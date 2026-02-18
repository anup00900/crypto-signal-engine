"""
Database configuration and connection utilities.
"""

from typing import Optional
from config.settings import settings


def get_connection_params(role: str = "collector") -> dict:
    """
    Get database connection parameters for a specific role.
    
    Args:
        role: One of 'admin', 'collector', 'analyst', 'api'
        
    Returns:
        Dictionary with connection parameters
    """
    db = settings.database
    
    credentials = {
        "admin": (db.admin_user, db.admin_password),
        "collector": (db.collector_user, db.collector_password),
        "analyst": (db.analyst_user, db.analyst_password),
        "api": (db.api_user, db.api_password),
    }
    
    user, password = credentials.get(role, credentials["collector"])
    
    return {
        "host": db.host,
        "port": db.port,
        "database": db.database,
        "user": user,
        "password": password,
    }


def get_connection_url(role: str = "collector") -> str:
    """
    Get SQLAlchemy connection URL for a specific role.
    
    Args:
        role: One of 'admin', 'collector', 'analyst', 'api'
        
    Returns:
        PostgreSQL connection URL string
    """
    return settings.database.get_connection_string(role)


# Table names constants
class Tables:
    """Database table names."""
    
    # Reference data
    INSTRUMENTS = "instruments"
    
    # OHLCV data by timeframe
    OHLCV_1S = "ohlcv_1s"
    OHLCV_1M = "ohlcv_1m"
    OHLCV_5M = "ohlcv_5m"
    OHLCV_15M = "ohlcv_15m"
    OHLCV_1H = "ohlcv_1h"
    OHLCV_4H = "ohlcv_4h"
    OHLCV_1D = "ohlcv_1d"
    
    # Trade data (for 1s aggregation)
    TRADES = "trades"
    
    # Funding rates
    FUNDING_RATES = "funding_rates"
    
    # Collection metadata
    COLLECTION_LOG = "collection_log"
    DATA_GAPS = "data_gaps"


# Index names
class Indexes:
    """Database index names."""
    
    # Primary indexes for OHLCV queries
    IDX_OHLCV_INSTRUMENT_TIME = "idx_{table}_instrument_timestamp"
    IDX_OHLCV_TIMESTAMP = "idx_{table}_timestamp"
    
    # Trade indexes
    IDX_TRADES_INSTRUMENT_TIME = "idx_trades_instrument_timestamp"
    IDX_TRADES_TIMESTAMP = "idx_trades_timestamp"
    
    # Funding rate indexes
    IDX_FUNDING_INSTRUMENT_TIME = "idx_funding_instrument_timestamp"


