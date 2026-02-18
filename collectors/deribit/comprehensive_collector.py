"""
Comprehensive Deribit Data Collector

Collects ALL data types:
- OHLCV (all timeframes)
- Order Book Snapshots
- Options Surface (IV, Greeks, Skew, Term Structure)
- Open Interest
- Funding Rates
- Basis (Futures vs Spot)
- Volatility Index (DVOL)
- Trades
"""

import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from collections import defaultdict
from loguru import logger
import json
import os
import sys

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from collectors.deribit.api_client import DeribitClient, DeribitConfig


@dataclass
class CollectionConfig:
    """Configuration for data collection"""
    currencies: List[str] = field(default_factory=lambda: ["BTC", "ETH"])
    years_history: int = 2
    
    # Timeframes for OHLCV
    ohlcv_timeframes: List[str] = field(default_factory=lambda: ["1", "5", "15", "60", "1D"])
    
    # Snapshot intervals (in seconds)
    orderbook_interval: int = 60  # Every minute
    options_interval: int = 300   # Every 5 minutes
    
    # Batch sizes
    ohlcv_batch_days: int = 30
    trades_batch_hours: int = 24
    
    # Output directory
    output_dir: str = "data_exports"


class ComprehensiveCollector:
    """
    Collects all Deribit data types for analysis
    """
    
    RESOLUTION_MAP = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "1h": "60",
        "4h": "240",
        "1d": "1D",
        "1": "1",
        "5": "5",
        "15": "15",
        "60": "60",
        "1D": "1D"
    }
    
    def __init__(self, config: Optional[CollectionConfig] = None):
        self.config = config or CollectionConfig()
        self.client = DeribitClient()
        
        # Create output directory
        os.makedirs(self.config.output_dir, exist_ok=True)
        
        # Storage for collected data
        self.instruments: Dict[str, List[Dict]] = {}
        self.options_snapshots: List[Dict] = []
        self.orderbook_snapshots: List[Dict] = []
        
    async def connect(self):
        """Connect to API"""
        await self.client.connect()
        
    async def close(self):
        """Close API connection"""
        await self.client.close()
        
    async def __aenter__(self):
        await self.connect()
        return self
        
    async def __aexit__(self, *args):
        await self.close()
        
    # =========================================================
    # INSTRUMENT COLLECTION
    # =========================================================
    
    async def collect_instruments(self) -> Dict[str, pd.DataFrame]:
        """Collect all instruments for configured currencies"""
        logger.info("Collecting instruments...")
        
        all_instruments = {}
        
        for currency in self.config.currencies:
            logger.info(f"  Fetching {currency} instruments...")
            
            # Futures
            futures = await self.client.get_instruments(currency, kind="future")
            logger.info(f"    Futures: {len(futures)}")
            
            # Options  
            options = await self.client.get_instruments(currency, kind="option")
            logger.info(f"    Options: {len(options)}")
            
            # Combine
            all_instr = futures + options
            all_instruments[currency] = all_instr
            
            # Save to CSV
            if all_instr:
                df = pd.DataFrame(all_instr)
                filepath = os.path.join(self.config.output_dir, f"instruments_{currency}.csv")
                df.to_csv(filepath, index=False)
                logger.info(f"    Saved to {filepath}")
                
        self.instruments = all_instruments
        return all_instruments
    
    # =========================================================
    # OHLCV COLLECTION
    # =========================================================
    
    async def collect_ohlcv(
        self,
        instrument_name: str,
        timeframe: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Collect OHLCV data for a single instrument
        
        Args:
            instrument_name: e.g., 'BTC-PERPETUAL'
            timeframe: '1m', '5m', '15m', '1h', '1d'
            start_date: Start datetime
            end_date: End datetime
        """
        resolution = self.RESOLUTION_MAP.get(timeframe, timeframe)
        all_data = []
        
        # Calculate batch size based on timeframe
        if resolution == "1D":
            batch_days = 365
        elif resolution in ["60", "240"]:
            batch_days = 60
        else:
            batch_days = 7
            
        current_start = start_date
        
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=batch_days), end_date)
            
            start_ts = int(current_start.timestamp() * 1000)
            end_ts = int(current_end.timestamp() * 1000)
            
            try:
                data = await self.client.get_ohlcv(
                    instrument_name, resolution, start_ts, end_ts
                )
                
                if data and "ticks" in data:
                    batch_records = []
                    for i, tick in enumerate(data["ticks"]):
                        batch_records.append({
                            "timestamp": datetime.fromtimestamp(tick / 1000),
                            "open": data["open"][i],
                            "high": data["high"][i],
                            "low": data["low"][i],
                            "close": data["close"][i],
                            "volume": data["volume"][i]
                        })
                    all_data.extend(batch_records)
                    logger.debug(f"    {current_start.date()} - {current_end.date()}: {len(batch_records)} candles")
                    
            except Exception as e:
                logger.warning(f"    Error fetching {current_start.date()}: {e}")
                
            current_start = current_end
            await asyncio.sleep(0.1)  # Rate limiting
            
        if all_data:
            df = pd.DataFrame(all_data)
            df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
            return df
        return pd.DataFrame()
    
    async def collect_all_ohlcv(self) -> Dict[str, Dict[str, pd.DataFrame]]:
        """Collect OHLCV for all perpetuals across all timeframes"""
        logger.info("Collecting OHLCV data...")
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=self.config.years_history * 365)
        
        results = {}
        
        for currency in self.config.currencies:
            instrument = f"{currency}-PERPETUAL"
            results[instrument] = {}
            
            logger.info(f"\n  {instrument}:")
            
            for tf in self.config.ohlcv_timeframes:
                logger.info(f"    Timeframe: {tf}")
                
                df = await self.collect_ohlcv(instrument, tf, start_date, end_date)
                
                if not df.empty:
                    results[instrument][tf] = df
                    
                    # Save to CSV
                    filepath = os.path.join(
                        self.config.output_dir, 
                        f"ohlcv_{instrument}_{tf}.csv"
                    )
                    df.to_csv(filepath, index=False)
                    logger.info(f"      Saved {len(df)} rows to {filepath}")
                    
        return results
    
    # =========================================================
    # OPTIONS DATA COLLECTION (IV Surface, Greeks)
    # =========================================================
    
    async def collect_options_snapshot(self, currency: str) -> Dict:
        """
        Collect complete options market snapshot
        
        Returns:
            Dict with options data including IV surface
        """
        logger.info(f"Collecting {currency} options snapshot...")
        
        # Get all options
        instruments = await self.client.get_instruments(currency, kind="option")
        
        # Get book summaries (includes IV, Greeks, OI)
        summaries = await self.client.get_book_summary_by_currency(currency, kind="option")
        
        # Get underlying price
        index_name = f"{currency.lower()}_usd"
        try:
            index_data = await self.client.get_index_price(index_name)
            underlying_price = index_data.get("index_price", 0)
        except:
            underlying_price = 0
            
        # Build options chain - fetch ticker for each to get Greeks
        options_data = []
        batch_size = 20  # Process in batches to avoid rate limits
        
        for i, summary in enumerate(summaries):
            instr = summary.get("instrument_name", "")
            
            # Parse instrument name (e.g., BTC-28MAR25-100000-C)
            parts = instr.split("-")
            if len(parts) >= 4:
                expiry = parts[1]
                strike = float(parts[2])
                option_type = "call" if parts[3] == "C" else "put"
            else:
                continue
            
            # Get Greeks from ticker endpoint
            greeks = {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}
            try:
                ticker = await self.client.ticker(instr)
                greeks = ticker.get("greeks", {}) or {}
            except Exception:
                pass  # Use None for Greeks if ticker fails
            
            # Rate limit: small delay every batch
            if i > 0 and i % batch_size == 0:
                await asyncio.sleep(0.1)
                
            options_data.append({
                "instrument_name": instr,
                "expiry": expiry,
                "strike": strike,
                "option_type": option_type,
                "mark_price": summary.get("mark_price"),
                "mark_iv": summary.get("mark_iv"),
                "bid_price": summary.get("bid_price"),
                "ask_price": summary.get("ask_price"),
                "underlying_price": summary.get("underlying_price", underlying_price),
                "open_interest": summary.get("open_interest"),
                "volume_24h": summary.get("volume"),
                "delta": greeks.get("delta"),
                "gamma": greeks.get("gamma"),
                "theta": greeks.get("theta"),
                "vega": greeks.get("vega"),
                "rho": greeks.get("rho"),
            })
            
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "currency": currency,
            "underlying_price": underlying_price,
            "options_count": len(options_data),
            "options": options_data
        }
    
    async def collect_options_surface(self, currency: str) -> pd.DataFrame:
        """
        Collect and structure options IV surface
        """
        snapshot = await self.collect_options_snapshot(currency)
        
        if not snapshot["options"]:
            return pd.DataFrame()
            
        df = pd.DataFrame(snapshot["options"])
        df["timestamp"] = snapshot["timestamp"]
        df["underlying_price"] = snapshot["underlying_price"]
        
        # Calculate moneyness
        if snapshot["underlying_price"] > 0:
            df["moneyness"] = df["strike"] / snapshot["underlying_price"]
            
        # Save
        filepath = os.path.join(self.config.output_dir, f"options_surface_{currency}.csv")
        df.to_csv(filepath, index=False)
        logger.info(f"  Saved {len(df)} options to {filepath}")
        
        return df
    
    async def compute_iv_metrics(self, currency: str) -> Dict:
        """
        Compute IV surface metrics: ATM IV, skew, term structure
        """
        snapshot = await self.collect_options_snapshot(currency)
        
        if not snapshot["options"]:
            return {}
            
        df = pd.DataFrame(snapshot["options"])
        underlying = snapshot["underlying_price"]
        
        metrics = {
            "timestamp": snapshot["timestamp"],
            "currency": currency,
            "underlying_price": underlying,
            "expirations": {},
            "term_structure": [],
            "skew_by_expiry": {}
        }
        
        # Group by expiry
        for expiry, group in df.groupby("expiry"):
            calls = group[group["option_type"] == "call"]
            puts = group[group["option_type"] == "put"]
            
            # Find ATM option (closest to underlying)
            if underlying > 0 and len(calls) > 0:
                calls["dist_from_atm"] = abs(calls["strike"] - underlying)
                atm_call = calls.loc[calls["dist_from_atm"].idxmin()]
                atm_iv = atm_call["mark_iv"]
            else:
                atm_iv = None
                
            # Calculate 25-delta skew (simplified)
            # In practice, you'd interpolate to exact delta
            skew_25d = None
            if len(puts) > 0 and len(calls) > 0:
                # Approximate: compare OTM put vs OTM call IV
                otm_puts = puts[puts["strike"] < underlying * 0.95]
                otm_calls = calls[calls["strike"] > underlying * 1.05]
                
                if len(otm_puts) > 0 and len(otm_calls) > 0:
                    avg_put_iv = otm_puts["mark_iv"].mean()
                    avg_call_iv = otm_calls["mark_iv"].mean()
                    if avg_put_iv and avg_call_iv:
                        skew_25d = avg_put_iv - avg_call_iv
                        
            metrics["expirations"][expiry] = {
                "atm_iv": atm_iv,
                "skew_25d": skew_25d,
                "num_calls": len(calls),
                "num_puts": len(puts),
                "total_oi_calls": calls["open_interest"].sum() if "open_interest" in calls else 0,
                "total_oi_puts": puts["open_interest"].sum() if "open_interest" in puts else 0
            }
            
            if atm_iv:
                # Parse expiry to get DTE
                try:
                    exp_date = datetime.strptime(expiry, "%d%b%y")
                    dte = (exp_date - datetime.utcnow()).days
                    metrics["term_structure"].append({
                        "expiry": expiry,
                        "dte": dte,
                        "atm_iv": atm_iv
                    })
                except:
                    pass
                    
        # Sort term structure by DTE
        metrics["term_structure"] = sorted(metrics["term_structure"], key=lambda x: x.get("dte", 0))
        
        return metrics
    
    # =========================================================
    # ORDER BOOK COLLECTION
    # =========================================================
    
    async def collect_orderbook_snapshot(self, instrument_name: str) -> Dict:
        """Collect order book snapshot with depth metrics"""
        
        book = await self.client.get_order_book(instrument_name, depth=20)
        
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        
        # Calculate depth metrics
        bid_depth_5 = sum(b[1] for b in bids[:5]) if bids else 0
        ask_depth_5 = sum(a[1] for a in asks[:5]) if asks else 0
        bid_depth_10 = sum(b[1] for b in bids[:10]) if bids else 0
        ask_depth_10 = sum(a[1] for a in asks[:10]) if asks else 0
        bid_depth_20 = sum(b[1] for b in bids[:20]) if bids else 0
        ask_depth_20 = sum(a[1] for a in asks[:20]) if asks else 0
        
        best_bid = bids[0][0] if bids else 0
        best_ask = asks[0][0] if asks else 0
        mid_price = (best_bid + best_ask) / 2 if best_bid and best_ask else 0
        spread = best_ask - best_bid if best_bid and best_ask else 0
        spread_pct = (spread / mid_price * 100) if mid_price > 0 else 0
        
        total_depth = bid_depth_20 + ask_depth_20
        imbalance = (bid_depth_20 - ask_depth_20) / total_depth if total_depth > 0 else 0
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "instrument_name": instrument_name,
            "best_bid_price": best_bid,
            "best_bid_amount": bids[0][1] if bids else 0,
            "best_ask_price": best_ask,
            "best_ask_amount": asks[0][1] if asks else 0,
            "mid_price": mid_price,
            "spread": spread,
            "spread_percent": spread_pct,
            "bid_depth_5": bid_depth_5,
            "ask_depth_5": ask_depth_5,
            "bid_depth_10": bid_depth_10,
            "ask_depth_10": ask_depth_10,
            "bid_depth_20": bid_depth_20,
            "ask_depth_20": ask_depth_20,
            "imbalance_ratio": imbalance,
            "bids": bids,
            "asks": asks
        }
    
    async def collect_all_orderbooks(self) -> pd.DataFrame:
        """Collect order book snapshots for all perpetuals"""
        logger.info("Collecting order book snapshots...")
        
        all_snapshots = []
        
        for currency in self.config.currencies:
            instrument = f"{currency}-PERPETUAL"
            
            try:
                snapshot = await self.collect_orderbook_snapshot(instrument)
                all_snapshots.append(snapshot)
                logger.info(f"  {instrument}: spread={snapshot['spread_percent']:.4f}%")
            except Exception as e:
                logger.error(f"  {instrument}: Error - {e}")
                
        if all_snapshots:
            df = pd.DataFrame(all_snapshots)
            filepath = os.path.join(self.config.output_dir, "orderbook_snapshots.csv")
            df.to_csv(filepath, index=False)
            
        return pd.DataFrame(all_snapshots)
    
    # =========================================================
    # FUNDING RATES COLLECTION
    # =========================================================
    
    async def collect_funding_history(
        self,
        instrument_name: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """Collect historical funding rates"""
        
        all_data = []
        batch_days = 90
        
        current_start = start_date
        
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=batch_days), end_date)
            
            start_ts = int(current_start.timestamp() * 1000)
            end_ts = int(current_end.timestamp() * 1000)
            
            try:
                data = await self.client.get_funding_rate_history(
                    instrument_name, start_ts, end_ts
                )
                
                if data:
                    for record in data:
                        all_data.append({
                            "timestamp": datetime.fromtimestamp(record["timestamp"] / 1000),
                            "instrument_name": instrument_name,
                            "interest_8h": record.get("interest_8h"),
                            "interest_1h": record.get("interest_1h"),
                            "prev_index_price": record.get("prev_index_price"),
                            "index_price": record.get("index_price")
                        })
                        
            except Exception as e:
                logger.warning(f"  Error fetching funding {current_start.date()}: {e}")
                
            current_start = current_end
            await asyncio.sleep(0.1)
            
        if all_data:
            df = pd.DataFrame(all_data)
            df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
            return df
        return pd.DataFrame()
    
    async def collect_all_funding(self) -> Dict[str, pd.DataFrame]:
        """Collect funding rates for all perpetuals"""
        logger.info("Collecting funding rate history...")
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=self.config.years_history * 365)
        
        results = {}
        
        for currency in self.config.currencies:
            instrument = f"{currency}-PERPETUAL"
            logger.info(f"  {instrument}...")
            
            df = await self.collect_funding_history(instrument, start_date, end_date)
            
            if not df.empty:
                results[instrument] = df
                filepath = os.path.join(self.config.output_dir, f"funding_{instrument}.csv")
                df.to_csv(filepath, index=False)
                logger.info(f"    Saved {len(df)} records")
                
        return results
    
    # =========================================================
    # OPEN INTEREST COLLECTION
    # =========================================================
    
    async def collect_open_interest(self, currency: str) -> Dict:
        """Collect current open interest by instrument type"""
        
        # Get all instruments with summaries
        futures_summary = await self.client.get_book_summary_by_currency(currency, kind="future")
        options_summary = await self.client.get_book_summary_by_currency(currency, kind="option")
        
        # Aggregate
        futures_oi = sum(s.get("open_interest", 0) or 0 for s in futures_summary)
        options_oi = sum(s.get("open_interest", 0) or 0 for s in options_summary)
        
        calls_oi = sum(
            s.get("open_interest", 0) or 0 
            for s in options_summary 
            if s.get("instrument_name", "").endswith("-C")
        )
        puts_oi = sum(
            s.get("open_interest", 0) or 0 
            for s in options_summary 
            if s.get("instrument_name", "").endswith("-P")
        )
        
        put_call_ratio = puts_oi / calls_oi if calls_oi > 0 else 0
        
        # Get perpetual specific
        perp_name = f"{currency}-PERPETUAL"
        perp_summary = [s for s in futures_summary if s.get("instrument_name") == perp_name]
        perp_oi = perp_summary[0].get("open_interest", 0) if perp_summary else 0
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "currency": currency,
            "perpetual_oi": perp_oi,
            "total_futures_oi": futures_oi,
            "total_options_oi": options_oi,
            "calls_oi": calls_oi,
            "puts_oi": puts_oi,
            "put_call_ratio": put_call_ratio
        }
    
    async def collect_all_open_interest(self) -> pd.DataFrame:
        """Collect OI for all currencies"""
        logger.info("Collecting open interest...")
        
        all_oi = []
        
        for currency in self.config.currencies:
            try:
                oi_data = await self.collect_open_interest(currency)
                all_oi.append(oi_data)
                logger.info(f"  {currency}: Perp OI={oi_data['perpetual_oi']:,.0f}, "
                           f"Options OI={oi_data['total_options_oi']:,.0f}, "
                           f"P/C Ratio={oi_data['put_call_ratio']:.2f}")
            except Exception as e:
                logger.error(f"  {currency}: Error - {e}")
                
        if all_oi:
            df = pd.DataFrame(all_oi)
            filepath = os.path.join(self.config.output_dir, "open_interest.csv")
            df.to_csv(filepath, index=False)
            
        return pd.DataFrame(all_oi)
    
    # =========================================================
    # BASIS COLLECTION
    # =========================================================
    
    async def collect_basis(self, currency: str) -> List[Dict]:
        """Calculate basis for all futures vs spot"""
        
        # Get spot price
        index_name = f"{currency.lower()}_usd"
        try:
            index_data = await self.client.get_index_price(index_name)
            spot_price = index_data.get("index_price", 0)
        except:
            spot_price = 0
            
        if spot_price == 0:
            return []
            
        # Get all futures
        futures = await self.client.get_instruments(currency, kind="future")
        summaries = await self.client.get_book_summary_by_currency(currency, kind="future")
        summary_map = {s["instrument_name"]: s for s in summaries}
        
        basis_data = []
        
        for future in futures:
            name = future["instrument_name"]
            
            # Skip perpetual for annualized basis
            if "PERPETUAL" in name:
                continue
                
            summary = summary_map.get(name, {})
            mark_price = summary.get("mark_price", 0)
            
            if mark_price == 0:
                continue
                
            # Get expiration
            exp_timestamp = future.get("expiration_timestamp", 0)
            if exp_timestamp:
                exp_date = datetime.fromtimestamp(exp_timestamp / 1000)
                dte = (exp_date - datetime.utcnow()).days
            else:
                dte = 0
                
            # Calculate basis
            basis = mark_price - spot_price
            basis_pct = (basis / spot_price) * 100
            
            # Annualize
            if dte > 0:
                basis_annualized = (basis_pct / dte) * 365
            else:
                basis_annualized = 0
                
            basis_data.append({
                "timestamp": datetime.utcnow().isoformat(),
                "currency": currency,
                "instrument_name": name,
                "spot_price": spot_price,
                "future_price": mark_price,
                "basis": basis,
                "basis_percent": basis_pct,
                "basis_annualized": basis_annualized,
                "days_to_expiry": dte
            })
            
        return basis_data
    
    async def collect_all_basis(self) -> pd.DataFrame:
        """Collect basis for all currencies"""
        logger.info("Collecting basis data...")
        
        all_basis = []
        
        for currency in self.config.currencies:
            try:
                basis_data = await self.collect_basis(currency)
                all_basis.extend(basis_data)
                
                for b in basis_data:
                    logger.info(f"  {b['instrument_name']}: "
                               f"Basis={b['basis_percent']:.2f}%, "
                               f"Annualized={b['basis_annualized']:.2f}%")
            except Exception as e:
                logger.error(f"  {currency}: Error - {e}")
                
        if all_basis:
            df = pd.DataFrame(all_basis)
            filepath = os.path.join(self.config.output_dir, "basis.csv")
            df.to_csv(filepath, index=False)
            
        return pd.DataFrame(all_basis)
    
    # =========================================================
    # VOLATILITY INDEX (DVOL) COLLECTION
    # =========================================================
    
    async def collect_dvol_history(
        self,
        currency: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """Collect historical DVOL data"""
        
        all_data = []
        batch_days = 30
        
        current_start = start_date
        
        while current_start < end_date:
            current_end = min(current_start + timedelta(days=batch_days), end_date)
            
            start_ts = int(current_start.timestamp() * 1000)
            end_ts = int(current_end.timestamp() * 1000)
            
            try:
                data = await self.client.get_volatility_index_data(
                    currency, start_ts, end_ts, resolution="3600"  # Hourly
                )
                
                if data:
                    for record in data:
                        all_data.append({
                            "timestamp": datetime.fromtimestamp(record[0] / 1000),
                            "currency": currency,
                            "dvol_open": record[1],
                            "dvol_high": record[2],
                            "dvol_low": record[3],
                            "dvol_close": record[4]
                        })
                        
            except Exception as e:
                logger.warning(f"  Error fetching DVOL {current_start.date()}: {e}")
                
            current_start = current_end
            await asyncio.sleep(0.1)
            
        if all_data:
            df = pd.DataFrame(all_data)
            df = df.drop_duplicates(subset=["timestamp"]).sort_values("timestamp")
            return df
        return pd.DataFrame()
    
    async def collect_all_dvol(self) -> Dict[str, pd.DataFrame]:
        """Collect DVOL for BTC and ETH"""
        logger.info("Collecting DVOL history...")
        
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=self.config.years_history * 365)
        
        results = {}
        
        for currency in ["BTC", "ETH"]:  # DVOL only available for BTC and ETH
            logger.info(f"  {currency} DVOL...")
            
            df = await self.collect_dvol_history(currency, start_date, end_date)
            
            if not df.empty:
                results[currency] = df
                filepath = os.path.join(self.config.output_dir, f"dvol_{currency}.csv")
                df.to_csv(filepath, index=False)
                logger.info(f"    Saved {len(df)} records")
                
        return results
    
    # =========================================================
    # MASTER COLLECTION METHOD
    # =========================================================
    
    async def collect_all(self, include_historical: bool = True) -> Dict:
        """
        Collect ALL data types
        
        Args:
            include_historical: If True, collect historical data (slow)
                               If False, only collect current snapshots (fast)
        """
        logger.info("=" * 60)
        logger.info("COMPREHENSIVE DERIBIT DATA COLLECTION")
        logger.info("=" * 60)
        logger.info(f"Currencies: {self.config.currencies}")
        logger.info(f"Years of history: {self.config.years_history}")
        logger.info(f"Output directory: {self.config.output_dir}")
        logger.info("=" * 60)
        
        results = {}
        
        # 1. Instruments (always)
        results["instruments"] = await self.collect_instruments()
        
        if include_historical:
            # 2. OHLCV history
            results["ohlcv"] = await self.collect_all_ohlcv()
            
            # 3. Funding rate history
            results["funding"] = await self.collect_all_funding()
            
            # 4. DVOL history
            results["dvol"] = await self.collect_all_dvol()
            
        # 5. Current snapshots (always)
        # Options surface
        for currency in self.config.currencies:
            results[f"options_surface_{currency}"] = await self.collect_options_surface(currency)
            results[f"iv_metrics_{currency}"] = await self.compute_iv_metrics(currency)
            
        # Order books
        results["orderbooks"] = await self.collect_all_orderbooks()
        
        # Open interest
        results["open_interest"] = await self.collect_all_open_interest()
        
        # Basis
        results["basis"] = await self.collect_all_basis()
        
        logger.info("=" * 60)
        logger.info("COLLECTION COMPLETE")
        logger.info(f"Data saved to: {os.path.abspath(self.config.output_dir)}")
        logger.info("=" * 60)
        
        return results


# =========================================================
# MAIN EXECUTION
# =========================================================

async def main():
    """Main collection script"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Collect Deribit data")
    parser.add_argument("--currencies", nargs="+", default=["BTC", "ETH"],
                        help="Currencies to collect")
    parser.add_argument("--years", type=int, default=2,
                        help="Years of historical data")
    parser.add_argument("--output", default="data_exports",
                        help="Output directory")
    parser.add_argument("--snapshots-only", action="store_true",
                        help="Only collect current snapshots (fast)")
    
    args = parser.parse_args()
    
    config = CollectionConfig(
        currencies=args.currencies,
        years_history=args.years,
        output_dir=args.output
    )
    
    async with ComprehensiveCollector(config) as collector:
        await collector.collect_all(include_historical=not args.snapshots_only)


if __name__ == "__main__":
    asyncio.run(main())

