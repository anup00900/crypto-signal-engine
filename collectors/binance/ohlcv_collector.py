"""
Binance OHLCV data collector.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from loguru import logger

from collectors.base import (
    BaseCollector,
    CollectionResult,
    CollectionStatus,
    OHLCVCandle
)
from collectors.binance.client import BinanceClient, BinanceAPIError
from utils.time_utils import (
    to_unix_ms,
    from_unix_ms,
    split_time_range,
    get_timeframe_seconds,
    BinanceTimeUtils
)


class BinanceOHLCVCollector(BaseCollector):
    """
    Collector for Binance OHLCV (candlestick) data.
    
    Usage:
        collector = BinanceOHLCVCollector()
        
        result = collector.collect_ohlcv(
            instrument="BTCUSDT",
            timeframe="1h",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 31)
        )
    """
    
    MAX_CANDLES_PER_REQUEST = 1000
    
    TIMEFRAME_MAP = {
        "1s": "1s",
        "1m": "1m",
        "3m": "3m",
        "5m": "5m",
        "15m": "15m",
        "30m": "30m",
        "1h": "1h",
        "2h": "2h",
        "4h": "4h",
        "6h": "6h",
        "8h": "8h",
        "12h": "12h",
        "1d": "1d",
        "1w": "1w"
    }
    
    def __init__(
        self,
        client: Optional[BinanceClient] = None,
        use_futures: bool = True
    ):
        """
        Initialize OHLCV collector.
        
        Args:
            client: Binance client instance
            use_futures: Use futures API (higher limits)
        """
        super().__init__(source="binance")
        self.client = client or BinanceClient()
        self.use_futures = use_futures
    
    def get_available_instruments(self) -> List[str]:
        """Get list of available instruments."""
        try:
            info = self.client.get_exchange_info()
            return [s["symbol"] for s in info.get("symbols", [])]
        except BinanceAPIError:
            return []
    
    def collect_ohlcv(
        self,
        instrument: str,
        timeframe: str,
        start: datetime,
        end: datetime
    ) -> CollectionResult:
        """
        Collect OHLCV candlestick data.
        
        Args:
            instrument: Symbol (e.g., "BTCUSDT")
            timeframe: Timeframe string
            start: Start datetime
            end: End datetime
            
        Returns:
            CollectionResult with OHLCV data
        """
        start_time = time.time()
        data_type = f"ohlcv_{timeframe}"
        
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
                error_message=f"Unsupported timeframe: {timeframe}"
            )
        
        interval = self.TIMEFRAME_MAP[timeframe]
        interval_seconds = get_timeframe_seconds(timeframe)
        
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
                    symbol=instrument,
                    interval=interval,
                    start=chunk_start,
                    end=chunk_end
                )
                all_candles.extend(candles)
                
            except BinanceAPIError as e:
                errors.append(f"Chunk {chunk_start}: {e.message}")
        
        duration = time.time() - start_time
        
        if not all_candles and errors:
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
        
        # Deduplicate
        seen = set()
        unique_candles = []
        for c in all_candles:
            ts = c["timestamp"]
            if ts not in seen:
                seen.add(ts)
                unique_candles.append(c)
        
        unique_candles.sort(key=lambda x: x["timestamp"])
        
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
        symbol: str,
        interval: str,
        start: datetime,
        end: datetime
    ) -> List[Dict[str, Any]]:
        """Fetch a single chunk of OHLCV data."""
        start_ms = to_unix_ms(start)
        end_ms = to_unix_ms(end)
        
        if self.use_futures:
            klines = self.client.get_futures_klines(
                symbol=symbol,
                interval=interval,
                start_time=start_ms,
                end_time=end_ms
            )
        else:
            klines = self.client.get_klines(
                symbol=symbol,
                interval=interval,
                start_time=start_ms,
                end_time=end_ms
            )
        
        candles = []
        for k in klines:
            # Binance kline format:
            # [open_time, open, high, low, close, volume, close_time, 
            #  quote_volume, trades, taker_buy_base, taker_buy_quote, ignore]
            candle = OHLCVCandle(
                timestamp=from_unix_ms(k[0]),
                open=float(k[1]),
                high=float(k[2]),
                low=float(k[3]),
                close=float(k[4]),
                volume=float(k[5]),
                volume_usd=float(k[7]),  # Quote volume
                trades_count=int(k[8])
            )
            
            if candle.validate():
                candles.append(candle.to_dict())
        
        return candles


