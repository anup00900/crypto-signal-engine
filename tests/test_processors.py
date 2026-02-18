"""
Tests for data processors.
"""

import pytest
from datetime import datetime, timezone, timedelta

from processors.trade_aggregator import aggregate_trades_to_ohlcv, TradeAggregator
from processors.data_validator import DataValidator, ValidationLevel
from processors.gap_filler import GapFiller, DataGap, GapStatus


class TestTradeAggregator:
    """Tests for trade aggregation."""
    
    def test_aggregate_single_trade(self):
        """Test aggregation of a single trade."""
        trades = [
            {
                "timestamp": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
                "price": 50000.0,
                "amount": 1.0
            }
        ]
        
        candles = aggregate_trades_to_ohlcv(trades, interval_seconds=1)
        
        assert len(candles) == 1
        assert candles[0]["open"] == 50000.0
        assert candles[0]["high"] == 50000.0
        assert candles[0]["low"] == 50000.0
        assert candles[0]["close"] == 50000.0
        assert candles[0]["volume"] == 1.0
    
    def test_aggregate_multiple_trades_same_second(self):
        """Test aggregation of multiple trades in same second."""
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        trades = [
            {"timestamp": base_time, "price": 50000.0, "amount": 1.0},
            {"timestamp": base_time, "price": 50100.0, "amount": 2.0},
            {"timestamp": base_time, "price": 49900.0, "amount": 1.5},
            {"timestamp": base_time, "price": 50050.0, "amount": 0.5},
        ]
        
        candles = aggregate_trades_to_ohlcv(trades, interval_seconds=1)
        
        assert len(candles) == 1
        assert candles[0]["open"] == 50000.0  # First trade
        assert candles[0]["high"] == 50100.0  # Max
        assert candles[0]["low"] == 49900.0   # Min
        assert candles[0]["close"] == 50050.0  # Last trade
        assert candles[0]["volume"] == 5.0     # Sum
        assert candles[0]["trades_count"] == 4
    
    def test_aggregate_multiple_seconds(self):
        """Test aggregation across multiple seconds."""
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        trades = [
            {"timestamp": base_time, "price": 50000.0, "amount": 1.0},
            {"timestamp": base_time + timedelta(seconds=1), "price": 50100.0, "amount": 2.0},
            {"timestamp": base_time + timedelta(seconds=2), "price": 50200.0, "amount": 1.5},
        ]
        
        candles = aggregate_trades_to_ohlcv(trades, interval_seconds=1)
        
        assert len(candles) == 3
        assert candles[0]["close"] == 50000.0
        assert candles[1]["close"] == 50100.0
        assert candles[2]["close"] == 50200.0
    
    def test_empty_trades(self):
        """Test aggregation with empty trades list."""
        candles = aggregate_trades_to_ohlcv([], interval_seconds=1)
        assert len(candles) == 0


class TestTradeAggregatorClass:
    """Tests for TradeAggregator class."""
    
    def test_streaming_aggregation(self):
        """Test streaming aggregation."""
        aggregator = TradeAggregator(interval_seconds=1)
        
        base_time = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        
        # First batch - all same second
        batch1 = [
            {"timestamp": base_time, "price": 50000.0, "amount": 1.0},
            {"timestamp": base_time, "price": 50100.0, "amount": 2.0},
        ]
        
        candles1 = aggregator.process_trades(batch1)
        assert len(candles1) == 0  # Not complete yet
        
        # Second batch - new second triggers completion of first
        batch2 = [
            {"timestamp": base_time + timedelta(seconds=1), "price": 50200.0, "amount": 1.0},
        ]
        
        candles2 = aggregator.process_trades(batch2)
        assert len(candles2) == 1  # First second complete
        assert candles2[0]["high"] == 50100.0
        
        # Flush remaining
        final = aggregator.flush()
        assert len(final) == 1
    
    def test_stats(self):
        """Test aggregation statistics."""
        aggregator = TradeAggregator(interval_seconds=1)
        
        trades = [
            {"timestamp": datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc), "price": 50000.0, "amount": 1.0},
            {"timestamp": datetime(2024, 1, 1, 0, 0, 1, tzinfo=timezone.utc), "price": 50100.0, "amount": 2.0},
        ]
        
        aggregator.process_trades(trades)
        aggregator.flush()
        
        stats = aggregator.get_stats()
        assert stats["trades_processed"] == 2
        assert stats["candles_created"] == 2


class TestDataValidator:
    """Tests for data validation."""
    
    def test_valid_candles(self):
        """Test validation of valid candles."""
        candles = [
            {
                "timestamp": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
                "open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0,
                "volume": 1000.0
            },
            {
                "timestamp": datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
                "open": 105.0, "high": 115.0, "low": 100.0, "close": 110.0,
                "volume": 1200.0
            },
        ]
        
        validator = DataValidator()
        result = validator.validate_ohlcv(candles)
        
        assert result.is_valid is True
        assert result.total_records == 2
        assert result.valid_records == 2
        assert result.error_count == 0
    
    def test_invalid_high_low(self):
        """Test detection of invalid high < low."""
        candles = [
            {
                "timestamp": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
                "open": 100.0, "high": 90.0, "low": 95.0, "close": 92.0,  # Invalid
                "volume": 1000.0
            },
        ]
        
        validator = DataValidator()
        result = validator.validate_ohlcv(candles)
        
        assert result.is_valid is False
        assert result.error_count >= 1
        
        error_codes = [i.code for i in result.issues if i.level == ValidationLevel.ERROR]
        assert "INVALID_HIGH_LOW" in error_codes
    
    def test_gap_detection(self):
        """Test gap detection in candles."""
        candles = [
            {
                "timestamp": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
                "open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0,
                "volume": 1000.0
            },
            {
                "timestamp": datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc),  # Gap!
                "open": 105.0, "high": 115.0, "low": 100.0, "close": 110.0,
                "volume": 1200.0
            },
        ]
        
        validator = DataValidator()
        result = validator.validate_ohlcv(candles, expected_interval_seconds=3600)
        
        # Should detect gap
        gap_warnings = [i for i in result.issues if i.code == "GAP_DETECTED"]
        assert len(gap_warnings) >= 1


class TestGapFiller:
    """Tests for gap detection and filling."""
    
    def test_detect_gap_between_candles(self):
        """Test detection of gap between candles."""
        candles = [
            {
                "timestamp": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
                "close": 100.0
            },
            {
                "timestamp": datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),  # 1 hour gap
                "close": 105.0
            },
        ]
        
        filler = GapFiller(interval_seconds=3600)
        gaps = filler.detect_gaps(
            candles=candles,
            instrument="BTC-PERPETUAL",
            data_type="ohlcv_1h"
        )
        
        assert len(gaps) == 1
        assert gaps[0].expected_records == 1
    
    def test_detect_gap_at_start(self):
        """Test detection of gap at start of range."""
        candles = [
            {
                "timestamp": datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
                "close": 100.0
            },
        ]
        
        filler = GapFiller(interval_seconds=3600)
        gaps = filler.detect_gaps(
            candles=candles,
            expected_start=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            instrument="BTC-PERPETUAL",
            data_type="ohlcv_1h"
        )
        
        assert len(gaps) >= 1
    
    def test_no_gaps(self):
        """Test with no gaps."""
        candles = [
            {
                "timestamp": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
                "close": 100.0
            },
            {
                "timestamp": datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
                "close": 105.0
            },
            {
                "timestamp": datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
                "close": 110.0
            },
        ]
        
        filler = GapFiller(interval_seconds=3600)
        gaps = filler.detect_gaps(candles=candles)
        
        assert len(gaps) == 0
    
    def test_fill_gap_forward(self):
        """Test forward gap filling."""
        candles = [
            {
                "timestamp": datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
                "open": 100.0, "high": 110.0, "low": 95.0, "close": 105.0,
                "volume": 1000.0
            },
            {
                "timestamp": datetime(2024, 1, 1, 2, 0, tzinfo=timezone.utc),
                "open": 108.0, "high": 115.0, "low": 100.0, "close": 110.0,
                "volume": 1200.0
            },
        ]
        
        filler = GapFiller(interval_seconds=3600)
        gaps = filler.detect_gaps(candles=candles)
        
        filled = filler.fill_gaps(candles, gaps, fill_method="forward")
        
        assert len(filled) == 3
        
        # Middle candle should be filled with previous close
        middle = filled[1]
        assert middle["is_gap_fill"] is True
        assert middle["open"] == 105.0
        assert middle["close"] == 105.0


class TestDataGap:
    """Tests for DataGap class."""
    
    def test_duration_calculation(self):
        """Test gap duration calculation."""
        gap = DataGap(
            instrument="BTC-PERPETUAL",
            data_type="ohlcv_1h",
            start=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            end=datetime(2024, 1, 1, 3, 0, tzinfo=timezone.utc),
            expected_records=3
        )
        
        assert gap.duration_seconds == 10800  # 3 hours
        assert "h" in gap.duration_human
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        gap = DataGap(
            instrument="BTC-PERPETUAL",
            data_type="ohlcv_1h",
            start=datetime(2024, 1, 1, 0, 0, tzinfo=timezone.utc),
            end=datetime(2024, 1, 1, 1, 0, tzinfo=timezone.utc),
            expected_records=1,
            status=GapStatus.DETECTED
        )
        
        d = gap.to_dict()
        
        assert d["instrument"] == "BTC-PERPETUAL"
        assert d["data_type"] == "ohlcv_1h"
        assert d["status"] == "detected"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


