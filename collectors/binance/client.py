"""
Binance API client with rate limiting and error handling.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from loguru import logger

from config.settings import settings
from utils.rate_limiter import RateLimiter, ExchangeRateLimiters


class BinanceAPIError(Exception):
    """Binance API error."""
    
    def __init__(self, message: str, code: Optional[int] = None):
        self.message = message
        self.code = code
        super().__init__(f"BinanceAPIError({code}): {message}")


class BinanceClient:
    """
    Binance API client with automatic rate limiting.
    
    Usage:
        client = BinanceClient()
        
        # Get OHLCV data
        candles = client.get_klines(
            symbol="BTCUSDT",
            interval="1h",
            start_time=1609459200000,
            end_time=1609545600000
        )
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        rate_limiter: Optional[RateLimiter] = None
    ):
        """
        Initialize Binance client.
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            rate_limiter: Custom rate limiter
        """
        self.api_url = settings.binance.api_url
        self.futures_url = settings.binance.futures_url
        self.api_key = api_key or settings.binance.api_key
        self.api_secret = api_secret or settings.binance.api_secret
        
        self.rate_limiter = rate_limiter or ExchangeRateLimiters.binance()
        self.session = self._create_session()
        
        logger.info("BinanceClient initialized")
    
    @property
    def is_authenticated(self) -> bool:
        """Check if client has authentication credentials."""
        return bool(self.api_key and self.api_secret)
    
    def _create_session(self) -> requests.Session:
        """Create HTTP session with retry strategy."""
        session = requests.Session()
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        
        if self.api_key:
            session.headers["X-MBX-APIKEY"] = self.api_key
        
        return session
    
    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        use_futures: bool = False
    ) -> Any:
        """
        Make an API request with rate limiting.
        
        Args:
            endpoint: API endpoint
            params: Request parameters
            use_futures: Use futures API URL
            
        Returns:
            API response
        """
        self.rate_limiter.wait()
        
        base_url = self.futures_url if use_futures else self.api_url
        url = f"{base_url}/{endpoint}"
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            
            if response.status_code == 429:
                raise BinanceAPIError("Rate limit exceeded", 429)
            
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.Timeout:
            raise BinanceAPIError("Request timeout", -1)
        except requests.exceptions.RequestException as e:
            raise BinanceAPIError(str(e), -1)
    
    def get_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000
    ) -> List[List]:
        """
        Get candlestick/kline data.
        
        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
            interval: Kline interval (1m, 5m, 15m, 1h, 4h, 1d, etc.)
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
            limit: Number of candles (max 1000)
            
        Returns:
            List of kline data
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000)
        }
        
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        
        return self._make_request("klines", params)
    
    def get_futures_klines(
        self,
        symbol: str,
        interval: str,
        start_time: Optional[int] = None,
        end_time: Optional[int] = None,
        limit: int = 1000
    ) -> List[List]:
        """
        Get futures candlestick data.
        
        Args:
            symbol: Futures symbol (e.g., "BTCUSDT")
            interval: Kline interval
            start_time: Start time in milliseconds
            end_time: End time in milliseconds
            limit: Number of candles
            
        Returns:
            List of kline data
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1500)
        }
        
        if start_time:
            params["startTime"] = start_time
        if end_time:
            params["endTime"] = end_time
        
        return self._make_request("klines", params, use_futures=True)
    
    def get_exchange_info(self) -> Dict[str, Any]:
        """Get exchange trading rules and symbol information."""
        return self._make_request("exchangeInfo")
    
    def get_ticker_24h(self, symbol: Optional[str] = None) -> Any:
        """
        Get 24hr ticker price change statistics.
        
        Args:
            symbol: Trading pair (returns all if None)
            
        Returns:
            Ticker data
        """
        params = {}
        if symbol:
            params["symbol"] = symbol
        
        return self._make_request("ticker/24hr", params)
    
    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            self._make_request("ping")
            return True
        except Exception as e:
            logger.error(f"Binance connection test failed: {e}")
            return False


