"""
CoinGecko metadata collector for market cap and coin information.
"""

from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

import requests
from loguru import logger

from config.settings import settings
from config.instruments import TOP_10_INSTRUMENTS
from utils.rate_limiter import RateLimiter, ExchangeRateLimiters


class CoinGeckoAPIError(Exception):
    """CoinGecko API error."""
    pass


class CoinGeckoMetadataCollector:
    """
    Collector for CoinGecko market metadata.
    
    Usage:
        collector = CoinGeckoMetadataCollector()
        
        # Get market data for top 10 coins
        data = collector.get_market_data()
        
        # Get specific coin info
        btc_info = collector.get_coin_info("bitcoin")
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize CoinGecko collector.
        
        Args:
            api_key: CoinGecko API key (Pro tier)
        """
        self.api_url = settings.coingecko.api_url
        self.api_key = api_key or settings.coingecko.api_key
        
        if self.api_key:
            self.rate_limiter = ExchangeRateLimiters.coingecko_pro()
        else:
            self.rate_limiter = ExchangeRateLimiters.coingecko_free()
        
        self.session = requests.Session()
        if self.api_key:
            self.session.headers["x-cg-pro-api-key"] = self.api_key
    
    def _make_request(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Make an API request."""
        self.rate_limiter.wait()
        
        url = f"{self.api_url}/{endpoint}"
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            raise CoinGeckoAPIError(str(e))
    
    def get_market_data(
        self,
        coin_ids: Optional[List[str]] = None,
        vs_currency: str = "usd"
    ) -> List[Dict[str, Any]]:
        """
        Get market data for coins.
        
        Args:
            coin_ids: List of CoinGecko coin IDs (uses top 10 if None)
            vs_currency: Quote currency
            
        Returns:
            List of market data dictionaries
        """
        if coin_ids is None:
            coin_ids = [inst.coingecko_id for inst in TOP_10_INSTRUMENTS]
        
        params = {
            "ids": ",".join(coin_ids),
            "vs_currency": vs_currency,
            "order": "market_cap_desc",
            "sparkline": "false",
            "price_change_percentage": "24h,7d,30d"
        }
        
        return self._make_request("coins/markets", params)
    
    def get_coin_info(self, coin_id: str) -> Dict[str, Any]:
        """
        Get detailed information for a coin.
        
        Args:
            coin_id: CoinGecko coin ID
            
        Returns:
            Coin information dictionary
        """
        params = {
            "localization": "false",
            "tickers": "false",
            "market_data": "true",
            "community_data": "false",
            "developer_data": "false"
        }
        
        return self._make_request(f"coins/{coin_id}", params)
    
    def get_historical_market_data(
        self,
        coin_id: str,
        days: int = 30,
        vs_currency: str = "usd"
    ) -> Dict[str, Any]:
        """
        Get historical market data.
        
        Args:
            coin_id: CoinGecko coin ID
            days: Number of days
            vs_currency: Quote currency
            
        Returns:
            Historical price, market cap, and volume data
        """
        params = {
            "vs_currency": vs_currency,
            "days": days
        }
        
        return self._make_request(f"coins/{coin_id}/market_chart", params)
    
    def get_global_market_data(self) -> Dict[str, Any]:
        """
        Get global cryptocurrency market data.
        
        Returns:
            Global market statistics
        """
        data = self._make_request("global")
        return data.get("data", {})
    
    def test_connection(self) -> bool:
        """Test API connection."""
        try:
            self._make_request("ping")
            return True
        except Exception as e:
            logger.error(f"CoinGecko connection test failed: {e}")
            return False
    
    def get_top_10_summary(self) -> List[Dict[str, Any]]:
        """
        Get summary data for top 10 cryptocurrencies.
        
        Returns:
            List of coin summaries with key metrics
        """
        market_data = self.get_market_data()
        
        summaries = []
        for coin in market_data:
            summaries.append({
                "symbol": coin.get("symbol", "").upper(),
                "name": coin.get("name"),
                "coingecko_id": coin.get("id"),
                "current_price": coin.get("current_price"),
                "market_cap": coin.get("market_cap"),
                "market_cap_rank": coin.get("market_cap_rank"),
                "total_volume": coin.get("total_volume"),
                "price_change_24h_pct": coin.get("price_change_percentage_24h"),
                "price_change_7d_pct": coin.get("price_change_percentage_7d_in_currency"),
                "ath": coin.get("ath"),
                "ath_date": coin.get("ath_date"),
                "circulating_supply": coin.get("circulating_supply"),
                "max_supply": coin.get("max_supply"),
                "last_updated": coin.get("last_updated")
            })
        
        return summaries


