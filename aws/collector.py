"""
Crypto Data Collector for AWS Lambda

- Collects data for TOP 10 cryptos
- Appends to existing files (no duplicates)
- Runs every 15 minutes

Data collected:
- OHLCV (15m, 1h, 4h, 1d) - Historical + ongoing (CSV, append)
- Funding rates - Historical + ongoing (CSV, append)
- Open interest - TRACKED OVER TIME (Parquet, daily files, append)
- Order books - TRACKED OVER TIME (Parquet, daily files, append)
- Options Greeks - TRACKED OVER TIME (Parquet, daily files, append)
"""

import asyncio
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from dataclasses import dataclass, field
import pandas as pd
from pathlib import Path
from loguru import logger

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.deribit.api_client import DeribitClient

# Try to import pyarrow for parquet support
try:
    import pyarrow.parquet as pq
    import pyarrow as pa
    HAS_PARQUET = True
except ImportError:
    HAS_PARQUET = False
    logger.warning("pyarrow not installed - using CSV fallback for snapshots")


# Available cryptos on Deribit (only BTC and ETH have perpetuals)
AVAILABLE_CRYPTOS = ["BTC", "ETH"]


@dataclass 
class Config:
    """Collector configuration"""
    # Cryptos to collect (only BTC and ETH available on Deribit)
    cryptos: List[str] = field(default_factory=lambda: ["BTC", "ETH"])
    
    # OHLCV timeframes: 5min, 1hour, 4hour
    timeframes: List[str] = field(default_factory=lambda: ["5", "60", "240"])
    
    # Output directory
    output_dir: str = "data_exports"
    
    # How many years of historical data to get (first run only)
    history_years: int = 2


class CryptoCollector:
    """
    Simple, clean crypto data collector
    
    - Appends new data to existing files
    - No duplicates
    - Works with top 10 cryptos
    """
    
    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config()
        self.client = DeribitClient()
        self._connected = False
        
        # Create output directory
        os.makedirs(self.config.output_dir, exist_ok=True)
        
    async def connect(self):
        if not self._connected:
            await self.client.connect()
            self._connected = True
            
    async def close(self):
        if self._connected:
            await self.client.close()
            self._connected = False
            
    async def __aenter__(self):
        await self.connect()
        return self
        
    async def __aexit__(self, *args):
        await self.close()
    
    def _get_filepath(self, data_type: str, crypto: str = None, timeframe: str = None) -> str:
        """Get file path for data type (CSV files)"""
        if crypto and timeframe:
            return f"{self.config.output_dir}/ohlcv_{crypto}_{timeframe}.csv"
        elif crypto:
            return f"{self.config.output_dir}/{data_type}_{crypto}.csv"
        else:
            return f"{self.config.output_dir}/{data_type}.csv"
    
    def _get_parquet_filepath(self, data_type: str, crypto: str = None) -> str:
        """
        Get file path for Parquet snapshot data (daily partitions)
        
        Structure:
        - options_greeks/BTC/2026-01-27.parquet
        - orderbook/2026-01-27.parquet  
        - open_interest/2026-01-27.parquet
        """
        today = datetime.utcnow().strftime("%Y-%m-%d")
        
        if crypto:
            folder = f"{self.config.output_dir}/{data_type}/{crypto}"
        else:
            folder = f"{self.config.output_dir}/{data_type}"
        
        os.makedirs(folder, exist_ok=True)
        return f"{folder}/{today}.parquet"
    
    def _load_existing(self, filepath: str) -> pd.DataFrame:
        """Load existing data file if it exists"""
        if os.path.exists(filepath):
            try:
                return pd.read_csv(filepath)
            except:
                return pd.DataFrame()
        return pd.DataFrame()
    
    def _save_append(self, df: pd.DataFrame, filepath: str, key_columns: List[str]):
        """
        Save data, appending to existing file without duplicates
        
        Args:
            df: New data
            filepath: Where to save
            key_columns: Columns to check for duplicates (e.g., ['timestamp', 'instrument'])
        """
        if df.empty:
            return
            
        # Load existing data
        existing = self._load_existing(filepath)
        
        if existing.empty:
            # No existing data, just save new
            df.to_csv(filepath, index=False)
            logger.info(f"  Created {filepath} with {len(df)} rows")
        else:
            # Combine and remove duplicates
            combined = pd.concat([existing, df], ignore_index=True)
            
            # Remove duplicates based on key columns
            valid_keys = [k for k in key_columns if k in combined.columns]
            if valid_keys:
                combined = combined.drop_duplicates(subset=valid_keys, keep='last')
            
            # Sort by timestamp if available
            if 'timestamp' in combined.columns:
                combined = combined.sort_values('timestamp')
                
            combined.to_csv(filepath, index=False)
            new_rows = len(combined) - len(existing)
            logger.info(f"  Updated {filepath}: +{new_rows} new rows (total: {len(combined)})")
    
    def _save_parquet_append(self, df: pd.DataFrame, filepath: str):
        """
        Save snapshot data to Parquet, appending to daily file
        
        Each 15-min snapshot appends to today's parquet file.
        ~96 snapshots per day per file.
        """
        if df.empty:
            return
            
        # Ensure timestamp column exists
        if 'timestamp' not in df.columns:
            df['timestamp'] = datetime.utcnow().isoformat()
        
        if HAS_PARQUET:
            if os.path.exists(filepath):
                # Load existing and append
                try:
                    existing = pd.read_parquet(filepath)
                    combined = pd.concat([existing, df], ignore_index=True)
                    combined.to_parquet(filepath, index=False, compression='snappy')
                    new_rows = len(combined) - len(existing)
                    logger.info(f"  Appended to {filepath}: +{new_rows} rows (total: {len(combined)})")
                except Exception as e:
                    logger.warning(f"  Error reading existing parquet: {e}")
                    df.to_parquet(filepath, index=False, compression='snappy')
                    logger.info(f"  Created new {filepath}: {len(df)} rows")
            else:
                # Create new file
                df.to_parquet(filepath, index=False, compression='snappy')
                logger.info(f"  Created {filepath}: {len(df)} rows")
        else:
            # Fallback to CSV if pyarrow not available
            csv_path = filepath.replace('.parquet', '.csv')
            if os.path.exists(csv_path):
                existing = pd.read_csv(csv_path)
                combined = pd.concat([existing, df], ignore_index=True)
                combined.to_csv(csv_path, index=False)
                logger.info(f"  Appended to {csv_path}: +{len(df)} rows")
            else:
                df.to_csv(csv_path, index=False)
                logger.info(f"  Created {csv_path}: {len(df)} rows")
    
    # =========================================================
    # OHLCV COLLECTION
    # =========================================================
    
    async def collect_ohlcv(
        self,
        instrument: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """Collect OHLCV data for an instrument"""
        
        all_data = []
        
        # Batch size based on timeframe
        if timeframe == "1D":
            batch_days = 365
        elif timeframe in ["60", "240"]:
            batch_days = 60
        else:
            batch_days = 7
            
        current = start_date
        
        while current < end_date:
            batch_end = min(current + timedelta(days=batch_days), end_date)
            
            start_ts = int(current.timestamp() * 1000)
            end_ts = int(batch_end.timestamp() * 1000)
            
            try:
                # Map 240 to 180 (Deribit doesn't have 4h, use 3h)
                resolution = "180" if timeframe == "240" else timeframe
                
                data = await self.client.get_ohlcv(instrument, resolution, start_ts, end_ts)
                
                if data and "ticks" in data:
                    for i, tick in enumerate(data["ticks"]):
                        all_data.append({
                            "timestamp": datetime.fromtimestamp(tick / 1000).isoformat(),
                            "instrument": instrument,
                            "timeframe": timeframe,
                            "open": data["open"][i],
                            "high": data["high"][i],
                            "low": data["low"][i],
                            "close": data["close"][i],
                            "volume": data["volume"][i]
                        })
                        
            except Exception as e:
                logger.debug(f"  Error {instrument} {current.date()}: {e}")
                
            current = batch_end
            await asyncio.sleep(0.1)
            
        return pd.DataFrame(all_data) if all_data else pd.DataFrame()
    
    async def collect_all_ohlcv(self, historical: bool = False):
        """
        Collect OHLCV for all cryptos and timeframes
        
        Args:
            historical: If True, get all history. If False, just recent data.
        """
        logger.info("📊 Collecting OHLCV data...")
        
        end_date = datetime.utcnow()
        
        if historical:
            start_date = end_date - timedelta(days=self.config.history_years * 365)
            logger.info(f"   Getting {self.config.history_years} years of history")
        else:
            start_date = end_date - timedelta(days=7)  # Last 7 days for updates
            
        for crypto in self.config.cryptos:
            instrument = f"{crypto}-PERPETUAL"
            
            # Check if instrument exists
            try:
                await self.client.ticker(instrument)
            except:
                logger.warning(f"   {instrument} not available, skipping")
                continue
                
            for tf in self.config.timeframes:
                logger.info(f"   {instrument} {tf}...")
                
                df = await self.collect_ohlcv(instrument, tf, start_date, end_date)
                
                if not df.empty:
                    filepath = self._get_filepath("ohlcv", crypto, tf)
                    self._save_append(df, filepath, ["timestamp", "instrument"])
    
    # =========================================================
    # FUNDING RATES
    # =========================================================
    
    async def collect_funding(self, instrument: str, start_date: datetime, end_date: datetime) -> pd.DataFrame:
        """Collect funding rate history"""
        
        all_data = []
        batch_days = 90
        current = start_date
        
        while current < end_date:
            batch_end = min(current + timedelta(days=batch_days), end_date)
            
            start_ts = int(current.timestamp() * 1000)
            end_ts = int(batch_end.timestamp() * 1000)
            
            try:
                data = await self.client.get_funding_rate_history(instrument, start_ts, end_ts)
                
                if data:
                    for record in data:
                        all_data.append({
                            "timestamp": datetime.fromtimestamp(record["timestamp"] / 1000).isoformat(),
                            "instrument": instrument,
                            "funding_8h": record.get("interest_8h"),
                            "index_price": record.get("index_price")
                        })
                        
            except Exception as e:
                logger.debug(f"  Funding error: {e}")
                
            current = batch_end
            await asyncio.sleep(0.1)
            
        return pd.DataFrame(all_data) if all_data else pd.DataFrame()
    
    async def collect_all_funding(self, historical: bool = False):
        """Collect funding rates for all perpetuals"""
        logger.info("💰 Collecting funding rates...")
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=self.config.history_years * 365 if historical else 7)
        
        for crypto in self.config.cryptos:
            instrument = f"{crypto}-PERPETUAL"
            
            try:
                await self.client.ticker(instrument)
            except:
                continue
                
            logger.info(f"   {instrument}...")
            
            df = await self.collect_funding(instrument, start_date, end_date)
            
            if not df.empty:
                filepath = self._get_filepath("funding", crypto)
                self._save_append(df, filepath, ["timestamp", "instrument"])
    
    # =========================================================
    # CURRENT SNAPSHOTS (Options, Order Books, OI)
    # =========================================================
    
    async def collect_options_greeks(self, currency: str) -> pd.DataFrame:
        """
        Collect options with Greeks (only BTC, ETH have options)
        
        Gets Greeks for ALL options by fetching ticker data for each.
        Uses ONE timestamp for the entire batch (15-min snapshot).
        """
        
        if currency not in ["BTC", "ETH"]:
            return pd.DataFrame()
        
        # ONE timestamp for the entire snapshot batch
        snapshot_time = datetime.utcnow().isoformat()
            
        try:
            summaries = await self.client.get_book_summary_by_currency(currency, kind="option")
            index_data = await self.client.get_index_price(f"{currency.lower()}_usd")
            underlying = index_data.get("index_price", 0)
        except Exception as e:
            logger.warning(f"Failed to get {currency} options summary: {e}")
            return pd.DataFrame()
        
        logger.info(f"     Found {len(summaries)} {currency} options, fetching Greeks for ALL...")
            
        options_data = []
        greeks_fetched = 0
        greeks_failed = 0
        
        for i, summary in enumerate(summaries):
            instr = summary.get("instrument_name", "")
            parts = instr.split("-")
            
            if len(parts) < 4:
                continue
                
            # Get Greeks for EVERY option (not just first 100)
            greeks = {}
            try:
                ticker = await self.client.ticker(instr)
                greeks = ticker.get("greeks", {}) or {}
                if greeks:
                    greeks_fetched += 1
                else:
                    greeks_failed += 1
                    
                # Rate limiting - small pause every 50 requests
                if i % 50 == 0 and i > 0:
                    await asyncio.sleep(0.2)
            except Exception as e:
                greeks_failed += 1
                if i < 5:  # Only log first few errors
                    logger.debug(f"     Greeks error for {instr}: {e}")
                
            options_data.append({
                "timestamp": snapshot_time,  # Same timestamp for all options in this batch
                "currency": currency,
                "instrument": instr,
                "expiry": parts[1],
                "strike": float(parts[2]),
                "type": "call" if parts[3] == "C" else "put",
                "underlying": underlying,
                "mark_price": summary.get("mark_price"),
                "mark_iv": summary.get("mark_iv"),
                "bid": summary.get("bid_price"),
                "ask": summary.get("ask_price"),
                "open_interest": summary.get("open_interest"),
                "volume_24h": summary.get("volume"),
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega"),
            })
        
        logger.info(f"     Greeks: {greeks_fetched} fetched, {greeks_failed} failed/empty")
            
        return pd.DataFrame(options_data)
    
    async def collect_orderbooks(self) -> pd.DataFrame:
        """Collect order book snapshots - ONE timestamp for entire batch"""
        
        # ONE timestamp for the entire snapshot batch
        snapshot_time = datetime.utcnow().isoformat()
        
        snapshots = []
        
        for crypto in self.config.cryptos:
            instrument = f"{crypto}-PERPETUAL"
            
            try:
                book = await self.client.get_order_book(instrument, depth=20)
                
                bids = book.get("bids", [])
                asks = book.get("asks", [])
                
                best_bid = bids[0][0] if bids else 0
                best_ask = asks[0][0] if asks else 0
                
                snapshots.append({
                    "timestamp": snapshot_time,  # Same timestamp for all in this batch
                    "instrument": instrument,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "mid_price": (best_bid + best_ask) / 2 if best_bid and best_ask else 0,
                    "spread": best_ask - best_bid if best_bid and best_ask else 0,
                    "bid_depth": sum(b[1] for b in bids),
                    "ask_depth": sum(a[1] for a in asks),
                })
                
            except Exception as e:
                logger.debug(f"  Orderbook error {instrument}: {e}")
                
        return pd.DataFrame(snapshots)
    
    async def collect_open_interest(self) -> pd.DataFrame:
        """Collect open interest for all cryptos - ONE timestamp for entire batch"""
        
        # ONE timestamp for the entire snapshot batch
        snapshot_time = datetime.utcnow().isoformat()
        
        oi_data = []
        
        for crypto in self.config.cryptos:
            try:
                futures = await self.client.get_book_summary_by_currency(crypto, kind="future")
                
                perp_oi = sum(
                    s.get("open_interest", 0) or 0 
                    for s in futures 
                    if "PERPETUAL" in s.get("instrument_name", "")
                )
                
                total_futures_oi = sum(s.get("open_interest", 0) or 0 for s in futures)
                
                # Options OI (only BTC, ETH)
                options_oi = 0
                if crypto in ["BTC", "ETH"]:
                    try:
                        options = await self.client.get_book_summary_by_currency(crypto, kind="option")
                        options_oi = sum(s.get("open_interest", 0) or 0 for s in options)
                    except:
                        pass
                
                oi_data.append({
                    "timestamp": snapshot_time,  # Same timestamp for all in this batch
                    "currency": crypto,
                    "perpetual_oi": perp_oi,
                    "futures_oi": total_futures_oi,
                    "options_oi": options_oi,
                })
                
            except Exception as e:
                logger.debug(f"  OI error {crypto}: {e}")
                
        return pd.DataFrame(oi_data)
    
    # =========================================================
    # MAIN COLLECTION METHODS
    # =========================================================
    
    async def collect_historical(self):
        """
        Collect ALL historical data (run once on first setup)
        
        Gets everything available from Deribit history.
        """
        logger.info("=" * 60)
        logger.info("📜 COLLECTING ALL HISTORICAL DATA")
        logger.info(f"   Cryptos: {self.config.cryptos}")
        logger.info(f"   Period: {self.config.history_years} years")
        logger.info("=" * 60)
        
        # OHLCV history
        await self.collect_all_ohlcv(historical=True)
        
        # Funding history
        await self.collect_all_funding(historical=True)
        
        logger.info("=" * 60)
        logger.info("✅ HISTORICAL COLLECTION COMPLETE")
        logger.info("=" * 60)
    
    async def collect_update(self):
        """
        Collect current data (runs every 15 minutes)
        
        - Recent OHLCV (appends to existing)
        - Current options Greeks
        - Current order books
        - Current open interest
        """
        logger.info("=" * 60)
        logger.info("🔄 15-MINUTE UPDATE")
        logger.info(f"   Time: {datetime.utcnow().isoformat()}")
        logger.info("=" * 60)
        
        # Recent OHLCV (last 7 days, will append new candles)
        await self.collect_all_ohlcv(historical=False)
        
        # Recent funding
        await self.collect_all_funding(historical=False)
        
        # Current snapshots - NOW TRACKED OVER TIME (Parquet, daily files)
        logger.info("📊 Collecting current snapshots (tracking over time)...")
        
        # Options Greeks (BTC, ETH only) - APPEND to daily Parquet
        for crypto in ["BTC", "ETH"]:
            if crypto in self.config.cryptos:
                logger.info(f"   {crypto} options greeks...")
                df = await self.collect_options_greeks(crypto)
                if not df.empty:
                    filepath = self._get_parquet_filepath("options_greeks", crypto)
                    self._save_parquet_append(df, filepath)
        
        # Order books - APPEND to daily Parquet
        logger.info("   Order books...")
        df = await self.collect_orderbooks()
        if not df.empty:
            filepath = self._get_parquet_filepath("orderbook")
            self._save_parquet_append(df, filepath)
        
        # Open interest - APPEND to daily Parquet
        logger.info("   Open interest...")
        df = await self.collect_open_interest()
        if not df.empty:
            filepath = self._get_parquet_filepath("open_interest")
            self._save_parquet_append(df, filepath)
        
        logger.info("=" * 60)
        logger.info("✅ UPDATE COMPLETE")
        logger.info("=" * 60)


# =========================================================
# MAIN
# =========================================================

async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Crypto Data Collector")
    parser.add_argument("--historical", action="store_true", help="Collect all historical data")
    parser.add_argument("--update", action="store_true", help="Run 15-minute update")
    parser.add_argument("--cryptos", nargs="+", default=["BTC", "ETH", "SOL"], help="Cryptos to collect")
    parser.add_argument("--years", type=int, default=2, help="Years of history")
    
    args = parser.parse_args()
    
    config = Config(
        cryptos=args.cryptos,
        history_years=args.years
    )
    
    async with CryptoCollector(config) as collector:
        if args.historical:
            await collector.collect_historical()
        elif args.update:
            await collector.collect_update()
        else:
            # Default: run both
            await collector.collect_historical()
            await collector.collect_update()


if __name__ == "__main__":
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | {message}")
    
    asyncio.run(main())

