"""
SQLAlchemy ORM models for the crypto data database.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional
from sqlalchemy import (
    Column, Integer, BigInteger, String, Boolean, DateTime, 
    Numeric, Text, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy.sql import func


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class Instrument(Base):
    """Instrument/trading pair reference data."""
    
    __tablename__ = 'instruments'
    __table_args__ = {'schema': 'crypto'}
    
    id = Column(Integer, primary_key=True)
    symbol = Column(String(20), nullable=False, index=True)
    name = Column(String(100), nullable=False)
    exchange = Column(String(50), nullable=False, index=True)
    instrument_name = Column(String(100), nullable=False, unique=True, index=True)
    instrument_type = Column(String(50), nullable=False)  # perpetual, spot, future
    base_currency = Column(String(20), nullable=False)
    quote_currency = Column(String(20), nullable=False)
    contract_size = Column(Numeric(20, 8))
    tick_size = Column(Numeric(20, 10))
    min_trade_amount = Column(Numeric(20, 8))
    is_active = Column(Boolean, default=True)
    coingecko_id = Column(String(100))
    extra_data = Column(JSONB)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    
    def __repr__(self):
        return f"<Instrument({self.instrument_name})>"


class OHLCVBase:
    """Base mixin for OHLCV tables."""
    
    id = Column(BigInteger, primary_key=True)
    instrument_id = Column(Integer, ForeignKey('crypto.instruments.id'))
    instrument = Column(String(100), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    open = Column(Numeric(20, 8), nullable=False)
    high = Column(Numeric(20, 8), nullable=False)
    low = Column(Numeric(20, 8), nullable=False)
    close = Column(Numeric(20, 8), nullable=False)
    volume = Column(Numeric(20, 8), nullable=False)
    volume_usd = Column(Numeric(20, 2))
    trades_count = Column(Integer)
    source = Column(String(50), default='deribit')
    collected_at = Column(DateTime(timezone=True), server_default=func.now())


class OHLCV1s(OHLCVBase, Base):
    """1-second OHLCV data (aggregated from trades)."""
    
    __tablename__ = 'ohlcv_1s'
    __table_args__ = (
        UniqueConstraint('instrument', 'timestamp'),
        Index('idx_ohlcv_1s_instrument_ts', 'instrument', 'timestamp'),
        Index('idx_ohlcv_1s_timestamp', 'timestamp'),
        {'schema': 'crypto'}
    )
    
    def __repr__(self):
        return f"<OHLCV1s({self.instrument}, {self.timestamp})>"


class OHLCV1m(OHLCVBase, Base):
    """1-minute OHLCV data."""
    
    __tablename__ = 'ohlcv_1m'
    __table_args__ = (
        UniqueConstraint('instrument', 'timestamp'),
        Index('idx_ohlcv_1m_instrument_ts', 'instrument', 'timestamp'),
        Index('idx_ohlcv_1m_timestamp', 'timestamp'),
        {'schema': 'crypto'}
    )
    
    def __repr__(self):
        return f"<OHLCV1m({self.instrument}, {self.timestamp})>"


class OHLCV5m(OHLCVBase, Base):
    """5-minute OHLCV data."""
    
    __tablename__ = 'ohlcv_5m'
    __table_args__ = (
        UniqueConstraint('instrument', 'timestamp'),
        Index('idx_ohlcv_5m_instrument_ts', 'instrument', 'timestamp'),
        Index('idx_ohlcv_5m_timestamp', 'timestamp'),
        {'schema': 'crypto'}
    )
    
    def __repr__(self):
        return f"<OHLCV5m({self.instrument}, {self.timestamp})>"


class OHLCV15m(OHLCVBase, Base):
    """15-minute OHLCV data."""
    
    __tablename__ = 'ohlcv_15m'
    __table_args__ = (
        UniqueConstraint('instrument', 'timestamp'),
        Index('idx_ohlcv_15m_instrument_ts', 'instrument', 'timestamp'),
        Index('idx_ohlcv_15m_timestamp', 'timestamp'),
        {'schema': 'crypto'}
    )
    
    def __repr__(self):
        return f"<OHLCV15m({self.instrument}, {self.timestamp})>"


class OHLCV1h(OHLCVBase, Base):
    """1-hour OHLCV data."""
    
    __tablename__ = 'ohlcv_1h'
    __table_args__ = (
        UniqueConstraint('instrument', 'timestamp'),
        Index('idx_ohlcv_1h_instrument_ts', 'instrument', 'timestamp'),
        Index('idx_ohlcv_1h_timestamp', 'timestamp'),
        {'schema': 'crypto'}
    )
    
    def __repr__(self):
        return f"<OHLCV1h({self.instrument}, {self.timestamp})>"


class OHLCV4h(OHLCVBase, Base):
    """4-hour OHLCV data."""
    
    __tablename__ = 'ohlcv_4h'
    __table_args__ = (
        UniqueConstraint('instrument', 'timestamp'),
        Index('idx_ohlcv_4h_instrument_ts', 'instrument', 'timestamp'),
        Index('idx_ohlcv_4h_timestamp', 'timestamp'),
        {'schema': 'crypto'}
    )
    
    def __repr__(self):
        return f"<OHLCV4h({self.instrument}, {self.timestamp})>"


class OHLCV1d(OHLCVBase, Base):
    """1-day OHLCV data."""
    
    __tablename__ = 'ohlcv_1d'
    __table_args__ = (
        UniqueConstraint('instrument', 'timestamp'),
        Index('idx_ohlcv_1d_instrument_ts', 'instrument', 'timestamp'),
        Index('idx_ohlcv_1d_timestamp', 'timestamp'),
        {'schema': 'crypto'}
    )
    
    def __repr__(self):
        return f"<OHLCV1d({self.instrument}, {self.timestamp})>"


class Trade(Base):
    """Raw trade data for 1-second aggregation."""
    
    __tablename__ = 'trades'
    __table_args__ = (
        UniqueConstraint('instrument', 'trade_id'),
        Index('idx_trades_instrument_ts', 'instrument', 'timestamp'),
        Index('idx_trades_timestamp', 'timestamp'),
        {'schema': 'crypto'}
    )
    
    id = Column(BigInteger, primary_key=True)
    instrument_id = Column(Integer, ForeignKey('crypto.instruments.id'))
    instrument = Column(String(100), nullable=False)
    trade_id = Column(String(100), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    price = Column(Numeric(20, 8), nullable=False)
    amount = Column(Numeric(20, 8), nullable=False)
    direction = Column(String(10))  # buy or sell
    tick_direction = Column(Integer)  # 0-3 for price movement
    liquidation = Column(Boolean, default=False)
    source = Column(String(50), default='deribit')
    collected_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<Trade({self.instrument}, {self.trade_id})>"


class FundingRate(Base):
    """Funding rate data for perpetual contracts."""
    
    __tablename__ = 'funding_rates'
    __table_args__ = (
        UniqueConstraint('instrument', 'timestamp'),
        Index('idx_funding_instrument_ts', 'instrument', 'timestamp'),
        Index('idx_funding_timestamp', 'timestamp'),
        {'schema': 'crypto'}
    )
    
    id = Column(BigInteger, primary_key=True)
    instrument_id = Column(Integer, ForeignKey('crypto.instruments.id'))
    instrument = Column(String(100), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    funding_rate = Column(Numeric(20, 10), nullable=False)
    mark_price = Column(Numeric(20, 8))
    index_price = Column(Numeric(20, 8))
    source = Column(String(50), default='deribit')
    collected_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<FundingRate({self.instrument}, {self.timestamp})>"


class CollectionLog(Base):
    """Log of data collection runs."""
    
    __tablename__ = 'collection_log'
    __table_args__ = (
        Index('idx_collection_log_instrument', 'instrument'),
        Index('idx_collection_log_type', 'data_type'),
        Index('idx_collection_log_time', 'collected_at'),
        {'schema': 'crypto'}
    )
    
    id = Column(Integer, primary_key=True)
    instrument = Column(String(100), nullable=False)
    data_type = Column(String(50), nullable=False)  # ohlcv_1s, ohlcv_1m, trades, funding
    source = Column(String(50), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    records_collected = Column(Integer, nullable=False)
    status = Column(String(20), nullable=False)  # success, failed, partial
    error_message = Column(Text)
    duration_seconds = Column(Numeric(10, 2))
    collected_at = Column(DateTime(timezone=True), server_default=func.now())
    
    def __repr__(self):
        return f"<CollectionLog({self.instrument}, {self.data_type}, {self.status})>"


class DataGap(Base):
    """Track gaps in collected data."""
    
    __tablename__ = 'data_gaps'
    __table_args__ = (
        Index('idx_data_gaps_instrument', 'instrument'),
        Index('idx_data_gaps_status', 'status'),
        {'schema': 'crypto'}
    )
    
    id = Column(Integer, primary_key=True)
    instrument = Column(String(100), nullable=False)
    data_type = Column(String(50), nullable=False)
    gap_start = Column(DateTime(timezone=True), nullable=False)
    gap_end = Column(DateTime(timezone=True), nullable=False)
    expected_records = Column(Integer)
    detected_at = Column(DateTime(timezone=True), server_default=func.now())
    filled_at = Column(DateTime(timezone=True))
    status = Column(String(20), default='detected')  # detected, filling, filled, unfillable
    
    def __repr__(self):
        return f"<DataGap({self.instrument}, {self.gap_start} - {self.gap_end})>"


# Model mapping for dynamic table selection
OHLCV_MODELS = {
    '1s': OHLCV1s,
    '1m': OHLCV1m,
    '5m': OHLCV5m,
    '15m': OHLCV15m,
    '1h': OHLCV1h,
    '4h': OHLCV4h,
    '1d': OHLCV1d,
}


def get_ohlcv_model(timeframe: str):
    """Get the appropriate OHLCV model for a timeframe."""
    return OHLCV_MODELS.get(timeframe.lower())

