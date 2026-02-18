"""
Base collector class and common interfaces.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Any, Dict, Generator
from enum import Enum


class CollectionStatus(Enum):
    """Status of a collection operation."""
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    NO_DATA = "no_data"


@dataclass
class CollectionResult:
    """Result of a data collection operation."""
    
    status: CollectionStatus
    instrument: str
    data_type: str  # ohlcv_1d, ohlcv_1h, trades, funding, etc.
    source: str  # deribit, binance, etc.
    start_time: datetime
    end_time: datetime
    records_collected: int
    duration_seconds: float
    error_message: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    
    @property
    def is_success(self) -> bool:
        """Check if collection was successful."""
        return self.status in (CollectionStatus.SUCCESS, CollectionStatus.PARTIAL)
    
    def to_log_entry(self) -> dict:
        """Convert to database log entry format."""
        return {
            "instrument": self.instrument,
            "data_type": self.data_type,
            "source": self.source,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "records_collected": self.records_collected,
            "status": self.status.value,
            "error_message": self.error_message,
            "duration_seconds": self.duration_seconds
        }


@dataclass 
class OHLCVCandle:
    """Standard OHLCV candle data structure."""
    
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    volume_usd: Optional[float] = None
    trades_count: Optional[int] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "volume_usd": self.volume_usd,
            "trades_count": self.trades_count
        }
    
    def validate(self) -> bool:
        """Validate candle data."""
        # High should be >= Low
        if self.high < self.low:
            return False
        # Open and Close should be between High and Low
        if not (self.low <= self.open <= self.high):
            return False
        if not (self.low <= self.close <= self.high):
            return False
        # Volume should be non-negative
        if self.volume < 0:
            return False
        return True


@dataclass
class Trade:
    """Standard trade data structure."""
    
    trade_id: str
    timestamp: datetime
    price: float
    amount: float
    direction: Optional[str] = None  # buy or sell
    tick_direction: Optional[int] = None
    liquidation: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "trade_id": self.trade_id,
            "timestamp": self.timestamp,
            "price": self.price,
            "amount": self.amount,
            "direction": self.direction,
            "tick_direction": self.tick_direction,
            "liquidation": self.liquidation
        }


@dataclass
class FundingRate:
    """Standard funding rate data structure."""
    
    timestamp: datetime
    funding_rate: float
    mark_price: Optional[float] = None
    index_price: Optional[float] = None
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "timestamp": self.timestamp,
            "funding_rate": self.funding_rate,
            "mark_price": self.mark_price,
            "index_price": self.index_price
        }


class BaseCollector(ABC):
    """
    Abstract base class for all data collectors.
    
    Subclasses must implement:
    - collect_ohlcv(): Collect OHLCV candlestick data
    - get_available_instruments(): Get list of available instruments
    """
    
    def __init__(self, source: str):
        """
        Initialize collector.
        
        Args:
            source: Data source identifier (e.g., 'deribit', 'binance')
        """
        self.source = source
    
    @abstractmethod
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
            instrument: Instrument identifier
            timeframe: Timeframe string (1m, 5m, 1h, 1d, etc.)
            start: Start datetime
            end: End datetime
            
        Returns:
            CollectionResult with OHLCV data
        """
        pass
    
    @abstractmethod
    def get_available_instruments(self) -> List[str]:
        """
        Get list of available instruments from the exchange.
        
        Returns:
            List of instrument identifiers
        """
        pass
    
    def validate_instrument(self, instrument: str) -> bool:
        """
        Check if an instrument is available.
        
        Args:
            instrument: Instrument identifier
            
        Returns:
            True if available, False otherwise
        """
        return instrument in self.get_available_instruments()


class BaseTradesCollector(BaseCollector):
    """Base class for collectors that also support trade history."""
    
    @abstractmethod
    def collect_trades(
        self,
        instrument: str,
        start: datetime,
        end: datetime
    ) -> CollectionResult:
        """
        Collect trade history data.
        
        Args:
            instrument: Instrument identifier
            start: Start datetime
            end: End datetime
            
        Returns:
            CollectionResult with trade data
        """
        pass


class BaseFundingCollector(BaseCollector):
    """Base class for collectors that support funding rate history."""
    
    @abstractmethod
    def collect_funding_rates(
        self,
        instrument: str,
        start: datetime,
        end: datetime
    ) -> CollectionResult:
        """
        Collect funding rate history.
        
        Args:
            instrument: Instrument identifier
            start: Start datetime  
            end: End datetime
            
        Returns:
            CollectionResult with funding rate data
        """
        pass


