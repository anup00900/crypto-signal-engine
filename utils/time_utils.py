"""
Time and timestamp utilities for data collection.
"""

from datetime import datetime, timedelta, timezone
from typing import List, Tuple, Optional, Generator


def to_unix_ms(dt: datetime) -> int:
    """
    Convert datetime to Unix timestamp in milliseconds.
    
    Args:
        dt: Datetime object (should be timezone-aware, assumes UTC if naive)
        
    Returns:
        Unix timestamp in milliseconds
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def from_unix_ms(timestamp_ms: int) -> datetime:
    """
    Convert Unix timestamp in milliseconds to datetime.
    
    Args:
        timestamp_ms: Unix timestamp in milliseconds
        
    Returns:
        UTC datetime object
    """
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)


def to_unix_seconds(dt: datetime) -> int:
    """
    Convert datetime to Unix timestamp in seconds.
    
    Args:
        dt: Datetime object
        
    Returns:
        Unix timestamp in seconds
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


def from_unix_seconds(timestamp: int) -> datetime:
    """
    Convert Unix timestamp in seconds to datetime.
    
    Args:
        timestamp: Unix timestamp in seconds
        
    Returns:
        UTC datetime object
    """
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def get_date_range(
    start: datetime,
    end: datetime,
    interval_seconds: int
) -> Generator[Tuple[datetime, datetime], None, None]:
    """
    Generate date range chunks.
    
    Args:
        start: Start datetime
        end: End datetime
        interval_seconds: Size of each chunk in seconds
        
    Yields:
        Tuple of (chunk_start, chunk_end)
    """
    current = start
    delta = timedelta(seconds=interval_seconds)
    
    while current < end:
        chunk_end = min(current + delta, end)
        yield current, chunk_end
        current = chunk_end


def floor_timestamp(dt: datetime, interval_seconds: int) -> datetime:
    """
    Floor timestamp to interval boundary.
    
    Args:
        dt: Datetime to floor
        interval_seconds: Interval in seconds
        
    Returns:
        Floored datetime
    """
    timestamp = to_unix_seconds(dt)
    floored = (timestamp // interval_seconds) * interval_seconds
    return from_unix_seconds(floored)


def ceil_timestamp(dt: datetime, interval_seconds: int) -> datetime:
    """
    Ceil timestamp to interval boundary.
    
    Args:
        dt: Datetime to ceil
        interval_seconds: Interval in seconds
        
    Returns:
        Ceiled datetime
    """
    timestamp = to_unix_seconds(dt)
    if timestamp % interval_seconds == 0:
        return dt
    ceiled = ((timestamp // interval_seconds) + 1) * interval_seconds
    return from_unix_seconds(ceiled)


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def days_ago(days: int) -> datetime:
    """Get datetime for N days ago."""
    return now_utc() - timedelta(days=days)


def years_ago(years: int) -> datetime:
    """Get datetime for N years ago."""
    return now_utc() - timedelta(days=years * 365)


def get_history_start(years: int = 2) -> datetime:
    """
    Get the start datetime for historical data collection.
    
    Args:
        years: Number of years of history
        
    Returns:
        Start datetime (UTC, floored to day boundary)
    """
    start = years_ago(years)
    return floor_timestamp(start, 86400)  # Floor to day


def calculate_expected_candles(
    start: datetime,
    end: datetime,
    interval_seconds: int
) -> int:
    """
    Calculate expected number of candles in a time range.
    
    Args:
        start: Start datetime
        end: End datetime
        interval_seconds: Candle interval in seconds
        
    Returns:
        Expected number of candles
    """
    total_seconds = (end - start).total_seconds()
    return int(total_seconds // interval_seconds)


def split_time_range(
    start: datetime,
    end: datetime,
    max_candles: int,
    interval_seconds: int
) -> List[Tuple[datetime, datetime]]:
    """
    Split a time range into chunks that don't exceed max_candles.
    
    Useful for APIs that limit the number of candles per request.
    
    Args:
        start: Start datetime
        end: End datetime
        max_candles: Maximum candles per chunk
        interval_seconds: Candle interval in seconds
        
    Returns:
        List of (chunk_start, chunk_end) tuples
    """
    chunk_duration = timedelta(seconds=max_candles * interval_seconds)
    chunks = []
    
    current = start
    while current < end:
        chunk_end = min(current + chunk_duration, end)
        chunks.append((current, chunk_end))
        current = chunk_end
    
    return chunks


def format_duration(seconds: float) -> str:
    """
    Format duration in human-readable format.
    
    Args:
        seconds: Duration in seconds
        
    Returns:
        Formatted string (e.g., "2h 30m 15s")
    """
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    
    return " ".join(parts)


def get_timeframe_seconds(timeframe: str) -> int:
    """
    Convert timeframe string to seconds.
    
    Args:
        timeframe: Timeframe string (1s, 1m, 5m, 15m, 1h, 4h, 1d)
        
    Returns:
        Number of seconds
    """
    mapping = {
        "1s": 1,
        "1m": 60,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
        "6h": 21600,
        "12h": 43200,
        "1d": 86400,
        "1w": 604800,
    }
    
    return mapping.get(timeframe.lower(), 60)


# Deribit-specific time utilities
class DeribitTimeUtils:
    """Utilities for Deribit API timestamps."""
    
    # Deribit returns timestamps in milliseconds
    
    @staticmethod
    def to_deribit_timestamp(dt: datetime) -> int:
        """Convert datetime to Deribit timestamp (ms)."""
        return to_unix_ms(dt)
    
    @staticmethod
    def from_deribit_timestamp(timestamp_ms: int) -> datetime:
        """Convert Deribit timestamp (ms) to datetime."""
        return from_unix_ms(timestamp_ms)
    
    @staticmethod
    def get_resolution(timeframe: str) -> str:
        """
        Convert timeframe to Deribit resolution parameter.
        
        Deribit supports: 1, 3, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1D
        """
        mapping = {
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
            "1d": "1D",
        }
        return mapping.get(timeframe.lower(), "60")


# Binance-specific time utilities  
class BinanceTimeUtils:
    """Utilities for Binance API timestamps."""
    
    @staticmethod
    def to_binance_timestamp(dt: datetime) -> int:
        """Convert datetime to Binance timestamp (ms)."""
        return to_unix_ms(dt)
    
    @staticmethod
    def from_binance_timestamp(timestamp_ms: int) -> datetime:
        """Convert Binance timestamp (ms) to datetime."""
        return from_unix_ms(timestamp_ms)
    
    @staticmethod
    def get_interval(timeframe: str) -> str:
        """
        Convert timeframe to Binance interval parameter.
        
        Binance supports: 1s, 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
        """
        mapping = {
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
            "1w": "1w",
        }
        return mapping.get(timeframe.lower(), "1h")


