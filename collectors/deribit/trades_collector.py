"""
Deribit trade history collector for 1-second OHLCV aggregation.
"""

import time
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any, Generator

from loguru import logger

from collectors.base import (
    BaseTradesCollector,
    CollectionResult,
    CollectionStatus,
    Trade
)
from collectors.deribit.client import DeribitClient, DeribitAPIError
from utils.time_utils import (
    to_unix_ms,
    from_unix_ms,
    get_date_range
)
from utils.logger import log_collection_start, log_collection_complete, log_collection_error


class DeribitTradesCollector(BaseTradesCollector):
    """
    Collector for Deribit trade history data.
    
    This collector fetches raw trade data which can be aggregated
    into 1-second OHLCV candles for high-frequency analysis.
    
    Usage:
        collector = DeribitTradesCollector()
        
        # Collect trades for a time range
        result = collector.collect_trades(
            instrument="BTC-PERPETUAL",
            start=datetime(2024, 1, 1, 0, 0),
            end=datetime(2024, 1, 1, 1, 0)  # 1 hour
        )
        
        # Stream trades in chunks for large time ranges
        for chunk in collector.stream_trades(
            instrument="BTC-PERPETUAL",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 2)
        ):
            process(chunk)
    """
    
    # Maximum trades per request (Deribit limit)
    MAX_TRADES_PER_REQUEST = 1000
    
    # Chunk size for streaming (1 hour)
    STREAM_CHUNK_SECONDS = 3600
    
    def __init__(self, client: Optional[DeribitClient] = None):
        """
        Initialize trades collector.
        
        Args:
            client: Deribit client instance
        """
        super().__init__(source="deribit")
        self.client = client or DeribitClient()
        self._instruments_cache: Optional[List[str]] = None
    
    def get_available_instruments(self) -> List[str]:
        """Get list of available instruments."""
        if self._instruments_cache is None:
            self._instruments_cache = []
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
        Collect OHLCV by aggregating trades.
        
        For 1-second timeframe, this collector fetches trades and
        aggregates them into OHLCV candles.
        
        Args:
            instrument: Instrument name
            timeframe: Should be "1s" for this collector
            start: Start datetime
            end: End datetime
            
        Returns:
            CollectionResult with aggregated OHLCV data
        """
        if timeframe != "1s":
            logger.warning(f"TradesCollector is optimized for 1s timeframe, got {timeframe}")
        
        # Collect trades
        trades_result = self.collect_trades(instrument, start, end)
        
        if not trades_result.is_success:
            return CollectionResult(
                status=trades_result.status,
                instrument=instrument,
                data_type=f"ohlcv_{timeframe}",
                source=self.source,
                start_time=start,
                end_time=end,
                records_collected=0,
                duration_seconds=trades_result.duration_seconds,
                error_message=trades_result.error_message
            )
        
        # Aggregate trades to 1s candles
        from processors.trade_aggregator import aggregate_trades_to_ohlcv
        
        candles = aggregate_trades_to_ohlcv(
            trades=trades_result.data,
            interval_seconds=1
        )
        
        return CollectionResult(
            status=CollectionStatus.SUCCESS,
            instrument=instrument,
            data_type=f"ohlcv_{timeframe}",
            source=self.source,
            start_time=start,
            end_time=end,
            records_collected=len(candles),
            duration_seconds=trades_result.duration_seconds,
            data=candles
        )
    
    def collect_trades(
        self,
        instrument: str,
        start: datetime,
        end: datetime
    ) -> CollectionResult:
        """
        Collect trade history for an instrument.
        
        Args:
            instrument: Instrument name
            start: Start datetime
            end: End datetime
            
        Returns:
            CollectionResult with trade data
        """
        start_time = time.time()
        
        log_collection_start(self.source, instrument, "trades", start, end)
        
        all_trades: List[Dict[str, Any]] = []
        errors = []
        
        # Iterate through time range
        for chunk_start, chunk_end in get_date_range(start, end, self.STREAM_CHUNK_SECONDS):
            try:
                trades = self._fetch_trades_for_range(
                    instrument=instrument,
                    start=chunk_start,
                    end=chunk_end
                )
                all_trades.extend(trades)
                
            except DeribitAPIError as e:
                error_msg = f"Chunk {chunk_start} to {chunk_end}: {e.message}"
                errors.append(error_msg)
                logger.warning(error_msg)
        
        duration = time.time() - start_time
        
        if not all_trades and errors:
            log_collection_error(self.source, instrument, Exception(errors[0]))
            return CollectionResult(
                status=CollectionStatus.FAILED,
                instrument=instrument,
                data_type="trades",
                source=self.source,
                start_time=start,
                end_time=end,
                records_collected=0,
                duration_seconds=duration,
                error_message="; ".join(errors)
            )
        
        status = CollectionStatus.PARTIAL if errors else CollectionStatus.SUCCESS
        
        # Sort by timestamp
        all_trades.sort(key=lambda x: x["timestamp"])
        
        log_collection_complete(self.source, instrument, "trades", len(all_trades), duration)
        
        return CollectionResult(
            status=status,
            instrument=instrument,
            data_type="trades",
            source=self.source,
            start_time=start,
            end_time=end,
            records_collected=len(all_trades),
            duration_seconds=duration,
            error_message="; ".join(errors) if errors else None,
            data=all_trades
        )
    
    def _fetch_trades_for_range(
        self,
        instrument: str,
        start: datetime,
        end: datetime
    ) -> List[Dict[str, Any]]:
        """
        Fetch all trades for a time range, handling pagination.
        
        Args:
            instrument: Instrument name
            start: Start datetime
            end: End datetime
            
        Returns:
            List of trade dictionaries
        """
        trades = []
        current_start = start
        
        while current_start < end:
            start_ms = to_unix_ms(current_start)
            end_ms = to_unix_ms(end)
            
            result = self.client.get_last_trades_by_instrument_and_time(
                instrument=instrument,
                start_timestamp=start_ms,
                end_timestamp=end_ms,
                count=self.MAX_TRADES_PER_REQUEST,
                sorting="asc"
            )
            
            trade_data = result.get("trades", [])
            
            if not trade_data:
                break
            
            # Parse trades
            for t in trade_data:
                trade = Trade(
                    trade_id=str(t.get("trade_id")),
                    timestamp=from_unix_ms(t.get("timestamp")),
                    price=t.get("price"),
                    amount=t.get("amount"),
                    direction=t.get("direction"),
                    tick_direction=t.get("tick_direction"),
                    liquidation=t.get("liquidation", False)
                )
                trades.append(trade.to_dict())
            
            # Check if more data available
            has_more = result.get("has_more", False)
            
            if not has_more or len(trade_data) < self.MAX_TRADES_PER_REQUEST:
                break
            
            # Move start to after last trade
            last_timestamp = trade_data[-1].get("timestamp")
            current_start = from_unix_ms(last_timestamp) + timedelta(milliseconds=1)
        
        return trades
    
    def stream_trades(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
        chunk_seconds: int = 3600
    ) -> Generator[List[Dict[str, Any]], None, None]:
        """
        Stream trades in chunks to handle large time ranges.
        
        Useful for processing trades without loading everything into memory.
        
        Args:
            instrument: Instrument name
            start: Start datetime
            end: End datetime
            chunk_seconds: Seconds per chunk (default 1 hour)
            
        Yields:
            Lists of trade dictionaries
        """
        for chunk_start, chunk_end in get_date_range(start, end, chunk_seconds):
            try:
                trades = self._fetch_trades_for_range(
                    instrument=instrument,
                    start=chunk_start,
                    end=chunk_end
                )
                
                if trades:
                    yield trades
                    
            except DeribitAPIError as e:
                logger.warning(f"Failed to fetch trades for {chunk_start} to {chunk_end}: {e}")
                continue
    
    def estimate_trade_count(
        self,
        instrument: str,
        start: datetime,
        end: datetime
    ) -> int:
        """
        Estimate the number of trades in a time range.
        
        Samples a small portion and extrapolates.
        
        Args:
            instrument: Instrument name
            start: Start datetime
            end: End datetime
            
        Returns:
            Estimated number of trades
        """
        # Sample 1 hour
        sample_end = min(start + timedelta(hours=1), end)
        
        trades = self._fetch_trades_for_range(
            instrument=instrument,
            start=start,
            end=sample_end
        )
        
        sample_duration = (sample_end - start).total_seconds()
        total_duration = (end - start).total_seconds()
        
        if sample_duration > 0:
            trades_per_second = len(trades) / sample_duration
            estimated_total = int(trades_per_second * total_duration)
            return estimated_total
        
        return 0


