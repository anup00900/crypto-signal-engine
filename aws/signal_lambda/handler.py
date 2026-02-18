"""
AWS Lambda Handler for Signal Engine

Triggered every 1 minute by EventBridge.
Fetches Binance data, manages S3 rolling buffers, computes signals.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict

# Add project root for imports (handler.py → signal_lambda/ → aws/ → project_root/)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
from loguru import logger

# Configure logging for Lambda
logger.remove()
logger.add(sys.stderr, level="INFO",
           format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {message}")


def lambda_handler(event: Dict[str, Any], context: Any) -> Dict[str, Any]:
    """
    Signal Engine Lambda entry point.

    Pipeline:
      1. Fetch Binance REST data (6 HTTP calls)
      2. Load rolling buffers from S3
      3. Append new data, trim to 24h
      4. Every 5 min: recompute volume profile
      5. Compute 7 signals + TDS for each symbol
      6. Save everything back to S3
    """
    from aws.s3_storage import S3Storage
    from aws.signal_lambda import binance_fetcher
    from aws.signal_lambda.candle_store import CandleStore
    from aws.signal_lambda.config import (
        ROLLING_CANDLE_LIMIT,
        ROLLING_DERIV_LIMIT,
        ROLLING_LIQUIDATION_LIMIT,
        S3_PREFIX,
        SIGNAL_WEIGHTS,
        SYMBOLS,
        VOLUME_PROFILE_BIN_SIZE,
        VOLUME_PROFILE_INTERVAL_MIN,
    )
    from aws.signal_lambda.signal_engine import SignalEngine, compute_volume_profile

    now = datetime.now(timezone.utc)
    logger.info(f"Signal engine invoked at {now.isoformat()}")

    bucket_name = os.environ.get("S3_BUCKET", "ailerlabs-crypto-data")

    try:
        # --- 1. Init storage ---
        s3 = S3Storage(bucket_name)
        store = CandleStore(s3, S3_PREFIX)

        # --- 2. Fetch from Binance ---
        logger.info(f"Fetching Binance data for {SYMBOLS}")
        raw = binance_fetcher.fetch_all(SYMBOLS)

        # --- 3. Load existing rolling buffers ---
        candles_df = store.load_rolling_candles()
        deriv_df = store.load_rolling_derivatives()

        # --- 4. Build new candle rows ---
        new_candle_rows = []
        new_deriv_rows = []

        for sym, data in raw.items():
            for candle in data["candles"]:
                new_candle_rows.append({
                    "ts": candle["ts"],
                    "symbol": sym,
                    "open": candle["open"],
                    "high": candle["high"],
                    "low": candle["low"],
                    "close": candle["close"],
                    "volume": candle["volume"],
                    "quote_volume": candle["quote_volume"],
                    "trades": candle["trades"],
                    "taker_buy_volume": candle["taker_buy_volume"],
                    "taker_buy_quote_volume": candle["taker_buy_quote_volume"],
                    "delta": candle["delta"],
                    "vwap": candle["vwap"],
                })

            prem = data["premium"]
            oi = data["oi"]
            new_deriv_rows.append({
                "ts": oi["time"],  # Use Binance-reported OI timestamp
                "symbol": sym,
                "mark_price": prem["mark_price"],
                "index_price": prem["index_price"],
                "funding_rate": prem["funding_rate"],
                "open_interest": oi["open_interest"],
            })

        # --- 4b. Build long/short ratio rows ---
        new_liq_rows = []
        for sym, data in raw.items():
            for ls in data.get("long_short", []):
                new_liq_rows.append({
                    "time": ls["ts"],
                    "symbol": sym,
                    "taker_buy_ratio": ls["taker_buy_ratio"],
                    "taker_buy_vol": ls["taker_buy_vol"],
                    "taker_sell_vol": ls["taker_sell_vol"],
                    "global_long_ratio": ls["global_long_ratio"],
                    "top_trader_long_ratio": ls["top_trader_long_ratio"],
                })

        # --- 5. Append + trim ---
        candles_df = CandleStore.append_candles(
            candles_df, new_candle_rows, limit=ROLLING_CANDLE_LIMIT
        )
        deriv_df = CandleStore.append_candles(
            deriv_df, new_deriv_rows, limit=ROLLING_DERIV_LIMIT
        )

        # Liquidations rolling buffer
        liq_df = store.load_rolling_liquidations()
        if new_liq_rows:
            new_liq_df = pd.DataFrame(new_liq_rows)
            if "time" in new_liq_df.columns:
                new_liq_df["time"] = pd.to_datetime(new_liq_df["time"], utc=True)
            if liq_df.empty:
                liq_df = new_liq_df
            else:
                liq_df = pd.concat([liq_df, new_liq_df], ignore_index=True)
                if "time" in liq_df.columns and "symbol" in liq_df.columns:
                    liq_df = liq_df.drop_duplicates(
                        subset=["time", "symbol"], keep="last"
                    )
                    liq_df = liq_df.sort_values("time").reset_index(drop=True)
                # Trim per symbol
                parts = []
                for sym in liq_df["symbol"].unique():
                    parts.append(liq_df[liq_df["symbol"] == sym].tail(ROLLING_LIQUIDATION_LIMIT))
                liq_df = pd.concat(parts, ignore_index=True)

        logger.info(
            f"Rolling buffers: {len(candles_df)} candle rows, "
            f"{len(deriv_df)} deriv rows, {len(liq_df)} liq rows"
        )

        # --- 6. Volume profile (every 5 min) ---
        should_recompute_profile = (now.minute % VOLUME_PROFILE_INTERVAL_MIN == 0)

        if should_recompute_profile:
            logger.info("Recomputing volume profile")
            profile_all = {}
            for sym in SYMBOLS:
                bin_size = VOLUME_PROFILE_BIN_SIZE.get(sym, 10.0)
                profile_all[sym] = compute_volume_profile(
                    candles_df, sym, bin_size
                )
            store.save_volume_profile(profile_all)
        else:
            profile_all = store.load_volume_profile()

        # --- 7. Compute signals ---
        engine = SignalEngine(SIGNAL_WEIGHTS)

        # CAP needs both symbols
        cap_score = engine.compute_cap(candles_df)

        signals_output = {}
        signal_rows = []

        for sym in SYMBOLS:
            profile = profile_all.get(sym, {})
            result = engine.compute_all(
                candles_df, deriv_df, profile, sym, cap_score
            )
            if result:
                signals_output[sym] = result
                signal_rows.append(result)
                logger.info(
                    f"{sym}: TDS={result['tds']}, "
                    f"entry={result['entry_ok']}, dir={result['direction']}"
                )

        # --- 8. Save everything ---
        store.save_rolling_candles(candles_df)
        store.save_rolling_derivatives(deriv_df)
        if not liq_df.empty:
            store.save_rolling_liquidations(liq_df)
        store.save_signals_latest(signals_output)

        # Daily archives
        if signal_rows:
            signals_archive_df = pd.DataFrame(signal_rows)
            store.append_to_daily_archive(signals_archive_df, "signals_1m")

        # Archive new candles too
        if new_candle_rows:
            new_candles_df = pd.DataFrame(new_candle_rows)
            if "ts" in new_candles_df.columns:
                new_candles_df["ts"] = pd.to_datetime(
                    new_candles_df["ts"], utc=True
                )
            store.append_to_daily_archive(new_candles_df, "candles_1m")

        # Archive derivatives for historical analysis
        if new_deriv_rows:
            new_deriv_df = pd.DataFrame(new_deriv_rows)
            if "ts" in new_deriv_df.columns:
                new_deriv_df["ts"] = pd.to_datetime(
                    new_deriv_df["ts"], utc=True
                )
            store.append_to_daily_archive(new_deriv_df, "derivatives_1m")

        logger.info("Signal engine complete")

        return {
            "statusCode": 200,
            "body": json.dumps({
                "message": "Signal computation successful",
                "timestamp": now.isoformat(),
                "symbols": SYMBOLS,
                "signals": signals_output,
            }, default=str),
        }

    except Exception as e:
        logger.error(f"Signal engine failed: {e}")
        return {
            "statusCode": 500,
            "body": json.dumps({
                "error": str(e),
                "timestamp": now.isoformat(),
            }),
        }


# Local testing
if __name__ == "__main__":
    result = lambda_handler({"source": "local-test"}, None)
    print(json.dumps(json.loads(result["body"]), indent=2))
