"""
Crypto Signals MCP Server

stdio-based MCP server that reads signal data from S3
and exposes it as tools for Claude Code.

Covers all data from the signal engine:
  - 7 individual signals (VEP, SCI, LCS, FLOW, DPS, GRAV, CAP)
  - TDS (Trade Decision Score)
  - Entry conditions, direction, TP/invalidation
  - Volume profile (POC, HVN, LVN, VAH, VAL)
  - Rolling candle data (1m OHLCV + delta + vwap)
  - Derivatives data (funding, OI, mark/index price)
  - Historical archives (signals + candles)

Usage:
    python3 mcp_server/signal_server.py
"""

import io
import json
import os
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError
from mcp.server.fastmcp import FastMCP

# --- Config ---
S3_BUCKET = os.environ.get("S3_BUCKET", "crypto-collector-prod-data-720428162886")
AWS_REGION = os.environ.get("AWS_REGION", "eu-north-1")
S3_PREFIX = "signals"

# --- S3 client ---
s3_client = boto3.client("s3", region_name=AWS_REGION)

# --- MCP server ---
mcp = FastMCP(
    "crypto-signals",
    instructions=(
        "Crypto trading signal data from the signal engine. "
        "Provides real-time and historical signals for BTCUSDT and ETHUSDT "
        "including 7 component scores, TDS, volume profile, candle data, "
        "and derivatives data."
    ),
)


# =====================================================================
# S3 helpers
# =====================================================================


def _read_json(key: str) -> dict:
    """Read a JSON file from S3."""
    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        return json.loads(resp["Body"].read().decode("utf-8"))
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            return {"error": f"File not found: {key}"}
        raise


def _read_parquet(key: str, tail: int = 200):
    """Read a Parquet file from S3, return DataFrame."""
    import pandas as pd

    try:
        resp = s3_client.get_object(Bucket=S3_BUCKET, Key=key)
        data = resp["Body"].read()
        df = pd.read_parquet(io.BytesIO(data))
        if tail:
            df = df.tail(tail)
        return df
    except ClientError as e:
        code = e.response["Error"]["Code"]
        if code in ("NoSuchKey", "404"):
            return None
        raise


def _df_to_json(df, symbol: str = "") -> str:
    """Convert DataFrame to JSON string, optionally filtering by symbol."""
    if df is None or df.empty:
        return json.dumps({"error": "No data available"})
    if symbol:
        symbol = symbol.upper()
        df = df[df["symbol"] == symbol] if "symbol" in df.columns else df
    for col in df.select_dtypes(include=["datetime64", "datetimetz"]).columns:
        df[col] = df[col].astype(str)
    return json.dumps(df.to_dict(orient="records"), indent=2, default=str)


def _get_signals_latest() -> dict:
    """Read signals_latest.json from S3 (cached within request)."""
    return _read_json(f"{S3_PREFIX}/signals_latest.json")


def _get_signal_for_symbol(symbol: str) -> dict:
    """Extract signal for one symbol from latest."""
    symbol = symbol.upper()
    data = _get_signals_latest()
    if "error" in data:
        return data
    if symbol in data:
        return data[symbol]
    return {"error": f"Symbol {symbol} not found", "available": list(data.keys())}


# =====================================================================
# 1. OVERVIEW / DASHBOARD TOOLS
# =====================================================================


@mcp.tool()
def get_crypto_signals() -> str:
    """Get the latest trading signals for ALL tracked symbols (BTC + ETH).

    Returns complete signal output: TDS, entry_ok, direction,
    take-profit / invalidation levels, and all 7 component scores.
    """
    data = _get_signals_latest()
    return json.dumps(data, indent=2, default=str)


@mcp.tool()
def get_crypto_signal(symbol: str) -> str:
    """Get the latest trading signal for a specific symbol.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    return json.dumps(_get_signal_for_symbol(symbol), indent=2, default=str)


@mcp.tool()
def get_market_summary() -> str:
    """Get a high-level market summary dashboard.

    Returns per-symbol: price, TDS, direction, entry_ok status,
    and whether conditions favor trading.
    """
    data = _get_signals_latest()
    if "error" in data:
        return json.dumps(data)

    summary = {}
    for sym, sig in data.items():
        summary[sym] = {
            "price": sig.get("price"),
            "tds": sig.get("tds"),
            "direction": sig.get("direction"),
            "entry_ok": sig.get("entry_ok"),
            "sci_dir": sig.get("sci_dir"),
            "flow": sig.get("flow"),
            "cap": sig.get("cap"),
            "tp1": sig.get("tp1"),
            "inval": sig.get("inval"),
        }
    return json.dumps(summary, indent=2, default=str)


@mcp.tool()
def get_signal_comparison() -> str:
    """Compare BTC vs ETH signals side by side.

    Shows all 7 component scores + TDS + entry status for both symbols,
    highlighting divergences.
    """
    data = _get_signals_latest()
    if "error" in data:
        return json.dumps(data)

    score_keys = ["vep", "sci", "lcs", "flow", "dps", "grav", "cap", "tds"]
    comparison = {"symbols": {}, "divergences": []}

    for sym, sig in data.items():
        comparison["symbols"][sym] = {
            k: sig.get(k) for k in score_keys + ["entry_ok", "direction", "sci_dir"]
        }

    # Find divergences
    syms = list(data.keys())
    if len(syms) == 2:
        s1, s2 = data[syms[0]], data[syms[1]]
        for k in score_keys:
            v1, v2 = s1.get(k, 0), s2.get(k, 0)
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                diff = abs(v1 - v2)
                if diff > 15:
                    comparison["divergences"].append(
                        {"signal": k, syms[0]: v1, syms[1]: v2, "diff": round(diff, 2)}
                    )

    return json.dumps(comparison, indent=2, default=str)


# =====================================================================
# 2. TDS (TRADE DECISION SCORE) TOOLS
# =====================================================================


@mcp.tool()
def get_tds(symbol: str) -> str:
    """Get the Trade Decision Score (TDS) for a symbol.

    TDS is the weighted composite of all 7 signals (0-100).
    >= 75 with supporting conditions triggers entry.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)

    return json.dumps(
        {
            "symbol": symbol.upper(),
            "tds": sig.get("tds"),
            "entry_ok": sig.get("entry_ok"),
            "direction": sig.get("direction"),
            "weights": {
                "vep": 0.22, "sci": 0.20, "lcs": 0.18, "flow": 0.12,
                "dps": 0.10, "grav": 0.10, "cap": 0.08,
            },
        },
        indent=2,
        default=str,
    )


@mcp.tool()
def get_tds_history(symbol: str = "", date: str = "") -> str:
    """Get TDS score trend over time for a date.

    Shows how the Trade Decision Score evolved minute by minute.

    Args:
        symbol: BTCUSDT or ETHUSDT (optional, returns all if empty)
        date: YYYY-MM-DD (defaults to today)
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = _read_parquet(f"{S3_PREFIX}/archive/signals_1m/{date}.parquet", tail=500)
    if df is None:
        return json.dumps({"error": f"No signal archive for {date}"})
    if symbol:
        symbol = symbol.upper()
        df = df[df["symbol"] == symbol] if "symbol" in df.columns else df
    cols = ["ts", "symbol", "tds", "entry_ok", "direction"]
    cols = [c for c in cols if c in df.columns]
    return _df_to_json(df[cols])


# =====================================================================
# 3. INDIVIDUAL SIGNAL COMPONENT TOOLS
# =====================================================================


@mcp.tool()
def get_vep(symbol: str) -> str:
    """Get the Volatility Expansion Predictor (VEP) score for a symbol.

    VEP detects volatility compression → expansion.
    >70 = expansion likely, 50-70 = primed, <50 = normal.

    Uses: 5m range compression, volume activity, return noise.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)
    return json.dumps(
        {"symbol": symbol.upper(), "ts": sig.get("ts"), "price": sig.get("price"), "vep": sig.get("vep"), "weight": 0.22},
        indent=2, default=str,
    )


@mcp.tool()
def get_sci(symbol: str) -> str:
    """Get the Stop Cluster Impulse (SCI) score for a symbol.

    SCI detects stop sweep and reclaim patterns using candle structure.
    sci_dir: +1 = bullish reclaim, -1 = bearish reclaim, 0 = no sweep.

    Uses: 15m local high/low sweep detection, delta fraction.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)
    return json.dumps(
        {
            "symbol": symbol.upper(),
            "ts": sig.get("ts"),
            "price": sig.get("price"),
            "sci": sig.get("sci"),
            "sci_dir": sig.get("sci_dir"),
            "weight": 0.20,
        },
        indent=2, default=str,
    )


@mcp.tool()
def get_lcs(symbol: str) -> str:
    """Get the Liquidity Cascade Score (LCS) for a symbol.

    LCS detects forced directional moves (liquidation cascades).
    High score means strong velocity + volume + delta alignment.

    Uses: 5m velocity, volume z-score, delta z-score.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)
    return json.dumps(
        {"symbol": symbol.upper(), "ts": sig.get("ts"), "price": sig.get("price"), "lcs": sig.get("lcs"), "weight": 0.18},
        indent=2, default=str,
    )


@mcp.tool()
def get_flow(symbol: str) -> str:
    """Get the Flow Quality Score (FLOW) for a symbol.

    FLOW measures execution safety — how clean the move is.
    High efficiency = directional move without churn.
    Low FLOW = toxic/noisy environment.

    Uses: candle body/range efficiency, volume, churn.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)
    return json.dumps(
        {"symbol": symbol.upper(), "ts": sig.get("ts"), "price": sig.get("price"), "flow": sig.get("flow"), "weight": 0.12},
        indent=2, default=str,
    )


@mcp.tool()
def get_dps(symbol: str) -> str:
    """Get the Derivatives Pressure Score (DPS) for a symbol.

    DPS measures derivatives market pressure using open interest
    and funding rate relative to 24h baselines.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)
    return json.dumps(
        {"symbol": symbol.upper(), "ts": sig.get("ts"), "price": sig.get("price"), "dps": sig.get("dps"), "weight": 0.10},
        indent=2, default=str,
    )


@mcp.tool()
def get_grav(symbol: str) -> str:
    """Get the Gravity Score (GRAV) for a symbol.

    GRAV measures structural pull toward High Volume Nodes.
    High score = price near HVN (strong pull).
    Uses distance to nearest HVN normalized by ATR.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)
    return json.dumps(
        {"symbol": symbol.upper(), "ts": sig.get("ts"), "price": sig.get("price"), "grav": sig.get("grav"), "weight": 0.10},
        indent=2, default=str,
    )


@mcp.tool()
def get_cap(symbol: str) -> str:
    """Get the Cross-Asset Pressure (CAP) score for a symbol.

    CAP measures BTC/ETH alignment. High = stable/aligned regime.
    Low = divergence/unstable regime (dangerous for entries).

    Uses: 5m return divergence, 60m correlation.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)
    return json.dumps(
        {"symbol": symbol.upper(), "ts": sig.get("ts"), "price": sig.get("price"), "cap": sig.get("cap"), "weight": 0.08},
        indent=2, default=str,
    )


@mcp.tool()
def get_all_scores(symbol: str) -> str:
    """Get all 7 signal component scores for a symbol in one call.

    Returns VEP, SCI, LCS, FLOW, DPS, GRAV, CAP with their weights
    and individual interpretations.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)

    scores = {
        "symbol": symbol.upper(),
        "ts": sig.get("ts"),
        "price": sig.get("price"),
        "scores": {
            "vep":  {"value": sig.get("vep"),  "weight": 0.22, "signal": "Volatility Expansion Predictor"},
            "sci":  {"value": sig.get("sci"),  "weight": 0.20, "signal": "Stop Cluster Impulse", "direction": sig.get("sci_dir")},
            "lcs":  {"value": sig.get("lcs"),  "weight": 0.18, "signal": "Liquidity Cascade Score"},
            "flow": {"value": sig.get("flow"), "weight": 0.12, "signal": "Flow Quality"},
            "dps":  {"value": sig.get("dps"),  "weight": 0.10, "signal": "Derivatives Pressure"},
            "grav": {"value": sig.get("grav"), "weight": 0.10, "signal": "Gravity (profile pull)"},
            "cap":  {"value": sig.get("cap"),  "weight": 0.08, "signal": "Cross-Asset Pressure"},
        },
        "tds": sig.get("tds"),
        "entry_ok": sig.get("entry_ok"),
        "direction": sig.get("direction"),
    }
    return json.dumps(scores, indent=2, default=str)


# =====================================================================
# 4. ENTRY / TRADE CONDITION TOOLS
# =====================================================================


@mcp.tool()
def get_entry_signals() -> str:
    """Get entry signals — only symbols where entry_ok is True.

    Entry conditions: TDS >= 75, FLOW >= 50, CAP >= 45,
    plus SCI direction or strong LCS cascade (LCS >= 80).

    Returns direction (+1 long / -1 short), TP levels, invalidation.
    """
    data = _get_signals_latest()
    if "error" in data:
        return json.dumps(data)

    entries = {}
    for sym, sig in data.items():
        if sig.get("entry_ok"):
            entries[sym] = {
                "direction": sig.get("direction"),
                "tds": sig.get("tds"),
                "price": sig.get("price"),
                "tp1": sig.get("tp1"),
                "tp2": sig.get("tp2"),
                "tp3": sig.get("tp3"),
                "inval": sig.get("inval"),
                "sci_dir": sig.get("sci_dir"),
                "flow": sig.get("flow"),
                "cap": sig.get("cap"),
            }

    if not entries:
        return json.dumps({"message": "No active entry signals", "symbols_checked": list(data.keys())})

    return json.dumps(entries, indent=2, default=str)


@mcp.tool()
def get_tp_levels(symbol: str) -> str:
    """Get take-profit and invalidation levels for a symbol.

    TP levels are derived from volume profile HVN nodes.
    Invalidation is the nearest LVN beyond entry in opposite direction,
    or VA boundary, or 2x ATR fallback.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)
    return json.dumps(
        {
            "symbol": symbol.upper(),
            "price": sig.get("price"),
            "direction": sig.get("direction"),
            "tp1": sig.get("tp1"),
            "tp2": sig.get("tp2"),
            "tp3": sig.get("tp3"),
            "inval": sig.get("inval"),
            "entry_ok": sig.get("entry_ok"),
        },
        indent=2, default=str,
    )


@mcp.tool()
def get_entry_history(date: str = "", symbol: str = "") -> str:
    """Get historical entry signals for a date (only rows where entry_ok was True).

    Args:
        date: YYYY-MM-DD (defaults to today)
        symbol: BTCUSDT or ETHUSDT (optional)
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = _read_parquet(f"{S3_PREFIX}/archive/signals_1m/{date}.parquet", tail=0)
    if df is None:
        return json.dumps({"error": f"No signal archive for {date}"})
    if "entry_ok" in df.columns:
        df = df[df["entry_ok"] == True]  # noqa: E712
    if symbol:
        symbol = symbol.upper()
        if "symbol" in df.columns:
            df = df[df["symbol"] == symbol]
    return _df_to_json(df.tail(100))


# =====================================================================
# 5. VOLUME PROFILE TOOLS
# =====================================================================


@mcp.tool()
def get_volume_profile(symbol: str) -> str:
    """Get the full volume profile for a symbol.

    Returns POC, HVN array, LVN array, VAH, VAL, and gravity score.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    symbol = symbol.upper()
    data = _read_json(f"{S3_PREFIX}/volume_profile.json")
    if "error" in data:
        return json.dumps(data)
    if symbol in data:
        return json.dumps(data[symbol], indent=2, default=str)
    return json.dumps({"error": f"Symbol {symbol} not found", "available": list(data.keys())})


@mcp.tool()
def get_poc(symbol: str) -> str:
    """Get the Point of Control (POC) price level for a symbol.

    POC is the price level with the highest traded volume.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    symbol = symbol.upper()
    data = _read_json(f"{S3_PREFIX}/volume_profile.json")
    if "error" in data:
        return json.dumps(data)
    profile = data.get(symbol, {})
    return json.dumps(
        {
            "symbol": symbol,
            "poc": profile.get("poc"),
            "vah": profile.get("vah"),
            "val": profile.get("val"),
            "hvn_count": len(profile.get("hvn", [])),
            "lvn_count": len(profile.get("lvn", [])),
        },
        indent=2, default=str,
    )


@mcp.tool()
def get_hvn_levels(symbol: str) -> str:
    """Get High Volume Node (HVN) price levels for a symbol.

    HVNs are support/resistance levels where heavy volume traded.
    Used as take-profit targets and structural magnets.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    symbol = symbol.upper()
    data = _read_json(f"{S3_PREFIX}/volume_profile.json")
    if "error" in data:
        return json.dumps(data)
    profile = data.get(symbol, {})
    return json.dumps(
        {"symbol": symbol, "hvn": profile.get("hvn", []), "poc": profile.get("poc")},
        indent=2, default=str,
    )


@mcp.tool()
def get_lvn_levels(symbol: str) -> str:
    """Get Low Volume Node (LVN) price levels for a symbol.

    LVNs are price levels with thin volume — price moves fast through them.
    Used as invalidation levels (stops).

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    symbol = symbol.upper()
    data = _read_json(f"{S3_PREFIX}/volume_profile.json")
    if "error" in data:
        return json.dumps(data)
    profile = data.get(symbol, {})
    return json.dumps(
        {"symbol": symbol, "lvn": profile.get("lvn", [])},
        indent=2, default=str,
    )


@mcp.tool()
def get_value_area(symbol: str) -> str:
    """Get the Value Area (VAH + VAL) for a symbol.

    Value Area contains ~70% of traded volume.
    VAH = Value Area High, VAL = Value Area Low.
    Price outside VA tends to revert; inside VA is fair value.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    symbol = symbol.upper()
    data = _read_json(f"{S3_PREFIX}/volume_profile.json")
    if "error" in data:
        return json.dumps(data)
    profile = data.get(symbol, {})
    return json.dumps(
        {
            "symbol": symbol,
            "vah": profile.get("vah"),
            "val": profile.get("val"),
            "poc": profile.get("poc"),
        },
        indent=2, default=str,
    )


# =====================================================================
# 6. CANDLE DATA TOOLS
# =====================================================================


@mcp.tool()
def get_latest_candles(symbol: str, count: int = 60) -> str:
    """Get the most recent 1-minute candles from the rolling buffer.

    Returns OHLCV + delta + vwap for recent candles.

    Args:
        symbol: BTCUSDT or ETHUSDT
        count: Number of recent candles to return (default 60 = last hour)
    """
    df = _read_parquet(f"{S3_PREFIX}/candles_1m_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No candle data available"})
    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    return _df_to_json(df.tail(min(count, 500)))


@mcp.tool()
def get_candle_history(date: str, symbol: str = "") -> str:
    """Get historical 1-minute candle data for a specific date.

    Args:
        date: Date in YYYY-MM-DD format
        symbol: BTCUSDT or ETHUSDT (optional)
    """
    df = _read_parquet(f"{S3_PREFIX}/archive/candles_1m/{date}.parquet", tail=0)
    if df is None:
        return json.dumps({"error": f"No candle archive for {date}"})
    if symbol:
        symbol = symbol.upper()
        if "symbol" in df.columns:
            df = df[df["symbol"] == symbol]
    return _df_to_json(df.tail(200))


@mcp.tool()
def get_ohlcv(symbol: str, count: int = 30) -> str:
    """Get recent OHLCV (Open, High, Low, Close, Volume) summary for a symbol.

    Simpler view of candle data focused on price action.

    Args:
        symbol: BTCUSDT or ETHUSDT
        count: Number of candles (default 30 = last 30 minutes)
    """
    df = _read_parquet(f"{S3_PREFIX}/candles_1m_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No candle data available"})
    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    cols = [c for c in ["ts", "open", "high", "low", "close", "volume"] if c in df.columns]
    return _df_to_json(df[cols].tail(min(count, 500)))


@mcp.tool()
def get_delta(symbol: str, count: int = 60) -> str:
    """Get recent delta (buy vs sell volume) data for a symbol.

    Positive delta = more aggressive buying.
    Negative delta = more aggressive selling.

    Args:
        symbol: BTCUSDT or ETHUSDT
        count: Number of candles (default 60)
    """
    df = _read_parquet(f"{S3_PREFIX}/candles_1m_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No candle data available"})
    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    cols = [c for c in ["ts", "close", "volume", "delta", "taker_buy_volume"] if c in df.columns]
    return _df_to_json(df[cols].tail(min(count, 500)))


@mcp.tool()
def get_vwap(symbol: str, count: int = 60) -> str:
    """Get recent VWAP (Volume Weighted Average Price) data for a symbol.

    VWAP shows the average price weighted by volume.
    Price above VWAP = bullish tendency, below = bearish.

    Args:
        symbol: BTCUSDT or ETHUSDT
        count: Number of candles (default 60)
    """
    df = _read_parquet(f"{S3_PREFIX}/candles_1m_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No candle data available"})
    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    cols = [c for c in ["ts", "close", "vwap", "volume"] if c in df.columns]
    return _df_to_json(df[cols].tail(min(count, 500)))


# =====================================================================
# 7. DERIVATIVES DATA TOOLS
# =====================================================================


@mcp.tool()
def get_derivatives(symbol: str, count: int = 60) -> str:
    """Get recent derivatives data for a symbol.

    Returns mark price, index price, funding rate, and open interest.

    Args:
        symbol: BTCUSDT or ETHUSDT
        count: Number of recent data points (default 60)
    """
    df = _read_parquet(f"{S3_PREFIX}/derivatives_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No derivatives data available"})
    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    return _df_to_json(df.tail(min(count, 500)))


@mcp.tool()
def get_funding_rate(symbol: str) -> str:
    """Get the latest funding rate for a symbol.

    Positive funding = longs pay shorts (bullish crowd).
    Negative funding = shorts pay longs (bearish crowd).

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    df = _read_parquet(f"{S3_PREFIX}/derivatives_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No derivatives data available"})
    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    if df.empty:
        return json.dumps({"error": f"No derivatives data for {symbol}"})
    last = df.iloc[-1]
    return json.dumps(
        {
            "symbol": symbol,
            "funding_rate": float(last.get("funding_rate", 0)),
            "mark_price": float(last.get("mark_price", 0)),
            "index_price": float(last.get("index_price", 0)),
            "ts": str(last.get("ts", "")),
        },
        indent=2, default=str,
    )


@mcp.tool()
def get_open_interest(symbol: str) -> str:
    """Get the latest open interest for a symbol.

    Rising OI + price rise = new longs opening.
    Rising OI + price drop = new shorts opening.
    Falling OI = positions closing.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    df = _read_parquet(f"{S3_PREFIX}/derivatives_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No derivatives data available"})
    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    if df.empty:
        return json.dumps({"error": f"No derivatives data for {symbol}"})
    last = df.iloc[-1]
    return json.dumps(
        {
            "symbol": symbol,
            "open_interest": float(last.get("open_interest", 0)),
            "ts": str(last.get("ts", "")),
        },
        indent=2, default=str,
    )


# =====================================================================
# 8. HISTORICAL / ARCHIVE TOOLS
# =====================================================================


@mcp.tool()
def get_signal_history(date: str = "", symbol: str = "") -> str:
    """Get historical signal data for a specific date.

    Returns the full signal archive (all 7 scores + TDS + entry conditions)
    for each minute of the given date.

    Args:
        date: YYYY-MM-DD (defaults to today)
        symbol: BTCUSDT or ETHUSDT (optional)
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = _read_parquet(f"{S3_PREFIX}/archive/signals_1m/{date}.parquet", tail=500)
    if df is None:
        return json.dumps({"error": f"No signal archive for {date}"})
    return _df_to_json(df, symbol)


@mcp.tool()
def get_score_history(signal_name: str, date: str = "", symbol: str = "") -> str:
    """Get historical values for a specific signal component.

    Track how an individual signal (VEP, SCI, LCS, etc.) changed over a day.

    Args:
        signal_name: One of: vep, sci, lcs, flow, dps, grav, cap, tds
        date: YYYY-MM-DD (defaults to today)
        symbol: BTCUSDT or ETHUSDT (optional)
    """
    signal_name = signal_name.lower()
    valid = ["vep", "sci", "lcs", "flow", "dps", "grav", "cap", "tds"]
    if signal_name not in valid:
        return json.dumps({"error": f"Invalid signal: {signal_name}", "valid": valid})

    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = _read_parquet(f"{S3_PREFIX}/archive/signals_1m/{date}.parquet", tail=0)
    if df is None:
        return json.dumps({"error": f"No signal archive for {date}"})
    if symbol:
        symbol = symbol.upper()
        if "symbol" in df.columns:
            df = df[df["symbol"] == symbol]
    cols = [c for c in ["ts", "symbol", signal_name] if c in df.columns]
    # Include sci_dir when querying SCI (GAP 13: direction context)
    if signal_name == "sci" and "sci_dir" in df.columns:
        cols.append("sci_dir")
    return _df_to_json(df[cols].tail(500))


@mcp.tool()
def list_archive_dates() -> str:
    """List available dates in the signal archive.

    Shows which dates have historical signal data available.
    """
    try:
        resp = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=f"{S3_PREFIX}/archive/signals_1m/",
            MaxKeys=100,
        )
        dates = []
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".parquet"):
                date_str = key.split("/")[-1].replace(".parquet", "")
                dates.append(date_str)
        return json.dumps({"dates": sorted(dates), "count": len(dates)}, indent=2)
    except ClientError as e:
        return json.dumps({"error": str(e)})


# =====================================================================
# 9. VOLATILITY / REGIME TOOLS
# =====================================================================


@mcp.tool()
def get_volatility_status(symbol: str) -> str:
    """Get volatility status for a symbol based on VEP and candle data.

    Indicates whether the market is compressed, primed, or expanding.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)

    vep = sig.get("vep", 0)
    if vep > 70:
        regime = "EXPANSION_LIKELY"
    elif vep > 50:
        regime = "PRIMED"
    else:
        regime = "NORMAL"

    return json.dumps(
        {
            "symbol": symbol.upper(),
            "vep": vep,
            "volatility_regime": regime,
            "flow": sig.get("flow"),
            "lcs": sig.get("lcs"),
        },
        indent=2, default=str,
    )


@mcp.tool()
def get_market_regime() -> str:
    """Get the overall market regime assessment.

    Combines CAP (cross-asset alignment), VEP (volatility), and FLOW
    to classify the current trading environment.
    """
    data = _get_signals_latest()
    if "error" in data:
        return json.dumps(data)

    regime = {}
    for sym, sig in data.items():
        cap = sig.get("cap", 0)
        vep = sig.get("vep", 0)
        flow = sig.get("flow", 0)

        if cap < 40:
            alignment = "DIVERGENT"
        elif cap > 65:
            alignment = "ALIGNED"
        else:
            alignment = "MIXED"

        if vep > 70:
            vol = "HIGH_VOL"
        elif vep > 50:
            vol = "PRIMED"
        else:
            vol = "LOW_VOL"

        if flow > 65:
            quality = "CLEAN"
        elif flow > 45:
            quality = "MODERATE"
        else:
            quality = "NOISY"

        regime[sym] = {
            "cross_asset": alignment,
            "volatility": vol,
            "flow_quality": quality,
            "tradeable": cap > 45 and flow > 50,
            "scores": {"cap": cap, "vep": vep, "flow": flow},
        }

    return json.dumps(regime, indent=2, default=str)


# =====================================================================
# 10. DIAGNOSTICS / REASON TOOLS
# =====================================================================


@mcp.tool()
def get_signal_diagnostics(symbol: str) -> str:
    """Get the diagnostic reason breakdown for a symbol's signal computation.

    Returns the 'reason' field from the signal engine, which includes:
    - compression: range compression ratio (< 1 = compressed)
    - activity: volume activity ratio (> 1 = elevated)
    - noise: 5m return noise level
    - sci_dir: stop cluster sweep direction (+1/-1/0)
    - scores: all 7 raw signal scores

    This explains WHY the TDS value is what it is.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)

    result = {
        "symbol": symbol.upper(),
        "ts": sig.get("ts"),
        "price": sig.get("price"),
        "tds": sig.get("tds"),
        "entry_ok": sig.get("entry_ok"),
        "reason": sig.get("reason", {}),
    }
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def get_signal_reason(symbol: str) -> str:
    """Get a human-readable explanation of why the current signal is what it is.

    Interprets the diagnostic fields (compression, activity, noise, direction)
    into plain English for decision-making.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    sig = _get_signal_for_symbol(symbol)
    if "error" in sig:
        return json.dumps(sig)

    reason = sig.get("reason", {})
    tds = sig.get("tds", 0)
    entry_ok = sig.get("entry_ok", False)
    direction = sig.get("direction", 0)

    compression = reason.get("compression", 1.0)
    activity = reason.get("activity", 1.0)
    noise = reason.get("noise", 0.0)
    sci_dir = reason.get("sci_dir", 0)

    explanations = []

    # Compression
    if compression < 0.7:
        explanations.append(f"Range heavily compressed ({compression:.3f}x baseline) - volatility expansion likely")
    elif compression < 0.9:
        explanations.append(f"Range moderately compressed ({compression:.3f}x baseline)")
    elif compression > 1.3:
        explanations.append(f"Range expanded ({compression:.3f}x baseline) - active move in progress")
    else:
        explanations.append(f"Range normal ({compression:.3f}x baseline)")

    # Activity
    if activity > 1.5:
        explanations.append(f"Volume elevated ({activity:.3f}x baseline) - strong participation")
    elif activity > 1.1:
        explanations.append(f"Volume slightly above average ({activity:.3f}x baseline)")
    elif activity < 0.7:
        explanations.append(f"Volume low ({activity:.3f}x baseline) - thin market")
    else:
        explanations.append(f"Volume normal ({activity:.3f}x baseline)")

    # SCI direction
    if sci_dir == 1:
        explanations.append("Stop sweep detected BELOW - bullish reclaim pattern")
    elif sci_dir == -1:
        explanations.append("Stop sweep detected ABOVE - bearish reclaim pattern")

    # Entry
    if entry_ok:
        dir_str = "LONG" if direction == 1 else "SHORT" if direction == -1 else "NEUTRAL"
        explanations.append(f"Entry conditions MET - direction: {dir_str}")
    else:
        missing = []
        if tds < 75:
            missing.append(f"TDS={tds:.1f} (need >= 75)")
        if sig.get("flow", 0) < 50:
            missing.append(f"FLOW={sig.get('flow', 0):.1f} (need >= 50)")
        if sig.get("cap", 0) < 45:
            missing.append(f"CAP={sig.get('cap', 0):.1f} (need >= 45)")
        if missing:
            explanations.append(f"Entry conditions NOT met: {', '.join(missing)}")

    return json.dumps(
        {
            "symbol": symbol.upper(),
            "tds": tds,
            "entry_ok": entry_ok,
            "direction": direction,
            "explanation": explanations,
            "raw_diagnostics": reason,
        },
        indent=2, default=str,
    )


# =====================================================================
# 11. ARCHIVE LISTING TOOLS
# =====================================================================


@mcp.tool()
def list_candle_archive_dates() -> str:
    """List available dates in the candle archive.

    Shows which dates have historical 1-minute candle data available.
    """
    try:
        resp = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=f"{S3_PREFIX}/archive/candles_1m/",
            MaxKeys=100,
        )
        dates = []
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".parquet"):
                date_str = key.split("/")[-1].replace(".parquet", "")
                dates.append(date_str)
        return json.dumps({"dates": sorted(dates), "count": len(dates)}, indent=2)
    except ClientError as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
def list_s3_data_files() -> str:
    """List all data files currently stored in the signals S3 prefix.

    Shows rolling buffers, latest files, and archive structure.
    Useful for understanding what data is available.
    """
    try:
        resp = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=f"{S3_PREFIX}/",
            MaxKeys=200,
        )
        files = []
        for obj in resp.get("Contents", []):
            files.append({
                "key": obj["Key"],
                "size_kb": round(obj["Size"] / 1024, 1),
                "last_modified": str(obj["LastModified"]),
            })
        return json.dumps({"bucket": S3_BUCKET, "files": files, "count": len(files)}, indent=2)
    except ClientError as e:
        return json.dumps({"error": str(e)})


# =====================================================================
# 12. DERIVED FEATURES (computed on-the-fly from candle data)
# =====================================================================


@mcp.tool()
def get_derived_features(symbol: str) -> str:
    """Get derived rolling features computed from candle data.

    These intermediate values are used by the signal engine but not stored.
    This tool computes them on-the-fly from the rolling candle buffer:
    - range_5m: 5-minute sum of candle ranges
    - vol_5m: 5-minute sum of volume
    - delta_5m: 5-minute sum of delta
    - velocity_5m: absolute price change over 5 minutes
    - body_efficiency: latest candle body/range ratio
    - return_1m: latest 1-minute return

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    import numpy as np

    df = _read_parquet(f"{S3_PREFIX}/candles_1m_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No candle data available"})
    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    if df.empty or len(df) < 10:
        return json.dumps({"error": f"Insufficient candle data for {symbol}"})

    close = df["close"].astype(float)
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    opn = df["open"].astype(float)
    vol = df["volume"].astype(float)
    delta = df["delta"].astype(float) if "delta" in df.columns else vol * 0

    rng_1m = high - low
    range_5m = float(rng_1m.tail(5).sum())
    vol_5m = float(vol.tail(5).sum())
    delta_5m = float(delta.tail(5).sum())

    px = float(close.iloc[-1])
    px_5ago = float(close.iloc[-6]) if len(close) > 5 else float(close.iloc[0])
    velocity_5m = abs(px - px_5ago)

    last_range = float(rng_1m.iloc[-1])
    last_body = abs(float(close.iloc[-1]) - float(opn.iloc[-1]))
    body_eff = last_body / max(last_range, 1e-12)

    ret_1m = float(close.pct_change().iloc[-1]) if len(close) > 1 else 0.0

    # 24h baselines for context
    range_5m_series = rng_1m.rolling(5).sum()
    vol_5m_series = vol.rolling(5).sum()
    base_range = float(range_5m_series.rolling(1440, min_periods=60).median().iloc[-1]) if len(range_5m_series) > 60 else range_5m
    base_vol = float(vol_5m_series.rolling(1440, min_periods=60).median().iloc[-1]) if len(vol_5m_series) > 60 else vol_5m
    if np.isnan(base_range):
        base_range = range_5m
    if np.isnan(base_vol):
        base_vol = vol_5m

    return json.dumps(
        {
            "symbol": symbol,
            "ts": str(df["ts"].iloc[-1]) if "ts" in df.columns else None,
            "price": px,
            "features": {
                "range_5m": round(range_5m, 4),
                "vol_5m": round(vol_5m, 2),
                "delta_5m": round(delta_5m, 2),
                "velocity_5m": round(velocity_5m, 4),
                "body_efficiency": round(body_eff, 4),
                "return_1m": round(ret_1m, 8),
            },
            "baselines": {
                "range_5m_24h_median": round(base_range, 4),
                "vol_5m_24h_median": round(base_vol, 2),
                "compression_ratio": round(range_5m / max(base_range, 1e-12), 4),
                "activity_ratio": round(vol_5m / max(base_vol, 1e-12), 4),
            },
            "candle_count": len(df),
        },
        indent=2,
        default=str,
    )


# =====================================================================
# 13. DERIVATIVES HISTORY
# =====================================================================


@mcp.tool()
def get_derivatives_history(date: str, symbol: str = "") -> str:
    """Get historical derivatives data for a specific date.

    Returns funding rate, open interest, mark/index prices throughout the day.

    Args:
        date: Date in YYYY-MM-DD format
        symbol: BTCUSDT or ETHUSDT (optional)
    """
    df = _read_parquet(f"{S3_PREFIX}/archive/derivatives_1m/{date}.parquet", tail=0)
    if df is None:
        return json.dumps({"error": f"No derivatives archive for {date}"})
    if symbol:
        symbol = symbol.upper()
        if "symbol" in df.columns:
            df = df[df["symbol"] == symbol]
    return _df_to_json(df.tail(200))


@mcp.tool()
def list_derivatives_archive_dates() -> str:
    """List available dates in the derivatives archive.

    Shows which dates have historical derivatives data available.
    """
    try:
        resp = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=f"{S3_PREFIX}/archive/derivatives_1m/",
            MaxKeys=100,
        )
        dates = []
        for obj in resp.get("Contents", []):
            key = obj["Key"]
            if key.endswith(".parquet"):
                date_str = key.split("/")[-1].replace(".parquet", "")
                dates.append(date_str)
        return json.dumps({"dates": sorted(dates), "count": len(dates)}, indent=2)
    except ClientError as e:
        return json.dumps({"error": str(e)})


# =====================================================================
# 14. MULTI-TIMEFRAME VOLUME PROFILE (GAP 3)
# =====================================================================


@mcp.tool()
def get_multi_timeframe_profile(symbol: str) -> str:
    """Get volume profiles computed over multiple timeframes for a symbol.

    Computes separate volume profiles from the rolling candle buffer at:
    - 1h  (last 60 candles)
    - 4h  (last 240 candles)
    - 12h (last 720 candles)
    - 24h (all available candles, up to ~1500)

    Each profile includes POC, HVN, LVN, VAH, VAL.
    Shows how support/resistance evolves across timeframes.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from aws.signal_lambda.signal_engine import compute_volume_profile
    from aws.signal_lambda.config import VOLUME_PROFILE_BIN_SIZE

    df = _read_parquet(f"{S3_PREFIX}/candles_1m_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No candle data available"})

    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    if df.empty:
        return json.dumps({"error": f"No candle data for {symbol}"})

    bin_size = VOLUME_PROFILE_BIN_SIZE.get(symbol, 10.0)
    timeframes = {"1h": 60, "4h": 240, "12h": 720, "24h": len(df)}
    profiles = {}

    for tf_name, n_candles in timeframes.items():
        slice_df = df.tail(min(n_candles, len(df)))
        if len(slice_df) < 10:
            continue
        # compute_volume_profile expects a symbol column
        profile = compute_volume_profile(slice_df, symbol, bin_size)
        profile["candle_count"] = len(slice_df)
        profiles[tf_name] = profile

    return json.dumps(
        {"symbol": symbol, "profiles": profiles},
        indent=2, default=str,
    )


# =====================================================================
# 15. LONG/SHORT RATIO & POSITIONING DATA (GAP 8)
# =====================================================================


@mcp.tool()
def get_long_short_ratio(symbol: str, count: int = 60) -> str:
    """Get recent long/short ratio and taker data for a symbol.

    Shows crowd positioning, whale positioning, and taker aggression:
    - taker_buy_ratio: > 1 = more aggressive buying, < 1 = more selling
    - global_long_ratio: crowd long/short ratio (> 1 = more longs)
    - top_trader_long_ratio: whale long/short ratio

    Args:
        symbol: BTCUSDT or ETHUSDT
        count: Number of recent data points (default 60)
    """
    df = _read_parquet(f"{S3_PREFIX}/liquidations_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No long/short data available (pipeline may need first run)"})
    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    if df.empty:
        return json.dumps({"error": f"No long/short data for {symbol}"})
    return _df_to_json(df.tail(min(count, 500)))


@mcp.tool()
def get_positioning_summary(symbol: str) -> str:
    """Get a summary of current market positioning for a symbol.

    Analyzes crowd vs whale positioning and taker aggression to determine
    whether the market is overleveraged in one direction.

    Args:
        symbol: BTCUSDT or ETHUSDT
    """
    df = _read_parquet(f"{S3_PREFIX}/liquidations_rolling.parquet", tail=0)
    if df is None:
        return json.dumps({"error": "No positioning data available"})
    symbol = symbol.upper()
    if "symbol" in df.columns:
        df = df[df["symbol"] == symbol]
    if df.empty:
        return json.dumps({"error": f"No positioning data for {symbol}"})

    latest = df.iloc[-1]
    avg_5 = df.tail(5).mean(numeric_only=True)

    taker = float(latest.get("taker_buy_ratio", 1))
    global_lr = float(latest.get("global_long_ratio", 1))
    top_lr = float(latest.get("top_trader_long_ratio", 1))

    # Interpret
    if global_lr > 1.5:
        crowd = "HEAVILY_LONG"
    elif global_lr > 1.1:
        crowd = "SLIGHTLY_LONG"
    elif global_lr < 0.7:
        crowd = "HEAVILY_SHORT"
    elif global_lr < 0.9:
        crowd = "SLIGHTLY_SHORT"
    else:
        crowd = "BALANCED"

    if taker > 1.3:
        aggression = "AGGRESSIVE_BUYING"
    elif taker < 0.7:
        aggression = "AGGRESSIVE_SELLING"
    else:
        aggression = "BALANCED"

    summary = {
        "symbol": symbol,
        "current": {
            "taker_buy_ratio": round(taker, 4),
            "global_long_ratio": round(global_lr, 4),
            "top_trader_long_ratio": round(top_lr, 4),
        },
        "avg_5_periods": {
            "taker_buy_ratio": round(float(avg_5.get("taker_buy_ratio", 1)), 4),
            "global_long_ratio": round(float(avg_5.get("global_long_ratio", 1)), 4),
        },
        "interpretation": {
            "crowd_positioning": crowd,
            "taker_aggression": aggression,
            "contrarian_signal": crowd in ("HEAVILY_LONG", "HEAVILY_SHORT"),
        },
        "data_points": len(df),
    }
    return json.dumps(summary, indent=2, default=str)


# =====================================================================
# 16. DERIBIT DATA (GAP 9)
# =====================================================================

# The Deribit collector Lambda stores data under the "data/" S3 prefix.
# These tools read that existing data.

DERIBIT_PREFIX = "data"


@mcp.tool()
def get_options_surface(currency: str = "BTC", date: str = "") -> str:
    """Get options surface data (IV, Greeks) from Deribit collector.

    Returns options chain with implied volatility, delta, gamma, vega, theta
    for all active strikes and expirations.

    Args:
        currency: BTC or ETH (default BTC)
        date: YYYY-MM-DD (defaults to today)
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    currency = currency.upper()
    df = _read_parquet(f"{DERIBIT_PREFIX}/options_greeks/{currency}/{date}.parquet", tail=0)
    if df is None:
        return json.dumps({"error": f"No options data for {currency} on {date}"})
    return _df_to_json(df.tail(500))


@mcp.tool()
def get_orderbook_snapshot(date: str = "") -> str:
    """Get order book snapshot data from Deribit collector.

    Returns bid/ask depth for tracked instruments.

    Args:
        date: YYYY-MM-DD (defaults to today)
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = _read_parquet(f"{DERIBIT_PREFIX}/orderbook/{date}.parquet", tail=0)
    if df is None:
        return json.dumps({"error": f"No orderbook data for {date}"})
    return _df_to_json(df.tail(200))


@mcp.tool()
def get_deribit_open_interest(date: str = "") -> str:
    """Get Deribit open interest data (options + futures).

    Args:
        date: YYYY-MM-DD (defaults to today)
    """
    if not date:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = _read_parquet(f"{DERIBIT_PREFIX}/open_interest/{date}.parquet", tail=0)
    if df is None:
        return json.dumps({"error": f"No Deribit OI data for {date}"})
    return _df_to_json(df.tail(200))


@mcp.tool()
def list_deribit_data() -> str:
    """List all available Deribit collector data files in S3.

    Shows options surfaces, order books, open interest, and other data
    collected by the Deribit Lambda (runs every 15 minutes).
    """
    try:
        resp = s3_client.list_objects_v2(
            Bucket=S3_BUCKET,
            Prefix=f"{DERIBIT_PREFIX}/",
            MaxKeys=200,
        )
        files = []
        for obj in resp.get("Contents", []):
            files.append({
                "key": obj["Key"],
                "size_kb": round(obj["Size"] / 1024, 1),
                "last_modified": str(obj["LastModified"]),
            })
        return json.dumps({"bucket": S3_BUCKET, "files": files, "count": len(files)}, indent=2)
    except ClientError as e:
        return json.dumps({"error": str(e)})


# =====================================================================
# 17. TRADE TRACKING (GAP 11)
# =====================================================================


def _read_trades() -> list:
    """Read trades_executed.json from S3."""
    data = _read_json(f"{S3_PREFIX}/trades_executed.json")
    if "error" in data:
        return []
    if isinstance(data, list):
        return data
    return data.get("trades", [])


@mcp.tool()
def log_trade(
    symbol: str,
    direction: str,
    entry_price: float,
    size: float,
    tp1: float = 0,
    stop_loss: float = 0,
    notes: str = "",
) -> str:
    """Log a trade entry for tracking/journaling.

    Records trade metadata alongside the signal state at entry time.
    Use this for paper trading or tracking real entries.

    Args:
        symbol: BTCUSDT or ETHUSDT
        direction: LONG or SHORT
        entry_price: Entry price
        size: Position size
        tp1: Take profit target (optional)
        stop_loss: Stop loss / invalidation level (optional)
        notes: Free-text notes about the trade (optional)
    """
    trades = _read_trades()
    sig = _get_signal_for_symbol(symbol)

    trade = {
        "id": len(trades) + 1,
        "ts": datetime.now(timezone.utc).isoformat(),
        "symbol": symbol.upper(),
        "direction": direction.upper(),
        "entry_price": entry_price,
        "size": size,
        "tp1": tp1,
        "stop_loss": stop_loss,
        "status": "OPEN",
        "exit_price": None,
        "exit_ts": None,
        "pnl": None,
        "notes": notes,
        "signal_at_entry": {
            "tds": sig.get("tds"),
            "entry_ok": sig.get("entry_ok"),
            "direction": sig.get("direction"),
            "vep": sig.get("vep"),
            "sci": sig.get("sci"),
            "flow": sig.get("flow"),
            "cap": sig.get("cap"),
        } if "error" not in sig else {},
    }
    trades.append(trade)

    # Save back to S3
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=f"{S3_PREFIX}/trades_executed.json",
        Body=json.dumps({"trades": trades}, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return json.dumps({"message": "Trade logged", "trade": trade}, indent=2, default=str)


@mcp.tool()
def close_trade(trade_id: int, exit_price: float, notes: str = "") -> str:
    """Close an open trade and record the exit.

    Args:
        trade_id: The trade ID to close
        exit_price: Exit price
        notes: Exit notes (optional)
    """
    trades = _read_trades()
    trade = None
    for t in trades:
        if t.get("id") == trade_id:
            trade = t
            break

    if trade is None:
        return json.dumps({"error": f"Trade {trade_id} not found"})
    if trade.get("status") != "OPEN":
        return json.dumps({"error": f"Trade {trade_id} is already {trade.get('status')}"})

    trade["exit_price"] = exit_price
    trade["exit_ts"] = datetime.now(timezone.utc).isoformat()
    trade["status"] = "CLOSED"
    if notes:
        trade["notes"] = (trade.get("notes", "") + " | EXIT: " + notes).strip(" | ")

    # Compute PnL
    entry = trade.get("entry_price", 0)
    size = trade.get("size", 0)
    if trade.get("direction") == "LONG":
        trade["pnl"] = round((exit_price - entry) * size, 4)
    elif trade.get("direction") == "SHORT":
        trade["pnl"] = round((entry - exit_price) * size, 4)

    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=f"{S3_PREFIX}/trades_executed.json",
        Body=json.dumps({"trades": trades}, indent=2, default=str).encode("utf-8"),
        ContentType="application/json",
    )
    return json.dumps({"message": "Trade closed", "trade": trade}, indent=2, default=str)


@mcp.tool()
def get_trades(status: str = "") -> str:
    """Get all tracked trades, optionally filtered by status.

    Args:
        status: Filter by OPEN, CLOSED, or ALL (default: all)
    """
    trades = _read_trades()
    if status:
        status = status.upper()
        if status != "ALL":
            trades = [t for t in trades if t.get("status") == status]

    return json.dumps({"trades": trades, "count": len(trades)}, indent=2, default=str)


@mcp.tool()
def get_trade_performance() -> str:
    """Get overall trade performance summary.

    Returns win rate, total PnL, average PnL per trade,
    best/worst trades, and breakdown by symbol.
    """
    trades = _read_trades()
    closed = [t for t in trades if t.get("status") == "CLOSED" and t.get("pnl") is not None]

    if not closed:
        open_count = len([t for t in trades if t.get("status") == "OPEN"])
        return json.dumps({
            "message": "No closed trades yet",
            "open_trades": open_count,
            "total_trades": len(trades),
        }, indent=2)

    pnls = [t["pnl"] for t in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]

    perf = {
        "total_trades": len(trades),
        "closed_trades": len(closed),
        "open_trades": len(trades) - len(closed),
        "total_pnl": round(sum(pnls), 4),
        "win_rate": round(len(wins) / len(closed) * 100, 1) if closed else 0,
        "avg_pnl": round(sum(pnls) / len(closed), 4) if closed else 0,
        "best_trade": round(max(pnls), 4) if pnls else 0,
        "worst_trade": round(min(pnls), 4) if pnls else 0,
        "avg_win": round(sum(wins) / len(wins), 4) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 4) if losses else 0,
    }

    # By symbol
    by_symbol = {}
    for t in closed:
        sym = t.get("symbol", "UNKNOWN")
        if sym not in by_symbol:
            by_symbol[sym] = {"count": 0, "pnl": 0}
        by_symbol[sym]["count"] += 1
        by_symbol[sym]["pnl"] = round(by_symbol[sym]["pnl"] + t["pnl"], 4)
    perf["by_symbol"] = by_symbol

    return json.dumps(perf, indent=2, default=str)


if __name__ == "__main__":
    mcp.run()
