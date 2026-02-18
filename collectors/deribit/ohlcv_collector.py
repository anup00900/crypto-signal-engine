"""
Deribit OHLCV data collector.
"""

import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from loguru import logger

from collectors.base import (
    BaseCollector, 
    CollectionResult, 
    CollectionStatus,
    OHLCVCandle
)
from collectors.deribit.client import DeribitClient, DeribitAPIError
from utils.time_utils import (
    to_unix_ms,
    from_unix_ms,
    split_time_range,
    get_timeframe_seconds,
    DeribitTimeUtils
)
from utils.logger import log_collection_start, log_collection_complete, log_collection_error


class DeribitOHLCVCollector(BaseCollector):
    """
    Collector for Deribit OHLCV (candlestick) data.
    
    Uses the /public/get_tradingview_chart_data endpoint.
    
    Usage:
        collector = DeribitOHLCVCollector()
        
        result = collector.collect_ohlcv(
            instrument="BTC-PERPETUAL",
            timeframe="1h",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 31)
        )
        
        if result.is_success:
            candles = result.data
            for candle in candles:
                print(f"{candle['timestamp']}: {candle['close']}")
    """
    
    # Maximum candles per request (Deribit limit)
    MAX_CANDLES_PER_REQUEST = 5000
    
    # Supported timeframes and their Deribit resolution values
    TIMEFRAME_MAP = {
        "1m": "1",
        "3m": "3",
        "5m": "5",
        "10m": "10",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "2h": "120",
        "3h": "180",
        "4h": "240",
        "6h": "360",
        "12h": "720",
        "1d": "1D"
    }
    
    def __init__(self, client: Optional[DeribitClient] = None):
        """
        Initialize OHLCV collector.
        
        Args:
            client: Deribit client instance (creates new one if None)
        """
        super().__init__(source="deribit")
        self.client = client or DeribitClient()
        self._instruments_cache: Optional[List[str]] = None
    
    def get_available_instruments(self) -> List[str]:
        """Get list of available instruments."""
        if self._instruments_cache is None:
            self._instruments_cache = []
            
            # Get perpetual instruments for each currency
            for currency in ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "MATIC"]:
                try:
                    instruments = self.client.get_instruments(currency=currency, kind="future")
                    for inst in instruments:
                        if inst.get("settlement_period") == "perpetual":
                            self._instruments_cache.append(inst["instrument_name"])
                except DeribitAPIError as e:
                    logger.warning(f"Failed to get instruments for {currency}: {e}")
        
        return self._instruments_cache
    
    def collect_ohlcv(
        self,
        instrument: str,
        timeframe: str,
        start: datetime,
        end: datetime
    ) -> CollectionResult:
        """
        Collect OHLCV candlestick data for an instrument.
        
        Args:
            instrument: Instrument name (e.g., "BTC-PERPETUAL")
            timeframe: Timeframe string (1m, 5m, 1h, 1d, etc.)
            start: Start datetime (UTC)
            end: End datetime (UTC)
            
        Returns:
            CollectionResult with OHLCV candle data
        """
        start_time = time.time()
        data_type = f"ohlcv_{timeframe}"
        
        log_collection_start(self.source, instrument, timeframe, start, end)
        
        # Validate timeframe
        if timeframe not in self.TIMEFRAME_MAP:
            return CollectionResult(
                status=CollectionStatus.FAILED,
                instrument=instrument,
                data_type=data_type,
                source=self.source,
                start_time=start,
                end_time=end,
                records_collected=0,
                duration_seconds=time.time() - start_time,
                error_message=f"Unsupported timeframe: {timeframe}. Supported: {list(self.TIMEFRAME_MAP.keys())}"
            )
        
        resolution = self.TIMEFRAME_MAP[timeframe]
        interval_seconds = get_timeframe_seconds(timeframe)
        
        # Split time range into manageable chunks
        chunks = split_time_range(
            start=start,
            end=end,
            max_candles=self.MAX_CANDLES_PER_REQUEST,
            interval_seconds=interval_seconds
        )
        
        all_candles: List[Dict[str, Any]] = []
        errors = []
        
        for chunk_start, chunk_end in chunks:
            try:
                candles = self._fetch_chunk(
                    instrument=instrument,
                    resolution=resolution,
                    start=chunk_start,
                    end=chunk_end
                )
                all_candles.extend(candles)
                
            except DeribitAPIError as e:
                error_msg = f"Chunk {chunk_start} to {chunk_end}: {e.message}"
                errors.append(error_msg)
                logger.warning(error_msg)
        
        # Determine status
        duration = time.time() - start_time
        
        if not all_candles and errors:
            log_collection_error(self.source, instrument, Exception(errors[0]))
            return CollectionResult(
                status=CollectionStatus.FAILED,
                instrument=instrument,
                data_type=data_type,
                source=self.source,
                start_time=start,
                end_time=end,
                records_collected=0,
                duration_seconds=duration,
                error_message="; ".join(errors)
            )
        
        status = CollectionStatus.PARTIAL if errors else CollectionStatus.SUCCESS
        
        # Deduplicate by timestamp (in case of overlapping chunks)
        seen_timestamps = set()
        unique_candles = []
        for candle in all_candles:
            ts = candle["timestamp"]
            if ts not in seen_timestamps:
                seen_timestamps.add(ts)
                unique_candles.append(candle)
        
        # Sort by timestamp
        unique_candles.sort(key=lambda x: x["timestamp"])
        
        log_collection_complete(self.source, instrument, timeframe, len(unique_candles), duration)
        
        return CollectionResult(
            status=status,
            instrument=instrument,
            data_type=data_type,
            source=self.source,
            start_time=start,
            end_time=end,
            records_collected=len(unique_candles),
            duration_seconds=duration,
            error_message="; ".join(errors) if errors else None,
            data=unique_candles
        )
    
    def _fetch_chunk(
        self,
        instrument: str,
        resolution: str,
        start: datetime,
        end: datetime
    ) -> List[Dict[str, Any]]:
        """
        Fetch a single chunk of OHLCV data.
        
        Args:
            instrument: Instrument name
            resolution: Deribit resolution string
            start: Chunk start datetime
            end: Chunk end datetime
            
        Returns:
            List of candle dictionaries
        """
        start_ms = to_unix_ms(start)
        end_ms = to_unix_ms(end)
        
        result = self.client.get_tradingview_chart_data(
            instrument=instrument,
            resolution=resolution,
            start_timestamp=start_ms,
            end_timestamp=end_ms
        )
        
        # Parse response
        candles = []
        
        if result.get("status") == "ok":
            ticks = result.get("ticks", [])
            opens = result.get("open", [])
            highs = result.get("high", [])
            lows = result.get("low", [])
            closes = result.get("close", [])
            volumes = result.get("volume", [])
            
            for i in range(len(ticks)):
                candle = OHLCVCandle(
                    timestamp=from_unix_ms(ticks[i]),
                    open=opens[i],
                    high=highs[i],
                    low=lows[i],
                    close=closes[i],
                    volume=volumes[i]
                )
                
                # Validate candle
                if candle.validate():
                    candles.append(candle.to_dict())
                else:
                    logger.warning(f"Invalid candle data at {candle.timestamp}")
        
        return candles
    
    def collect_all_timeframes(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
        timeframes: Optional[List[str]] = None
    ) -> Dict[str, CollectionResult]:
        """
        Collect OHLCV data for multiple timeframes.
        
        Args:
            instrument: Instrument name
            start: Start datetime
            end: End datetime
            timeframes: List of timeframes (default: all supported)
            
        Returns:
            Dictionary mapping timeframe to CollectionResult
        """
        if timeframes is None:
            timeframes = list(self.TIMEFRAME_MAP.keys())
        
        results = {}
        
        for timeframe in timeframes:
            logger.info(f"Collecting {timeframe} data for {instrument}")
            results[timeframe] = self.collect_ohlcv(
                instrument=instrument,
                timeframe=timeframe,
                start=start,
                end=end
            )
        
        return results
    
    def get_latest_candle(
        self,
        instrument: str,
        timeframe: str = "1h"
    ) -> Optional[Dict[str, Any]]:
        """
        Get the most recent candle for an instrument.
        
        Args:
            instrument: Instrument name
            timeframe: Timeframe string
            
        Returns:
            Latest candle dictionary or None
        """
        from datetime import timedelta
        
        end = datetime.now(timezone.utc)
        interval_seconds = get_timeframe_seconds(timeframe)
        start = end - timedelta(seconds=interval_seconds * 2)
        
        result = self.collect_ohlcv(
            instrument=instrument,
            timeframe=timeframe,
            start=start,
            end=end
        )
        
        if result.is_success and result.data:
            return result.data[-1]
        
        return None


