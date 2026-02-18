"""
Application settings loaded from environment variables.
"""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from pydantic import Field


class DatabaseSettings(BaseSettings):
    """PostgreSQL database configuration."""
    
    host: str = Field(default="localhost", alias="POSTGRES_HOST")
    port: int = Field(default=5433, alias="POSTGRES_PORT")
    database: str = Field(default="crypto_data", alias="POSTGRES_DB")
    
    # Role-based credentials
    admin_user: str = Field(default="crypto_admin", alias="POSTGRES_ADMIN_USER")
    admin_password: str = Field(default="admin_password", alias="POSTGRES_ADMIN_PASSWORD")
    
    collector_user: str = Field(default="crypto_collector", alias="POSTGRES_COLLECTOR_USER")
    collector_password: str = Field(default="collector_password", alias="POSTGRES_COLLECTOR_PASSWORD")
    
    analyst_user: str = Field(default="crypto_analyst", alias="POSTGRES_ANALYST_USER")
    analyst_password: str = Field(default="analyst_password", alias="POSTGRES_ANALYST_PASSWORD")
    
    api_user: str = Field(default="crypto_api", alias="POSTGRES_API_USER")
    api_password: str = Field(default="api_password", alias="POSTGRES_API_PASSWORD")
    
    def get_connection_string(self, role: str = "collector") -> str:
        """Get connection string for specific role."""
        credentials = {
            "admin": (self.admin_user, self.admin_password),
            "collector": (self.collector_user, self.collector_password),
            "analyst": (self.analyst_user, self.analyst_password),
            "api": (self.api_user, self.api_password),
        }
        
        user, password = credentials.get(role, credentials["collector"])
        return f"postgresql://{user}:{password}@{self.host}:{self.port}/{self.database}"
    
    class Config:
        env_file = ".env"
        extra = "ignore"


class DeribitSettings(BaseSettings):
    """Deribit API configuration."""
    
    api_url: str = Field(default="https://www.deribit.com/api/v2", alias="DERIBIT_API_URL")
    test_api_url: str = Field(default="https://test.deribit.com/api/v2", alias="DERIBIT_TEST_API_URL")
    client_id: Optional[str] = Field(default=None, alias="DERIBIT_CLIENT_ID")
    client_secret: Optional[str] = Field(default=None, alias="DERIBIT_CLIENT_SECRET")
    use_testnet: bool = Field(default=False, alias="DERIBIT_USE_TESTNET")
    
    @property
    def base_url(self) -> str:
        """Get the appropriate base URL."""
        return self.test_api_url if self.use_testnet else self.api_url
    
    @property
    def is_authenticated(self) -> bool:
        """Check if credentials are provided."""
        return bool(self.client_id and self.client_secret)
    
    class Config:
        env_file = ".env"
        extra = "ignore"


class BinanceSettings(BaseSettings):
    """Binance API configuration."""
    
    api_url: str = Field(default="https://api.binance.com/api/v3", alias="BINANCE_API_URL")
    futures_url: str = Field(default="https://fapi.binance.com/fapi/v1", alias="BINANCE_FUTURES_URL")
    api_key: Optional[str] = Field(default=None, alias="BINANCE_API_KEY")
    api_secret: Optional[str] = Field(default=None, alias="BINANCE_API_SECRET")
    
    @property
    def is_authenticated(self) -> bool:
        """Check if credentials are provided."""
        return bool(self.api_key and self.api_secret)
    
    class Config:
        env_file = ".env"
        extra = "ignore"


class CoinGeckoSettings(BaseSettings):
    """CoinGecko API configuration."""
    
    api_url: str = Field(default="https://api.coingecko.com/api/v3", alias="COINGECKO_API_URL")
    api_key: Optional[str] = Field(default=None, alias="COINGECKO_API_KEY")
    
    @property
    def is_pro(self) -> bool:
        """Check if using Pro API."""
        return bool(self.api_key)
    
    class Config:
        env_file = ".env"
        extra = "ignore"


class CollectorSettings(BaseSettings):
    """Data collection settings."""
    
    history_years: int = Field(default=2, alias="HISTORY_YEARS")
    request_delay_ms: int = Field(default=100, alias="REQUEST_DELAY_MS")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")
    db_batch_size: int = Field(default=1000, alias="DB_BATCH_SIZE")
    
    class Config:
        env_file = ".env"
        extra = "ignore"


class LoggingSettings(BaseSettings):
    """Logging configuration."""
    
    level: str = Field(default="INFO", alias="LOG_LEVEL")
    file: str = Field(default="logs/collector.log", alias="LOG_FILE")
    rotation: str = Field(default="10 MB", alias="LOG_ROTATION")
    retention: str = Field(default="30 days", alias="LOG_RETENTION")
    
    class Config:
        env_file = ".env"
        extra = "ignore"


class SchedulerSettings(BaseSettings):
    """Scheduler configuration."""
    
    daily_update_hour: int = Field(default=1, alias="DAILY_UPDATE_HOUR")
    daily_update_minute: int = Field(default=0, alias="DAILY_UPDATE_MINUTE")
    
    class Config:
        env_file = ".env"
        extra = "ignore"


class Settings:
    """Main settings container."""
    
    def __init__(self):
        self.database = DatabaseSettings()
        self.deribit = DeribitSettings()
        self.binance = BinanceSettings()
        self.coingecko = CoinGeckoSettings()
        self.collector = CollectorSettings()
        self.logging = LoggingSettings()
        self.scheduler = SchedulerSettings()
        
        # Project paths
        self.project_root = Path(__file__).parent.parent
        self.logs_dir = self.project_root / "logs"
        self.data_dir = self.project_root / "data"
        
        # Create directories if they don't exist
        self.logs_dir.mkdir(exist_ok=True)
        self.data_dir.mkdir(exist_ok=True)


# Singleton instance
settings = Settings()

