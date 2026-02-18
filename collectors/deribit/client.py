"""
Deribit API client with rate limiting and error handling.
"""

import time
from typing import Optional, Dict, Any, List
from datetime import datetime

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger

from config.settings import settings
from utils.rate_limiter import RateLimiter, ExchangeRateLimiters


class DeribitAPIError(Exception):
    """Deribit API error."""
    
    def __init__(self, message: str, code: Optional[int] = None, data: Optional[dict] = None):
        self.message = message
        self.code = code
        self.data = data
        super().__init__(f"DeribitAPIError({code}): {message}")


class DeribitClient:
    """
    Deribit API client with automatic rate limiting and retry logic.
    
    Usage:
        client = DeribitClient()
        
        # Get instruments
        instruments = client.get_instruments(currency="BTC", kind="future")
        
        # Get OHLCV data
        candles = client.get_tradingview_chart_data(
            instrument="BTC-PERPETUAL",
            resolution="60",
            start_timestamp=1609459200000,
            end_timestamp=1609545600000
        )
        
        # Get trades
        trades = client.get_last_trades_by_instrument_and_time(
            instrument="BTC-PERPETUAL",
            start_timestamp=1609459200000,
            end_timestamp=1609545600000
        )
    """
    
    def __init__(
        self,
        use_testnet: bool = False,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        rate_limiter: Optional[RateLimiter] = None
    ):
        """
        Initialize Deribit client.
        
        Args:
            use_testnet: Use testnet instead of mainnet
            client_id: Deribit API client ID for authentication
            client_secret: Deribit API client secret
            rate_limiter: Custom rate limiter (uses default if None)
        """
        # Configuration
        self.use_testnet = use_testnet or settings.deribit.use_testnet
        self.base_url = settings.deribit.test_api_url if self.use_testnet else settings.deribit.api_url
        
        # Authentication
        self.client_id = client_id or settings.deribit.client_id
        self.client_secret = client_secret or settings.deribit.client_secret
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        
        # Rate limiting
        if rate_limiter:
            self.rate_limiter = rate_limiter
        elif self.is_authenticated:
            self.rate_limiter = ExchangeRateLimiters.deribit_authenticated()
        else:
            self.rate_limiter = ExchangeRateLimiters.deribit_public()
        
        # HTTP session with retry logic
        self.session = self._create_session()
        
        logger.info(f"DeribitClient initialized (testnet={self.use_testnet}, auth={self.is_authenticated})")
    
    @property
    def is_authenticated(self) -> bool:
        """Check if client has authentication credentials."""
        return bool(self.client_id and self.client_secret)
    
    def _create_session(self) -> requests.Session:
        """Create HTTP session with retry strategy."""
        session = requests.Session()
        
        # Retry strategy for transient errors
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        
        # Default headers
        session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json"
        })
        
        return session
    
    def _make_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        require_auth: bool = False
    ) -> Dict[str, Any]:
        """
        Make an API request with rate limiting and error handling.
        
        Args:
            method: API method (e.g., "public/get_instruments")
            params: Request parameters
            require_auth: Whether authentication is required
            
        Returns:
            API response result
            
        Raises:
            DeribitAPIError: If API returns an error
        """
        # Rate limiting
        self.rate_limiter.wait()
        
        # Build request
        url = f"{self.base_url}/{method}"
        
        # Add authentication if required and available
        if require_auth and self.is_authenticated:
            self._ensure_authenticated()
            params = params or {}
            params["access_token"] = self._access_token
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            
            # Check for API error
            if "error" in data:
                error = data["error"]
                raise DeribitAPIError(
                    message=error.get("message", "Unknown error"),
                    code=error.get("code"),
                    data=error.get("data")
                )
            
            return data.get("result", data)
            
        except requests.exceptions.Timeout:
            logger.error(f"Request timeout: {method}")
            raise DeribitAPIError("Request timeout", code=-1)
        except requests.exceptions.RequestException as e:
            logger.error(f"Request error: {method} - {e}")
            raise DeribitAPIError(str(e), code=-1)
    
    def _ensure_authenticated(self):
        """Ensure we have a valid access token."""
        if not self.is_authenticated:
            raise DeribitAPIError("Authentication required but no credentials provided")
        
        # Check if token is still valid
        if self._access_token and self._token_expiry:
            if datetime.now() < self._token_expiry:
                return
        
        # Get new token
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate and get access token."""
        params = {
            "grant_type": "client_credentials",
            "client_id": self.client_id,
            "client_secret": self.client_secret
        }
        
        result = self._make_request("public/auth", params=params)
        
        self._access_token = result.get("access_token")
        expires_in = result.get("expires_in", 900)
        self._token_expiry = datetime.now() + timedelta(seconds=expires_in - 60)
        
        logger.info("Deribit authentication successful")
    
    # ===== PUBLIC API METHODS =====
    
    def get_instruments(
        self,
        currency: str = "BTC",
        kind: Optional[str] = None,
        expired: bool = False
    ) -> List[Dict[str, Any]]:
        """
        Get available instruments.
        
        Args:
            currency: Base currency (BTC, ETH, SOL, etc.)
            kind: Instrument type (future, option, spot, future_combo, option_combo)
            expired: Include expired instruments
            
        Returns:
            List of instrument details
        """
        params = {
            "currency": currency,
            "expired": str(expired).lower()
        }
        if kind:
            params["kind"] = kind
        
        return self._make_request("public/get_instruments", params=params)
    
    def get_tradingview_chart_data(
        self,
        instrument: str,
        resolution: str,
        start_timestamp: int,
        end_timestamp: int
    ) -> Dict[str, Any]:
        """
        Get OHLCV candlestick data.
        
        Args:
            instrument: Instrument name (e.g., "BTC-PERPETUAL")
            resolution: Candle resolution (1, 3, 5, 10, 15, 30, 60, 120, 180, 360, 720, 1D)
            start_timestamp: Start time in Unix milliseconds
            end_timestamp: End time in Unix milliseconds
            
        Returns:
            Dictionary with ticks (timestamps), open, high, low, close, volume arrays
        """
        params = {
            "instrument_name": instrument,
            "resolution": resolution,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp
        }
        
        return self._make_request("public/get_tradingview_chart_data", params=params)
    
    def get_last_trades_by_instrument_and_time(
        self,
        instrument: str,
        start_timestamp: int,
        end_timestamp: int,
        count: int = 1000,
        sorting: str = "asc"
    ) -> Dict[str, Any]:
        """
        Get trade history for an instrument.
        
        Args:
            instrument: Instrument name
            start_timestamp: Start time in Unix milliseconds
            end_timestamp: End time in Unix milliseconds
            count: Maximum number of trades to return (max 1000)
            sorting: Sort order ("asc" or "desc")
            
        Returns:
            Dictionary with trades and has_more flag
        """
        params = {
            "instrument_name": instrument,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "count": min(count, 1000),
            "sorting": sorting
        }
        
        return self._make_request("public/get_last_trades_by_instrument_and_time", params=params)
    
    def get_funding_rate_history(
        self,
        instrument: str,
        start_timestamp: int,
        end_timestamp: int
    ) -> List[Dict[str, Any]]:
        """
        Get funding rate history for perpetual contracts.
        
        Args:
            instrument: Perpetual instrument name
            start_timestamp: Start time in Unix milliseconds
            end_timestamp: End time in Unix milliseconds
            
        Returns:
            List of funding rate records
        """
        params = {
            "instrument_name": instrument,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp
        }
        
        return self._make_request("public/get_funding_rate_history", params=params)
    
    def get_ticker(self, instrument: str) -> Dict[str, Any]:
        """
        Get current ticker data for an instrument.
        
        Args:
            instrument: Instrument name
            
        Returns:
            Ticker data including best bid/ask, last price, volume, etc.
        """
        params = {"instrument_name": instrument}
        return self._make_request("public/ticker", params=params)
    
    def get_book_summary_by_instrument(self, instrument: str) -> Dict[str, Any]:
        """
        Get order book summary for an instrument.
        
        Args:
            instrument: Instrument name
            
        Returns:
            Order book summary with bid/ask prices and sizes
        """
        params = {"instrument_name": instrument}
        return self._make_request("public/get_book_summary_by_instrument", params=params)
    
    def get_index_price(self, index_name: str) -> Dict[str, Any]:
        """
        Get current index price.
        
        Args:
            index_name: Index name (e.g., "btc_usd")
            
        Returns:
            Index price data
        """
        params = {"index_name": index_name}
        return self._make_request("public/get_index_price", params=params)
    
    def test_connection(self) -> bool:
        """
        Test API connection.
        
        Returns:
            True if connection successful
        """
        try:
            result = self._make_request("public/test")
            return result.get("version") is not None
        except Exception as e:
            logger.error(f"Connection test failed: {e}")
            return False
    
    def get_rate_limiter_stats(self) -> dict:
        """Get rate limiter statistics."""
        return self.rate_limiter.get_stats()


# Convenience function
def create_deribit_client(
    testnet: bool = False,
    authenticated: bool = False
) -> DeribitClient:
    """
    Create a Deribit client with default settings.
    
    Args:
        testnet: Use testnet
        authenticated: Use authentication if credentials available
        
    Returns:
        Configured DeribitClient instance
    """
    if authenticated and settings.deribit.is_authenticated:
        return DeribitClient(
            use_testnet=testnet,
            client_id=settings.deribit.client_id,
            client_secret=settings.deribit.client_secret
        )
    return DeribitClient(use_testnet=testnet)


# Import timedelta for authentication
from datetime import timedelta


