"""
Binance Futures REST API fetcher

Lightweight synchronous HTTP calls using urllib.request (stdlib).
No authentication required for public market data endpoints.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List
from urllib.request import urlopen, Request

from .config import BINANCE_FUTURES_BASE


def _get_json(url: str, timeout: int = 10) -> Any:
    """Fetch JSON from a URL using stdlib (no extra deps)."""
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def fetch_klines(
    symbol: str, interval: str = "1m", limit: int = 3
) -> List[Dict[str, Any]]:
    """
    Fetch recent klines from Binance Futures.

    Returns list of dicts with computed delta and vwap:
      delta = 2 * taker_buy_volume - total_volume
      vwap  = quote_volume / volume
    """
    url = (
        f"{BINANCE_FUTURES_BASE}/klines"
        f"?symbol={symbol}&interval={interval}&limit={limit}"
    )
    raw = _get_json(url)

    candles = []
    for k in raw:
        # Binance kline array indices:
        # 0=open_time, 1=open, 2=high, 3=low, 4=close, 5=volume,
        # 6=close_time, 7=quote_volume, 8=trades,
        # 9=taker_buy_base_vol, 10=taker_buy_quote_vol, 11=ignore
        volume = float(k[5])
        quote_volume = float(k[7])
        taker_buy_volume = float(k[9])

        candles.append({
            "ts": datetime.fromtimestamp(k[0] / 1000, tz=timezone.utc).isoformat(),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": volume,
            "quote_volume": quote_volume,
            "trades": int(k[8]),
            "taker_buy_volume": taker_buy_volume,
            "taker_buy_quote_volume": float(k[10]),
            "delta": 2.0 * taker_buy_volume - volume,
            "vwap": quote_volume / volume if volume > 0 else float(k[4]),
        })

    return candles


def fetch_premium_index(symbol: str) -> Dict[str, Any]:
    """
    Fetch mark price, index price, and funding rate.
    """
    url = f"{BINANCE_FUTURES_BASE}/premiumIndex?symbol={symbol}"
    data = _get_json(url)
    return {
        "mark_price": float(data["markPrice"]),
        "index_price": float(data["indexPrice"]),
        "funding_rate": float(data["lastFundingRate"]),
    }


def fetch_open_interest(symbol: str) -> Dict[str, Any]:
    """
    Fetch current open interest.
    """
    url = f"{BINANCE_FUTURES_BASE}/openInterest?symbol={symbol}"
    data = _get_json(url)
    return {
        "open_interest": float(data["openInterest"]),
        "symbol": data["symbol"],
        "time": datetime.fromtimestamp(
            data["time"] / 1000, tz=timezone.utc
        ).isoformat(),
    }


def fetch_long_short_ratio(symbol: str, limit: int = 30) -> List[Dict[str, Any]]:
    """
    Fetch long/short ratio and taker buy/sell data from Binance Futures.

    Uses three public endpoints:
    - globalLongShortAccountRatio: crowd positioning
    - topLongShortPositionRatio: whale positioning
    - takerlongshortRatio: taker aggression

    Returns list of combined snapshots.
    """
    data_base = BINANCE_FUTURES_BASE.replace("/fapi/v1", "/futures/data")
    snapshots = []

    try:
        # Taker buy/sell ratio
        url = f"{data_base}/takerlongshortRatio?symbol={symbol}&period=5m&limit={limit}"
        taker = _get_json(url)

        # Global long/short account ratio
        url2 = f"{data_base}/globalLongShortAccountRatio?symbol={symbol}&period=5m&limit={limit}"
        global_ls = _get_json(url2)

        # Top trader long/short
        url3 = f"{data_base}/topLongShortPositionRatio?symbol={symbol}&period=5m&limit={limit}"
        top_ls = _get_json(url3)

        # Merge by timestamp
        taker_map = {int(d.get("timestamp", 0)): d for d in taker}
        global_map = {int(d.get("timestamp", 0)): d for d in global_ls}
        top_map = {int(d.get("timestamp", 0)): d for d in top_ls}

        all_ts = sorted(set(taker_map.keys()) | set(global_map.keys()) | set(top_map.keys()))
        for ts_ms in all_ts[-limit:]:
            t = taker_map.get(ts_ms, {})
            g = global_map.get(ts_ms, {})
            tp = top_map.get(ts_ms, {})
            snapshots.append({
                "ts": datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat(),
                "symbol": symbol,
                "taker_buy_ratio": float(t.get("buySellRatio", 0)),
                "taker_buy_vol": float(t.get("buyVol", 0)),
                "taker_sell_vol": float(t.get("sellVol", 0)),
                "global_long_ratio": float(g.get("longShortRatio", 0)),
                "global_long_account": float(g.get("longAccount", 0)),
                "top_trader_long_ratio": float(tp.get("longShortRatio", 0)),
                "top_trader_long_account": float(tp.get("longAccount", 0)),
            })
    except Exception:
        pass

    return snapshots


def fetch_all(symbols: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Fetch klines + premium index + open interest + long/short ratios.
    Total: 6 endpoints x len(symbols) HTTP calls.
    """
    result = {}
    for sym in symbols:
        result[sym] = {
            "candles": fetch_klines(sym, interval="1m", limit=3),
            "premium": fetch_premium_index(sym),
            "oi": fetch_open_interest(sym),
            "long_short": fetch_long_short_ratio(sym, limit=30),
        }
    return result
