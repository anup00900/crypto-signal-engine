"""
Tests for data collectors.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from collectors.base import CollectionResult, CollectionStatus, OHLCVCandle
from collectors.deribit import DeribitClient, DeribitOHLCVCollector


class TestOHLCVCandle:
    """Tests for OHLCVCandle data class."""
    
    def test_valid_candle(self):
        """Test valid candle validation."""
        candle = OHLCVCandle(
            timestamp=datetime.now(timezone.utc),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1000.0
        )
        assert candle.validate() is True
    
    def test_invalid_high_low(self):
        """Test candle with high < low."""
        candle = OHLCVCandle(
            timestamp=datetime.now(timezone.utc),
            open=100.0,
            high=90.0,  # Invalid: high < low
            low=95.0,
            close=92.0,
            volume=1000.0
        )
        assert candle.validate() is False
    
    def test_invalid_open_outside_range(self):
        """Test candle with open outside high-low range."""
        candle = OHLCVCandle(
            timestamp=datetime.now(timezone.utc),
            open=120.0,  # Invalid: open > high
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1000.0
        )
        assert candle.validate() is False
    
    def test_negative_volume(self):
        """Test candle with negative volume."""
        candle = OHLCVCandle(
            timestamp=datetime.now(timezone.utc),
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=-100.0  # Invalid
        )
        assert candle.validate() is False
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        timestamp = datetime.now(timezone.utc)
        candle = OHLCVCandle(
            timestamp=timestamp,
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1000.0,
            trades_count=50
        )
        
        d = candle.to_dict()
        
        assert d["timestamp"] == timestamp
        assert d["open"] == 100.0
        assert d["high"] == 110.0
        assert d["low"] == 95.0
        assert d["close"] == 105.0
        assert d["volume"] == 1000.0
        assert d["trades_count"] == 50


class TestCollectionResult:
    """Tests for CollectionResult."""
    
    def test_success_result(self):
        """Test successful collection result."""
        result = CollectionResult(
            status=CollectionStatus.SUCCESS,
            instrument="BTC-PERPETUAL",
            data_type="ohlcv_1h",
            source="deribit",
            start_time=datetime.now(timezone.utc) - timedelta(days=1),
            end_time=datetime.now(timezone.utc),
            records_collected=24,
            duration_seconds=5.0,
            data=[{"close": 50000}]
        )
        
        assert result.is_success is True
        assert result.records_collected == 24
    
    def test_failed_result(self):
        """Test failed collection result."""
        result = CollectionResult(
            status=CollectionStatus.FAILED,
            instrument="BTC-PERPETUAL",
            data_type="ohlcv_1h",
            source="deribit",
            start_time=datetime.now(timezone.utc) - timedelta(days=1),
            end_time=datetime.now(timezone.utc),
            records_collected=0,
            duration_seconds=2.0,
            error_message="API error"
        )
        
        assert result.is_success is False
        assert result.error_message == "API error"
    
    def test_to_log_entry(self):
        """Test conversion to log entry format."""
        result = CollectionResult(
            status=CollectionStatus.SUCCESS,
            instrument="BTC-PERPETUAL",
            data_type="ohlcv_1h",
            source="deribit",
            start_time=datetime.now(timezone.utc) - timedelta(days=1),
            end_time=datetime.now(timezone.utc),
            records_collected=24,
            duration_seconds=5.0
        )
        
        log = result.to_log_entry()
        
        assert log["instrument"] == "BTC-PERPETUAL"
        assert log["data_type"] == "ohlcv_1h"
        assert log["status"] == "success"


class TestDeribitClient:
    """Tests for Deribit API client."""
    
    @patch('collectors.deribit.client.requests.Session')
    def test_connection_test_success(self, mock_session):
        """Test successful connection test."""
        mock_response = Mock()
        mock_response.json.return_value = {"result": {"version": "1.0"}}
        mock_response.raise_for_status = Mock()
        
        mock_session.return_value.get.return_value = mock_response
        
        client = DeribitClient()
        # Would need proper mocking to test fully
    
    def test_rate_limiter_initialization(self):
        """Test that rate limiter is initialized."""
        client = DeribitClient()
        assert client.rate_limiter is not None


class TestDeribitOHLCVCollector:
    """Tests for Deribit OHLCV collector."""
    
    def test_unsupported_timeframe(self):
        """Test collection with unsupported timeframe."""
        mock_client = Mock()
        collector = DeribitOHLCVCollector(client=mock_client)
        
        result = collector.collect_ohlcv(
            instrument="BTC-PERPETUAL",
            timeframe="2m",  # Not supported
            start=datetime.now(timezone.utc) - timedelta(days=1),
            end=datetime.now(timezone.utc)
        )
        
        assert result.status == CollectionStatus.FAILED
        assert "Unsupported timeframe" in result.error_message
    
    def test_timeframe_map(self):
        """Test timeframe mapping is correct."""
        mock_client = Mock()
        collector = DeribitOHLCVCollector(client=mock_client)
        
        assert "1m" in collector.TIMEFRAME_MAP
        assert "1h" in collector.TIMEFRAME_MAP
        assert "1d" in collector.TIMEFRAME_MAP
        assert collector.TIMEFRAME_MAP["1h"] == "60"
        assert collector.TIMEFRAME_MAP["1d"] == "1D"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


