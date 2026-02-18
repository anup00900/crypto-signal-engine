"""
Signal Engine - 7 trading signals + TDS + volume profile

All signal computation from Signals_data.md, adapted for 1-minute candles
with delta and vwap derived from Binance klines.

Signals:
  1. VEP  - Volatility Expansion Predictor
  2. SCI  - Stop Cluster Impulse
  3. LCS  - Liquidity Cascade Score
  4. FLOW - Flow Quality Score
  5. DPS  - Derivatives Pressure Score
  6. GRAV - Gravity Score (volume profile)
  7. CAP  - Cross-Asset Pressure (BTC vs ETH)
  TDS  - Trade Decision Score (weighted combination)
"""

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def sigmoid(x: float) -> float:
    """Standard sigmoid, clamped input to avoid overflow."""
    x = max(-20.0, min(20.0, x))
    return 1.0 / (1.0 + math.exp(-x))


def safe_div(a: float, b: float) -> float:
    return a / (b + 1e-12)


def clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _med(arr: np.ndarray) -> float:
    return float(np.median(arr)) if arr.size else 0.0


def _std(arr: np.ndarray) -> float:
    return float(np.std(arr, ddof=0)) if arr.size else 0.0


def _closest_level(levels: List[float], price: float) -> float:
    if not levels:
        return 0.0
    return float(min(levels, key=lambda x: abs(x - price)))


def _next_levels(
    levels: List[float], price: float, direction: int
) -> List[float]:
    lv = sorted(float(x) for x in levels)
    if direction == 1:
        return [x for x in lv if x > price]
    if direction == -1:
        return [x for x in reversed(lv) if x < price]
    return []


# ---------------------------------------------------------------
# Volume Profile Builder
# ---------------------------------------------------------------

def compute_volume_profile(
    candles_df: pd.DataFrame,
    symbol: str,
    bin_size: float,
) -> Dict[str, Any]:
    """
    Build volume-at-price histogram from 1m candles.

    Returns dict with: poc, hvn, lvn, vah, val, gravity_score
    """
    sym_df = candles_df[candles_df["symbol"] == symbol] if "symbol" in candles_df.columns else candles_df
    if sym_df.empty:
        return {"poc": 0, "hvn": [], "lvn": [], "vah": 0, "val": 0}

    hist: Dict[float, float] = {}
    for _, row in sym_df.iterrows():
        low = float(row["low"])
        high = float(row["high"])
        volume = float(row["volume"])
        if high <= low or volume <= 0:
            continue
        bins = max(1, int((high - low) / bin_size) + 1)
        vol_per_bin = volume / bins
        for i in range(bins):
            price = low + i * bin_size
            key = round(price / bin_size) * bin_size
            hist[key] = hist.get(key, 0.0) + vol_per_bin

    if not hist:
        return {"poc": 0, "hvn": [], "lvn": [], "vah": 0, "val": 0}

    prices = np.array(sorted(hist.keys()))
    vols = np.array([hist[p] for p in prices])
    total_vol = vols.sum()

    # POC - Point of Control (highest volume price)
    poc_idx = int(np.argmax(vols))
    poc = float(prices[poc_idx])

    # HVN - High Volume Nodes (top 3)
    hvn_idx = np.argsort(vols)[::-1][:3]
    hvn = sorted(float(prices[i]) for i in hvn_idx)

    # LVN - Low Volume Nodes (bottom 2, excluding zero-volume)
    nonzero = vols > 0
    if nonzero.sum() > 2:
        nz_idx = np.where(nonzero)[0]
        nz_vols = vols[nz_idx]
        lvn_sort = np.argsort(nz_vols)[:2]
        lvn = sorted(float(prices[nz_idx[i]]) for i in lvn_sort)
    else:
        lvn = []

    # Value Area (70% of volume)
    sorted_idx = np.argsort(vols)[::-1]
    cum = 0.0
    included = []
    for i in sorted_idx:
        cum += vols[i]
        included.append(float(prices[i]))
        if cum >= total_vol * 0.7:
            break
    vah = max(included) if included else 0.0
    val_price = min(included) if included else 0.0

    return {
        "poc": poc,
        "hvn": hvn,
        "lvn": lvn,
        "vah": vah,
        "val": val_price,
    }


# ---------------------------------------------------------------
# Signal Engine
# ---------------------------------------------------------------

class SignalEngine:
    """Computes all 7 signals + TDS from candle and derivatives data."""

    def __init__(self, weights: Dict[str, float]):
        self.weights = weights

    # --- Window constants (in minutes) ---
    W5 = 5
    W15 = 15
    W60 = 60
    W24H = 1440  # 24 * 60

    def _sym_df(
        self, df: pd.DataFrame, symbol: str
    ) -> pd.DataFrame:
        """Filter dataframe by symbol if column exists."""
        if "symbol" in df.columns:
            return df[df["symbol"] == symbol].copy()
        return df.copy()

    # ==============================================================
    # Signal 1: Volatility Expansion Predictor (VEP)
    # ==============================================================

    def compute_vep(self, candles_df: pd.DataFrame, symbol: str) -> float:
        c = self._sym_df(candles_df, symbol)
        if len(c) < 120:
            return 50.0

        close = c["close"].astype(float)
        high = c["high"].astype(float)
        low = c["low"].astype(float)
        vol = c["volume"].astype(float)
        ret_1m = close.pct_change().fillna(0.0)

        rng_1m = high - low
        range_5m = rng_1m.rolling(self.W5).sum()
        vol_5m = vol.rolling(self.W5).sum()

        # 24h rolling medians as baselines
        base_range_5m = range_5m.rolling(self.W24H, min_periods=60).median()
        base_vol_5m = vol_5m.rolling(self.W24H, min_periods=60).median()

        r5 = float(range_5m.iloc[-1])
        v5 = float(vol_5m.iloc[-1])

        br5 = float(base_range_5m.iloc[-1]) if not np.isnan(base_range_5m.iloc[-1]) else max(r5, 1e-12)
        bv5 = float(base_vol_5m.iloc[-1]) if not np.isnan(base_vol_5m.iloc[-1]) else max(v5, 1e-12)

        compression = safe_div(r5, br5)
        activity = safe_div(v5, bv5)
        noise = _std(ret_1m.tail(self.W5).values)
        noise_base = _std(ret_1m.tail(self.W60).values) + 1e-12

        vep_raw = (
            -1.4 * (compression - 1.0)
            + 0.9 * (activity - 1.0)
            - 1.0 * (noise / noise_base)
        )
        return float(100.0 * sigmoid(vep_raw))

    # ==============================================================
    # Signal 2: Stop Cluster Impulse (SCI)
    # ==============================================================

    def compute_sci(
        self, candles_df: pd.DataFrame, symbol: str
    ) -> Tuple[float, int]:
        """Returns (sci_score, sci_direction)."""
        c = self._sym_df(candles_df, symbol)
        if len(c) < self.W15:
            return 0.0, 0

        high = c["high"].astype(float)
        low = c["low"].astype(float)
        close = c["close"].astype(float)
        vol = c["volume"].astype(float)
        delta = c["delta"].astype(float)

        local_high = float(high.tail(self.W15).max())
        local_low = float(low.tail(self.W15).min())

        last_high = float(high.iloc[-1])
        last_low = float(low.iloc[-1])
        last_close = float(close.iloc[-1])

        sci_dir = 0
        if last_low < local_low and last_close > local_low:
            sci_dir = 1   # bullish sweep & reclaim
        elif last_high > local_high and last_close < local_high:
            sci_dir = -1  # bearish sweep & reclaim

        if sci_dir == 0:
            return 0.0, 0

        # Strength: directional delta fraction over 5m
        d5 = float(delta.tail(self.W5).sum())
        v5 = float(vol.tail(self.W5).sum())
        dir_frac = abs(d5) / (v5 + 1e-12)

        sci = float(100.0 * sigmoid((dir_frac - 0.55) * 6.0))
        return sci, sci_dir

    # ==============================================================
    # Signal 3: Liquidity Cascade Score (LCS)
    # ==============================================================

    def compute_lcs(self, candles_df: pd.DataFrame, symbol: str) -> float:
        c = self._sym_df(candles_df, symbol)
        if len(c) < 120:
            return 50.0

        close = c["close"].astype(float)
        vol = c["volume"].astype(float)
        delta = c["delta"].astype(float)

        px = float(close.iloc[-1])
        close_5m_ago = float(close.iloc[-1 - self.W5]) if len(close) > self.W5 else float(close.iloc[0])
        velocity = abs(px - close_5m_ago)

        vol_5m = vol.rolling(self.W5).sum()
        delta_5m = delta.rolling(self.W5).sum()

        v5 = float(vol_5m.iloc[-1])
        d5 = float(delta_5m.iloc[-1])

        # Baselines from 24h medians
        vel_hist = close.diff(self.W5).abs().dropna().values
        vel_base = float(np.median(vel_hist[-self.W24H:])) if vel_hist.size else max(velocity, 1.0)

        bv5 = float(vol_5m.rolling(self.W24H, min_periods=60).median().iloc[-1])
        if np.isnan(bv5):
            bv5 = max(v5, 1e-12)

        d_hist = np.abs(delta_5m.dropna().values)
        d_base = float(np.median(d_hist[-self.W24H:])) if d_hist.size else max(abs(d5), 1.0)

        vel_z = safe_div(velocity, vel_base)
        vol_z = safe_div(v5, bv5)
        d_z = safe_div(abs(d5), d_base)

        lcs_raw = 0.9 * (vel_z - 1.0) + 0.8 * (vol_z - 1.0) + 0.7 * (d_z - 1.0)
        return float(100.0 * sigmoid(lcs_raw))

    # ==============================================================
    # Signal 4: Flow Quality Score (FLOW)
    # ==============================================================

    def compute_flow(self, candles_df: pd.DataFrame, symbol: str) -> float:
        c = self._sym_df(candles_df, symbol)
        if len(c) < self.W60:
            return 50.0

        close = c["close"].astype(float)
        opn = c["open"].astype(float)
        high = c["high"].astype(float)
        low = c["low"].astype(float)
        vol = c["volume"].astype(float)
        ret_1m = close.pct_change().fillna(0.0)

        rng_1m = (high - low).replace(0.0, np.nan).ffill().fillna(1e-12)
        body_1m = (close - opn).abs()

        eff = float(safe_div(float(body_1m.iloc[-1]), float(rng_1m.iloc[-1])))

        vol_5m = vol.rolling(self.W5).sum()
        bv5 = float(vol_5m.rolling(self.W24H, min_periods=60).median().iloc[-1])
        if np.isnan(bv5):
            bv5 = float(vol_5m.iloc[-1]) + 1e-12
        vol_z = safe_div(float(vol_5m.iloc[-1]), bv5)

        churn = _std(ret_1m.tail(self.W5).values)
        churn_base = _std(ret_1m.tail(self.W60).values) + 1e-12
        churn_rel = churn / churn_base

        flow_raw = 2.0 * (eff - 0.45) + 0.8 * (vol_z - 1.0) - 1.0 * (churn_rel - 1.0)
        return float(100.0 * sigmoid(flow_raw))

    # ==============================================================
    # Signal 5: Derivatives Pressure Score (DPS)
    # ==============================================================

    def compute_dps(
        self, derivatives_df: pd.DataFrame, symbol: str
    ) -> float:
        c = self._sym_df(derivatives_df, symbol)
        if c.empty or len(c) < 10:
            return 50.0

        oi = c["open_interest"].astype(float)
        funding = c["funding_rate"].astype(float)

        oi_med = float(oi.rolling(self.W24H, min_periods=10).median().iloc[-1])
        if np.isnan(oi_med):
            oi_med = float(oi.median())
        oi_z = safe_div(float(oi.iloc[-1]), max(oi_med, 1e-12))

        fund_med = float(funding.rolling(self.W24H, min_periods=10).median().iloc[-1])
        if np.isnan(fund_med):
            fund_med = float(funding.median())
        fund_z = safe_div(float(funding.iloc[-1]), abs(fund_med) + 1e-12)

        dps_raw = (oi_z - 1.0) + (fund_z - 1.0)
        return float(100.0 * sigmoid(dps_raw))

    # ==============================================================
    # Signal 6: Gravity Score (GRAV)
    # ==============================================================

    def compute_grav(
        self,
        candles_df: pd.DataFrame,
        symbol: str,
        profile: Dict[str, Any],
    ) -> float:
        c = self._sym_df(candles_df, symbol)
        hvn = profile.get("hvn", [])
        if not hvn or c.empty:
            return 50.0

        px = float(c["close"].astype(float).iloc[-1])
        nearest_hvn = _closest_level(hvn, px)

        rng_1m = (c["high"].astype(float) - c["low"].astype(float))
        atr_proxy = float(np.median(rng_1m.tail(self.W60).values) * 60.0) if len(rng_1m) >= self.W60 else float(np.median(rng_1m.values) * 60.0)

        dist_norm = abs(px - nearest_hvn) / (atr_proxy + 1e-12)
        return float(100.0 * sigmoid(-2.5 * (dist_norm - 0.15)))

    # ==============================================================
    # Signal 7: Cross-Asset Pressure (CAP)
    # ==============================================================

    def compute_cap(self, candles_df: pd.DataFrame) -> float:
        """
        Compute CAP from BTC and ETH candles together.
        High = stable/aligned, Low = divergence/unstable.
        """
        btc = self._sym_df(candles_df, "BTCUSDT")
        eth = self._sym_df(candles_df, "ETHUSDT")

        if btc.empty or eth.empty or len(btc) < 120 or len(eth) < 120:
            return 50.0

        b_ret = btc["close"].astype(float).pct_change().fillna(0.0)
        e_ret = eth["close"].astype(float).pct_change().fillna(0.0)

        # 5m divergence
        b5 = float(b_ret.tail(self.W5).sum())
        e5 = float(e_ret.tail(self.W5).sum())
        divergence = abs(b5 - e5)

        # 60m correlation
        b60 = b_ret.tail(self.W60).values
        e60 = e_ret.tail(self.W60).values
        if np.std(b60) > 0 and np.std(e60) > 0:
            corr = float(np.corrcoef(b60, e60)[0, 1])
        else:
            corr = 1.0

        div_term = sigmoid(-divergence * 40.0)
        corr_term = clamp((corr + 1.0) / 2.0, 0.0, 1.0)

        cap = 100.0 * (0.55 * div_term + 0.45 * corr_term)
        return float(clamp(cap, 0.0, 100.0))

    # ==============================================================
    # Compute all signals for one symbol
    # ==============================================================

    def compute_all(
        self,
        candles_df: pd.DataFrame,
        derivatives_df: pd.DataFrame,
        profile: Dict[str, Any],
        symbol: str,
        cap_score: float,
    ) -> Optional[Dict[str, Any]]:
        """
        Compute all 7 signals, TDS, entry logic, TP/invalidation.

        Args:
            candles_df: Full rolling candles (all symbols)
            derivatives_df: Full rolling derivatives (all symbols)
            profile: Volume profile dict for this symbol
            symbol: e.g. "BTCUSDT"
            cap_score: Pre-computed CAP (needs both BTC+ETH)
        """
        sym_candles = self._sym_df(candles_df, symbol)
        if sym_candles.empty or len(sym_candles) < 120:
            return None

        px = float(sym_candles["close"].astype(float).iloc[-1])
        ts = sym_candles["ts"].iloc[-1]

        vep = self.compute_vep(candles_df, symbol)
        sci, sci_dir = self.compute_sci(candles_df, symbol)
        lcs = self.compute_lcs(candles_df, symbol)
        flow = self.compute_flow(candles_df, symbol)
        dps = self.compute_dps(derivatives_df, symbol)
        grav = self.compute_grav(candles_df, symbol, profile)
        cap = cap_score

        # Compute intermediate values for the reason log
        vol = sym_candles["volume"].astype(float)
        rng_1m = sym_candles["high"].astype(float) - sym_candles["low"].astype(float)
        range_5m = rng_1m.rolling(self.W5).sum()
        vol_5m = vol.rolling(self.W5).sum()
        base_range_5m = range_5m.rolling(self.W24H, min_periods=60).median()
        base_vol_5m = vol_5m.rolling(self.W24H, min_periods=60).median()
        r5 = float(range_5m.iloc[-1])
        br5 = float(base_range_5m.iloc[-1]) if not np.isnan(base_range_5m.iloc[-1]) else max(r5, 1e-12)
        v5 = float(vol_5m.iloc[-1])
        bv5 = float(base_vol_5m.iloc[-1]) if not np.isnan(base_vol_5m.iloc[-1]) else max(v5, 1e-12)
        ret_1m = sym_candles["close"].astype(float).pct_change().fillna(0.0)

        compression = safe_div(r5, br5)
        activity = safe_div(v5, bv5)
        noise = _std(ret_1m.tail(self.W5).values)

        # TDS - weighted combination
        scores = {
            "vep": vep, "sci": sci, "lcs": lcs, "flow": flow,
            "dps": dps, "grav": grav, "cap": cap,
        }
        tds = 0.0
        for k, w in self.weights.items():
            tds += w * scores.get(k, 0.0)
        tds = clamp(tds, 0.0, 100.0)

        # Entry logic
        entry_ok = tds >= 75.0 and flow >= 50.0 and cap >= 45.0

        direction = 0
        if entry_ok:
            if sci_dir != 0:
                direction = sci_dir
            elif lcs >= 80.0:
                d5 = float(sym_candles["delta"].astype(float).tail(self.W5).sum())
                direction = 1 if d5 > 0 else -1

        # TP + Invalidation from profile
        tp1 = tp2 = tp3 = inval = 0.0
        hvn = profile.get("hvn", [])
        lvn = profile.get("lvn", [])

        if direction != 0 and hvn:
            nxt = _next_levels(hvn, px, direction)
            if len(nxt) >= 1:
                tp1 = nxt[0]
            if len(nxt) >= 2:
                tp2 = nxt[1]
            if len(nxt) >= 3:
                tp3 = nxt[2]

            if lvn:
                if direction == 1:
                    below = [x for x in lvn if x < px]
                    inval = max(below) if below else profile.get("val", 0.0)
                else:
                    above = [x for x in lvn if x > px]
                    inval = min(above) if above else profile.get("vah", 0.0)

            if inval == 0.0:
                rng_1m = sym_candles["high"].astype(float) - sym_candles["low"].astype(float)
                atr1h = float(np.median(rng_1m.tail(self.W60).values))
                inval = (px - 2.0 * atr1h) if direction == 1 else (px + 2.0 * atr1h)

        ts_str = ts.isoformat() if hasattr(ts, "isoformat") else str(ts)

        reason = {
            "scores": {k: round(v, 2) for k, v in scores.items()},
            "compression": round(compression, 4),
            "activity": round(activity, 4),
            "noise": round(noise, 8),
            "sci_dir": sci_dir,
        }

        return {
            "ts": ts_str,
            "symbol": symbol,
            "price": round(px, 2),
            "vep": round(vep, 1),
            "sci": round(sci, 1),
            "sci_dir": int(sci_dir),
            "lcs": round(lcs, 1),
            "flow": round(flow, 1),
            "dps": round(dps, 1),
            "grav": round(grav, 1),
            "cap": round(cap, 1),
            "tds": round(tds, 1),
            "entry_ok": bool(entry_ok),
            "direction": int(direction),
            "tp1": round(float(tp1), 2),
            "tp2": round(float(tp2), 2),
            "tp3": round(float(tp3), 2),
            "inval": round(float(inval), 2),
            "reason": reason,
        }
