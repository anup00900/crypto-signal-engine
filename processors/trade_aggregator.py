"""
Aggregate trade data into OHLCV candles.

This module is essential for creating 1-second OHLCV data from raw trades
since most exchanges (including Deribit) don't provide native 1-second candles.
"""

from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from collections import defaultdict

from loguru import logger


def aggregate_trades_to_ohlcv(
    trades: List[Dict[str, Any]],
    interval_seconds: int = 1
) -> List[Dict[str, Any]]:
    """
    Aggregate trade data into OHLCV candles.
    
    Args:
        trades: List of trade dictionaries with 'timestamp', 'price', 'amount'
        interval_seconds: Candle interval in seconds (default 1 for 1-second candles)
        
    Returns:
        List of OHLCV candle dictionaries
    """
    if not trades:
        return []
    
    # Group trades by interval bucket
    buckets: Dict[datetime, List[Dict[str, Any]]] = defaultdict(list)
    
    for trade in trades:
        timestamp = trade.get("timestamp")
        
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        
        # Floor to interval boundary
        epoch = timestamp.timestamp()
        floored_epoch = (int(epoch) // interval_seconds) * interval_seconds
        bucket_time = datetime.fromtimestamp(floored_epoch, tz=timezone.utc)
        
        buckets[bucket_time].append(trade)
    
    # Create candles from buckets
    candles = []
    
    for bucket_time in sorted(buckets.keys()):
        bucket_trades = buckets[bucket_time]
        
        # Sort trades by timestamp within bucket
        bucket_trades.sort(key=lambda x: x.get("timestamp", datetime.min))
        
        # Calculate OHLCV
        prices = [t.get("price", 0) for t in bucket_trades]
        volumes = [abs(t.get("amount", 0)) for t in bucket_trades]
        
        candle = {
            "timestamp": bucket_time,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": sum(volumes),
            "trades_count": len(bucket_trades)
        }
        
        # Calculate volume in USD if price available
        if candle["close"] > 0:
            candle["volume_usd"] = candle["volume"] * candle["close"]
        
        candles.append(candle)
    
    return candles


class TradeAggregator:
    """
    Advanced trade aggregator with streaming support and gap handling.
    
    Usage:
        aggregator = TradeAggregator(interval_seconds=1)
        
        # Process trades in batches
        for trade_batch in trade_stream:
            candles = aggregator.process_trades(trade_batch)
            for candle in candles:
                store_candle(candle)
        
        # Get any remaining incomplete candles
        final_candles = aggregator.flush()
    """
    
    def __init__(
        self,
        interval_seconds: int = 1,
        fill_gaps: bool = False,
        gap_fill_value: str = "previous"  # "previous", "zero", "interpolate"
    ):
        """
        Initialize trade aggregator.
        
        Args:
            interval_seconds: Candle interval in seconds
            fill_gaps: Whether to fill gaps with synthetic candles
            gap_fill_value: How to fill gaps ("previous", "zero", "interpolate")
        """
        self.interval_seconds = interval_seconds
        self.fill_gaps = fill_gaps
        self.gap_fill_value = gap_fill_value
        
        # Current incomplete candle
        self._current_bucket: Optional[datetime] = None
        self._current_trades: List[Dict[str, Any]] = []
        
        # Last completed candle (for gap filling)
        self._last_candle: Optional[Dict[str, Any]] = None
        
        # Statistics
        self._trades_processed = 0
        self._candles_created = 0
        self._gaps_filled = 0
    
    def _get_bucket_time(self, timestamp: datetime) -> datetime:
        """Get the bucket time for a timestamp."""
        epoch = timestamp.timestamp()
        floored_epoch = (int(epoch) // self.interval_seconds) * self.interval_seconds
        return datetime.fromtimestamp(floored_epoch, tz=timezone.utc)
    
    def _create_candle(
        self,
        bucket_time: datetime,
        trades: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create a candle from trades."""
        prices = [t.get("price", 0) for t in trades]
        volumes = [abs(t.get("amount", 0)) for t in trades]
        
        candle = {
            "timestamp": bucket_time,
            "open": prices[0],
            "high": max(prices),
            "low": min(prices),
            "close": prices[-1],
            "volume": sum(volumes),
            "trades_count": len(trades)
        }
        
        if candle["close"] > 0:
            candle["volume_usd"] = candle["volume"] * candle["close"]
        
        return candle
    
    def _fill_gap(
        self,
        start_time: datetime,
        end_time: datetime,
        previous_candle: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Fill gap between two candles."""
        gap_candles = []
        current = start_time + timedelta(seconds=self.interval_seconds)
        
        while current < end_time:
            if self.gap_fill_value == "previous":
                # Use previous close as all OHLC values
                gap_candle = {
                    "timestamp": current,
                    "open": previous_candle["close"],
                    "high": previous_candle["close"],
                    "low": previous_candle["close"],
                    "close": previous_candle["close"],
                    "volume": 0,
                    "volume_usd": 0,
                    "trades_count": 0,
                    "is_gap_fill": True
                }
            elif self.gap_fill_value == "zero":
                # Zero volume candle with previous close
                gap_candle = {
                    "timestamp": current,
                    "open": previous_candle["close"],
                    "high": previous_candle["close"],
                    "low": previous_candle["close"],
                    "close": previous_candle["close"],
                    "volume": 0,
                    "volume_usd": 0,
                    "trades_count": 0,
                    "is_gap_fill": True
                }
            else:
                # Default to previous
                gap_candle = {
                    "timestamp": current,
                    "open": previous_candle["close"],
                    "high": previous_candle["close"],
                    "low": previous_candle["close"],
                    "close": previous_candle["close"],
                    "volume": 0,
                    "volume_usd": 0,
                    "trades_count": 0,
                    "is_gap_fill": True
                }
            
            gap_candles.append(gap_candle)
            self._gaps_filled += 1
            current += timedelta(seconds=self.interval_seconds)
        
        return gap_candles
    
    def process_trades(
        self,
        trades: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Process a batch of trades and return completed candles.
        
        Args:
            trades: List of trade dictionaries
            
        Returns:
            List of completed candle dictionaries
        """
        completed_candles = []
        
        for trade in trades:
            self._trades_processed += 1
            
            timestamp = trade.get("timestamp")
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            
            bucket_time = self._get_bucket_time(timestamp)
            
            # Check if we're in a new bucket
            if self._current_bucket is None:
                # First trade
                self._current_bucket = bucket_time
                self._current_trades = [trade]
            elif bucket_time > self._current_bucket:
                # New bucket - complete current candle
                candle = self._create_candle(self._current_bucket, self._current_trades)
                self._candles_created += 1
                
                # Check for gaps
                if self.fill_gaps and self._last_candle:
                    expected_next = self._last_candle["timestamp"] + timedelta(seconds=self.interval_seconds)
                    if self._current_bucket > expected_next:
                        gap_candles = self._fill_gap(
                            self._last_candle["timestamp"],
                            self._current_bucket,
                            self._last_candle
                        )
                        completed_candles.extend(gap_candles)
                
                completed_candles.append(candle)
                self._last_candle = candle
                
                # Start new bucket
                self._current_bucket = bucket_time
                self._current_trades = [trade]
            else:
                # Same bucket - add trade
                self._current_trades.append(trade)
        
        return completed_candles
    
    def flush(self) -> List[Dict[str, Any]]:
        """
        Flush any remaining incomplete candle.
        
        Returns:
            List containing the final candle (if any)
        """
        if self._current_bucket and self._current_trades:
            candle = self._create_candle(self._current_bucket, self._current_trades)
            self._candles_created += 1
            self._current_bucket = None
            self._current_trades = []
            return [candle]
        
        return []
    
    def reset(self):
        """Reset the aggregator state."""
        self._current_bucket = None
        self._current_trades = []
        self._last_candle = None
    
    def get_stats(self) -> Dict[str, int]:
        """Get aggregation statistics."""
        return {
            "trades_processed": self._trades_processed,
            "candles_created": self._candles_created,
            "gaps_filled": self._gaps_filled
        }


def aggregate_trades_streaming(
    trade_iterator,
    interval_seconds: int = 1,
    batch_size: int = 10000
):
    """
    Generator that aggregates trades to candles in a streaming fashion.
    
    Args:
        trade_iterator: Iterator yielding trade dictionaries
        interval_seconds: Candle interval
        batch_size: Number of trades to process per batch
        
    Yields:
        OHLCV candle dictionaries
    """
    aggregator = TradeAggregator(interval_seconds=interval_seconds)
    batch = []
    
    for trade in trade_iterator:
        batch.append(trade)
        
        if len(batch) >= batch_size:
            candles = aggregator.process_trades(batch)
            for candle in candles:
                yield candle
            batch = []
    
    # Process remaining trades
    if batch:
        candles = aggregator.process_trades(batch)
        for candle in candles:
            yield candle
    
    # Flush final candle
    final_candles = aggregator.flush()
    for candle in final_candles:
        yield candle


