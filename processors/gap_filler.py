"""
Gap detection and filling for time series data.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional, Tuple
from enum import Enum

from loguru import logger


class GapStatus(Enum):
    """Status of a data gap."""
    DETECTED = "detected"
    FILLING = "filling"
    FILLED = "filled"
    UNFILLABLE = "unfillable"


@dataclass
class DataGap:
    """Represents a gap in time series data."""
    
    instrument: str
    data_type: str
    start: datetime
    end: datetime
    expected_records: int
    status: GapStatus = GapStatus.DETECTED
    
    @property
    def duration_seconds(self) -> float:
        """Get gap duration in seconds."""
        return (self.end - self.start).total_seconds()
    
    @property
    def duration_human(self) -> str:
        """Get human-readable duration."""
        seconds = self.duration_seconds
        if seconds < 60:
            return f"{seconds:.0f}s"
        elif seconds < 3600:
            return f"{seconds / 60:.1f}m"
        elif seconds < 86400:
            return f"{seconds / 3600:.1f}h"
        else:
            return f"{seconds / 86400:.1f}d"
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "instrument": self.instrument,
            "data_type": self.data_type,
            "gap_start": self.start,
            "gap_end": self.end,
            "expected_records": self.expected_records,
            "status": self.status.value
        }


class GapFiller:
    """
    Detects and fills gaps in time series data.
    
    Usage:
        filler = GapFiller(interval_seconds=60)  # 1-minute data
        
        # Detect gaps
        gaps = filler.detect_gaps(
            candles=existing_data,
            expected_start=start_time,
            expected_end=end_time
        )
        
        # Fill gaps with synthetic data
        filled_data = filler.fill_gaps(
            candles=existing_data,
            gaps=gaps,
            fill_method="forward"
        )
    """
    
    def __init__(
        self,
        interval_seconds: int,
        tolerance_seconds: Optional[int] = None
    ):
        """
        Initialize gap filler.
        
        Args:
            interval_seconds: Expected interval between data points
            tolerance_seconds: Allowed tolerance before considering it a gap
        """
        self.interval_seconds = interval_seconds
        self.tolerance_seconds = tolerance_seconds or (interval_seconds // 2)
    
    def detect_gaps(
        self,
        candles: List[Dict[str, Any]],
        expected_start: Optional[datetime] = None,
        expected_end: Optional[datetime] = None,
        instrument: str = "",
        data_type: str = "ohlcv"
    ) -> List[DataGap]:
        """
        Detect gaps in candlestick data.
        
        Args:
            candles: List of candle dictionaries with 'timestamp' field
            expected_start: Expected start time (checks for gap at beginning)
            expected_end: Expected end time (checks for gap at end)
            instrument: Instrument name for gap records
            data_type: Data type for gap records
            
        Returns:
            List of DataGap objects
        """
        gaps = []
        
        if not candles:
            if expected_start and expected_end:
                gap = DataGap(
                    instrument=instrument,
                    data_type=data_type,
                    start=expected_start,
                    end=expected_end,
                    expected_records=self._calculate_expected_records(
                        expected_start, expected_end
                    )
                )
                gaps.append(gap)
            return gaps
        
        # Sort by timestamp
        sorted_candles = sorted(candles, key=lambda x: x.get("timestamp"))
        
        # Check for gap at the beginning
        first_timestamp = sorted_candles[0].get("timestamp")
        if expected_start and first_timestamp:
            if isinstance(first_timestamp, str):
                first_timestamp = datetime.fromisoformat(first_timestamp.replace('Z', '+00:00'))
            
            if (first_timestamp - expected_start).total_seconds() > self.interval_seconds + self.tolerance_seconds:
                gap = DataGap(
                    instrument=instrument,
                    data_type=data_type,
                    start=expected_start,
                    end=first_timestamp,
                    expected_records=self._calculate_expected_records(
                        expected_start, first_timestamp
                    )
                )
                gaps.append(gap)
        
        # Check for gaps between candles
        for i in range(1, len(sorted_candles)):
            prev_timestamp = sorted_candles[i - 1].get("timestamp")
            curr_timestamp = sorted_candles[i].get("timestamp")
            
            if isinstance(prev_timestamp, str):
                prev_timestamp = datetime.fromisoformat(prev_timestamp.replace('Z', '+00:00'))
            if isinstance(curr_timestamp, str):
                curr_timestamp = datetime.fromisoformat(curr_timestamp.replace('Z', '+00:00'))
            
            time_diff = (curr_timestamp - prev_timestamp).total_seconds()
            
            if time_diff > self.interval_seconds + self.tolerance_seconds:
                gap_start = prev_timestamp + timedelta(seconds=self.interval_seconds)
                gap = DataGap(
                    instrument=instrument,
                    data_type=data_type,
                    start=gap_start,
                    end=curr_timestamp,
                    expected_records=self._calculate_expected_records(
                        gap_start, curr_timestamp
                    )
                )
                gaps.append(gap)
        
        # Check for gap at the end
        last_timestamp = sorted_candles[-1].get("timestamp")
        if expected_end and last_timestamp:
            if isinstance(last_timestamp, str):
                last_timestamp = datetime.fromisoformat(last_timestamp.replace('Z', '+00:00'))
            
            expected_next = last_timestamp + timedelta(seconds=self.interval_seconds)
            if (expected_end - expected_next).total_seconds() > self.tolerance_seconds:
                gap = DataGap(
                    instrument=instrument,
                    data_type=data_type,
                    start=expected_next,
                    end=expected_end,
                    expected_records=self._calculate_expected_records(
                        expected_next, expected_end
                    )
                )
                gaps.append(gap)
        
        return gaps
    
    def _calculate_expected_records(
        self,
        start: datetime,
        end: datetime
    ) -> int:
        """Calculate expected number of records in a time range."""
        duration = (end - start).total_seconds()
        return max(0, int(duration // self.interval_seconds))
    
    def fill_gaps(
        self,
        candles: List[Dict[str, Any]],
        gaps: List[DataGap],
        fill_method: str = "forward"
    ) -> List[Dict[str, Any]]:
        """
        Fill gaps in candlestick data.
        
        Args:
            candles: Original candle data
            gaps: List of gaps to fill
            fill_method: Method to use ("forward", "backward", "interpolate")
            
        Returns:
            List of candles with gaps filled
        """
        if not gaps:
            return candles
        
        # Sort candles by timestamp
        sorted_candles = sorted(candles, key=lambda x: x.get("timestamp"))
        result = list(sorted_candles)
        
        # Create timestamp index for quick lookup
        timestamp_index = {c.get("timestamp"): i for i, c in enumerate(result)}
        
        for gap in gaps:
            fill_candles = self._generate_fill_candles(
                gap=gap,
                candles=result,
                method=fill_method
            )
            result.extend(fill_candles)
        
        # Sort final result
        result.sort(key=lambda x: x.get("timestamp"))
        
        return result
    
    def _generate_fill_candles(
        self,
        gap: DataGap,
        candles: List[Dict[str, Any]],
        method: str
    ) -> List[Dict[str, Any]]:
        """Generate synthetic candles to fill a gap."""
        fill_candles = []
        
        # Find candles before and after gap
        before_candle = None
        after_candle = None
        
        for candle in candles:
            timestamp = candle.get("timestamp")
            if isinstance(timestamp, str):
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            
            if timestamp < gap.start:
                before_candle = candle
            elif timestamp >= gap.end and after_candle is None:
                after_candle = candle
                break
        
        # Generate fill candles
        current = gap.start
        while current < gap.end:
            if method == "forward" and before_candle:
                fill_candle = self._create_fill_candle_forward(
                    timestamp=current,
                    reference=before_candle
                )
            elif method == "backward" and after_candle:
                fill_candle = self._create_fill_candle_backward(
                    timestamp=current,
                    reference=after_candle
                )
            elif method == "interpolate" and before_candle and after_candle:
                progress = (current - gap.start).total_seconds() / gap.duration_seconds
                fill_candle = self._create_fill_candle_interpolate(
                    timestamp=current,
                    before=before_candle,
                    after=after_candle,
                    progress=progress
                )
            else:
                # Default to forward fill or zero
                fill_candle = self._create_fill_candle_zero(
                    timestamp=current,
                    reference=before_candle
                )
            
            fill_candles.append(fill_candle)
            current += timedelta(seconds=self.interval_seconds)
        
        return fill_candles
    
    def _create_fill_candle_forward(
        self,
        timestamp: datetime,
        reference: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create fill candle using forward fill (previous close)."""
        close = reference.get("close", 0)
        return {
            "timestamp": timestamp,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 0,
            "volume_usd": 0,
            "trades_count": 0,
            "is_gap_fill": True,
            "fill_method": "forward"
        }
    
    def _create_fill_candle_backward(
        self,
        timestamp: datetime,
        reference: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Create fill candle using backward fill (next open)."""
        open_price = reference.get("open", 0)
        return {
            "timestamp": timestamp,
            "open": open_price,
            "high": open_price,
            "low": open_price,
            "close": open_price,
            "volume": 0,
            "volume_usd": 0,
            "trades_count": 0,
            "is_gap_fill": True,
            "fill_method": "backward"
        }
    
    def _create_fill_candle_interpolate(
        self,
        timestamp: datetime,
        before: Dict[str, Any],
        after: Dict[str, Any],
        progress: float
    ) -> Dict[str, Any]:
        """Create fill candle using linear interpolation."""
        before_close = before.get("close", 0)
        after_open = after.get("open", 0)
        
        price = before_close + (after_open - before_close) * progress
        
        return {
            "timestamp": timestamp,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0,
            "volume_usd": 0,
            "trades_count": 0,
            "is_gap_fill": True,
            "fill_method": "interpolate"
        }
    
    def _create_fill_candle_zero(
        self,
        timestamp: datetime,
        reference: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Create fill candle with zero values."""
        price = reference.get("close", 0) if reference else 0
        return {
            "timestamp": timestamp,
            "open": price,
            "high": price,
            "low": price,
            "close": price,
            "volume": 0,
            "volume_usd": 0,
            "trades_count": 0,
            "is_gap_fill": True,
            "fill_method": "zero"
        }
    
    def generate_gap_report(
        self,
        gaps: List[DataGap]
    ) -> str:
        """Generate a human-readable gap report."""
        if not gaps:
            return "No gaps detected."
        
        lines = [
            f"Gap Report: {len(gaps)} gaps found",
            "=" * 50
        ]
        
        total_missing = sum(g.expected_records for g in gaps)
        total_duration = sum(g.duration_seconds for g in gaps)
        
        for i, gap in enumerate(gaps, 1):
            lines.append(
                f"{i}. {gap.start} to {gap.end}\n"
                f"   Duration: {gap.duration_human}\n"
                f"   Missing records: {gap.expected_records}\n"
                f"   Status: {gap.status.value}"
            )
        
        lines.append("=" * 50)
        lines.append(f"Total missing records: {total_missing}")
        lines.append(f"Total gap duration: {total_duration / 3600:.1f} hours")
        
        return "\n".join(lines)


