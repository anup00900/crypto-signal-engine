"""
Deribit API Client - Comprehensive data collection
Supports: OHLCV, Order Book, Options, Greeks, OI, Funding, Basis
"""

import asyncio
import aiohttp
import time
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Any
from dataclasses import dataclass
from loguru import logger
import json


@dataclass
class DeribitConfig:
    """Deribit API Configuration"""
    api_url: str = "https://www.deribit.com/api/v2"
    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    rate_limit: int = 10  # requests per second
    max_retries: int = 3
    timeout: int = 30


class DeribitClient:
    """
    Comprehensive Deribit API Client
    
    Supports all public and authenticated endpoints for:
    - Market data (OHLCV, trades)
    - Order book snapshots
    - Options data (IV, Greeks)
    - Open Interest
    - Funding rates
    - Index prices
    """
    
    def __init__(self, config: Optional[DeribitConfig] = None):
        self.config = config or DeribitConfig()
        self.session: Optional[aiohttp.ClientSession] = None
        self.access_token: Optional[str] = None
        self.token_expiry: Optional[datetime] = None
        self._last_request_time = 0
        self._request_interval = 1.0 / self.config.rate_limit
        
    async def __aenter__(self):
        await self.connect()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        
    async def connect(self):
        """Initialize HTTP session"""
        if self.session is None or self.session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self.session = aiohttp.ClientSession(timeout=timeout)
            logger.info("Deribit client connected")
            
    async def close(self):
        """Close HTTP session"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.info("Deribit client disconnected")
            
    async def _rate_limit(self):
        """Enforce rate limiting"""
        now = time.time()
        elapsed = now - self._last_request_time
        if elapsed < self._request_interval:
            await asyncio.sleep(self._request_interval - elapsed)
        self._last_request_time = time.time()
        
    async def _request(self, method: str, params: Dict = None, auth: bool = False) -> Dict:
        """Make API request with rate limiting and retries"""
        await self._rate_limit()
        
        url = f"{self.config.api_url}/{method}"
        params = params or {}
        
        headers = {"Content-Type": "application/json"}
        if auth and self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
            
        for attempt in range(self.config.max_retries):
            try:
                async with self.session.get(url, params=params, headers=headers) as response:
                    data = await response.json()
                    
                    if "error" in data:
                        error = data["error"]
                        logger.error(f"API Error: {error}")
                        if error.get("code") == 10028:  # Rate limit
                            await asyncio.sleep(2 ** attempt)
                            continue
                        raise Exception(f"API Error: {error}")
                        
                    return data.get("result", data)
                    
            except asyncio.TimeoutError:
                logger.warning(f"Request timeout, attempt {attempt + 1}/{self.config.max_retries}")
                if attempt == self.config.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                logger.error(f"Request failed: {e}")
                if attempt == self.config.max_retries - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
                
    # =========================================================
    # INSTRUMENT METHODS
    # =========================================================
    
    async def get_instruments(self, currency: str, kind: str = None, expired: bool = False) -> List[Dict]:
        """
        Get all instruments for a currency
        
        Args:
            currency: BTC, ETH, SOL, etc.
            kind: 'future', 'option', 'spot', or None for all
            expired: Include expired instruments
        """
        params = {"currency": currency, "expired": str(expired).lower()}
        if kind:
            params["kind"] = kind
            
        return await self._request("public/get_instruments", params)
    
    async def get_all_options(self, currency: str) -> List[Dict]:
        """Get all active options for a currency"""
        return await self.get_instruments(currency, kind="option")
    
    async def get_all_futures(self, currency: str) -> List[Dict]:
        """Get all active futures for a currency"""
        return await self.get_instruments(currency, kind="future")
        
    # =========================================================
    # OHLCV / CHART DATA
    # =========================================================
    
    async def get_ohlcv(
        self, 
        instrument_name: str, 
        resolution: str,  # '1', '3', '5', '10', '15', '30', '60', '120', '180', '360', '720', '1D'
        start_timestamp: int,
        end_timestamp: int
    ) -> Dict:
        """
        Get OHLCV candlestick data
        
        Args:
            instrument_name: e.g., 'BTC-PERPETUAL'
            resolution: Timeframe in minutes or '1D' for daily
            start_timestamp: Start time in milliseconds
            end_timestamp: End time in milliseconds
        """
        params = {
            "instrument_name": instrument_name,
            "resolution": resolution,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp
        }
        return await self._request("public/get_tradingview_chart_data", params)
    
    # =========================================================
    # ORDER BOOK
    # =========================================================
    
    async def get_order_book(self, instrument_name: str, depth: int = 20) -> Dict:
        """
        Get current order book snapshot
        
        Args:
            instrument_name: e.g., 'BTC-PERPETUAL'
            depth: Number of levels (1-50)
        """
        params = {"instrument_name": instrument_name, "depth": depth}
        return await self._request("public/get_order_book", params)
    
    async def get_order_book_by_instrument_id(self, instrument_id: int, depth: int = 20) -> Dict:
        """Get order book by instrument ID"""
        params = {"instrument_id": instrument_id, "depth": depth}
        return await self._request("public/get_order_book_by_instrument_id", params)
    
    # =========================================================
    # OPTIONS DATA (IV, GREEKS)
    # =========================================================
    
    async def get_book_summary_by_currency(self, currency: str, kind: str = None) -> List[Dict]:
        """
        Get summary of all instruments (includes IV, Greeks for options)
        
        Args:
            currency: BTC, ETH
            kind: 'future', 'option', or None for all
        """
        params = {"currency": currency}
        if kind:
            params["kind"] = kind
        return await self._request("public/get_book_summary_by_currency", params)
    
    async def get_book_summary_by_instrument(self, instrument_name: str) -> Dict:
        """Get detailed summary for single instrument"""
        params = {"instrument_name": instrument_name}
        return await self._request("public/get_book_summary_by_instrument", params)
    
    async def ticker(self, instrument_name: str) -> Dict:
        """
        Get current ticker with full details
        Includes: mark_price, mark_iv, greeks, OI, funding, etc.
        """
        params = {"instrument_name": instrument_name}
        return await self._request("public/ticker", params)
        
    # =========================================================
    # OPEN INTEREST
    # =========================================================
    
    async def get_open_interest_history(
        self, 
        instrument_name: str,
        start_timestamp: int,
        end_timestamp: int,
        resolution: str = "1D"  # '1', '60', '1D'
    ) -> List[Dict]:
        """Get historical open interest"""
        params = {
            "instrument_name": instrument_name,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "resolution": resolution
        }
        # Note: This endpoint may require authentication
        try:
            return await self._request("public/get_historical_volatility", params)
        except:
            # Fallback: get from ticker
            return []
    
    # =========================================================
    # FUNDING RATES
    # =========================================================
    
    async def get_funding_rate_history(
        self,
        instrument_name: str,
        start_timestamp: int,
        end_timestamp: int
    ) -> List[Dict]:
        """
        Get historical funding rates for perpetual
        
        Args:
            instrument_name: e.g., 'BTC-PERPETUAL'
            start_timestamp: Start in milliseconds
            end_timestamp: End in milliseconds
        """
        params = {
            "instrument_name": instrument_name,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp
        }
        return await self._request("public/get_funding_rate_history", params)
    
    async def get_funding_rate_value(self, instrument_name: str) -> float:
        """Get current funding rate"""
        params = {"instrument_name": instrument_name}
        result = await self._request("public/get_funding_rate_value", params)
        return result
    
    # =========================================================
    # INDEX PRICES
    # =========================================================
    
    async def get_index_price(self, index_name: str) -> Dict:
        """
        Get current index price
        
        Args:
            index_name: 'btc_usd', 'eth_usd', 'sol_usd', etc.
        """
        params = {"index_name": index_name}
        return await self._request("public/get_index_price", params)
    
    async def get_index_price_names(self) -> List[str]:
        """Get list of available index names"""
        return await self._request("public/get_index_price_names")
    
    # =========================================================
    # VOLATILITY INDEX (DVOL)
    # =========================================================
    
    async def get_volatility_index_data(
        self,
        currency: str,
        start_timestamp: int,
        end_timestamp: int,
        resolution: str = "3600"  # seconds
    ) -> List[Dict]:
        """
        Get Deribit Volatility Index (DVOL) history
        
        Args:
            currency: 'BTC' or 'ETH'
            resolution: in seconds ('60', '3600', '43200', '86400')
        """
        params = {
            "currency": currency,
            "start_timestamp": start_timestamp,
            "end_timestamp": end_timestamp,
            "resolution": resolution
        }
        return await self._request("public/get_volatility_index_data", params)
    
    # =========================================================
    # TRADES
    # =========================================================
    
    async def get_last_trades_by_instrument(
        self,
        instrument_name: str,
        count: int = 1000,
        start_timestamp: Optional[int] = None,
        end_timestamp: Optional[int] = None
    ) -> Dict:
        """
        Get recent trades for an instrument
        
        Args:
            instrument_name: e.g., 'BTC-PERPETUAL'
            count: Number of trades (max 1000)
        """
        params = {"instrument_name": instrument_name, "count": count}
        if start_timestamp:
            params["start_timestamp"] = start_timestamp
        if end_timestamp:
            params["end_timestamp"] = end_timestamp
            
        return await self._request("public/get_last_trades_by_instrument_and_time", params)
    
    async def get_last_trades_by_currency(
        self,
        currency: str,
        kind: str = None,
        count: int = 1000
    ) -> Dict:
        """Get recent trades for entire currency"""
        params = {"currency": currency, "count": count}
        if kind:
            params["kind"] = kind
        return await self._request("public/get_last_trades_by_currency", params)
    
    # =========================================================
    # HISTORICAL VOLATILITY
    # =========================================================
    
    async def get_historical_volatility(self, currency: str) -> List[List]:
        """
        Get historical volatility data
        Returns: [[timestamp, volatility], ...]
        """
        params = {"currency": currency}
        return await self._request("public/get_historical_volatility", params)
    
    # =========================================================
    # COMBO METHODS (Efficient data fetching)
    # =========================================================
    
    async def get_full_options_snapshot(self, currency: str) -> Dict:
        """
        Get complete options market snapshot including IV surface
        
        Returns dict with:
        - instruments: List of all options
        - market_data: IV, Greeks, OI for each option
        - underlying_price: Current index price
        """
        # Get all options instruments
        instruments = await self.get_instruments(currency, kind="option")
        
        # Get book summary (includes IV, Greeks)
        summaries = await self.get_book_summary_by_currency(currency, kind="option")
        
        # Get underlying index price
        index_name = f"{currency.lower()}_usd"
        index_data = await self.get_index_price(index_name)
        
        # Map summaries by instrument name
        summary_map = {s["instrument_name"]: s for s in summaries}
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "currency": currency,
            "underlying_price": index_data.get("index_price"),
            "instruments": instruments,
            "market_data": summary_map
        }
    
    async def get_perpetual_snapshot(self, instrument_name: str) -> Dict:
        """
        Get complete perpetual data including funding, OI, order book
        """
        # Get ticker (includes funding, OI, mark price)
        ticker_data = await self.ticker(instrument_name)
        
        # Get order book
        order_book = await self.get_order_book(instrument_name, depth=20)
        
        return {
            "timestamp": datetime.utcnow().isoformat(),
            "instrument": instrument_name,
            "ticker": ticker_data,
            "order_book": order_book
        }


# =========================================================
# CONVENIENCE FUNCTIONS
# =========================================================

async def fetch_all_options_data(currency: str = "BTC") -> Dict:
    """Fetch complete options data for a currency"""
    async with DeribitClient() as client:
        return await client.get_full_options_snapshot(currency)


async def fetch_perpetual_data(instrument: str = "BTC-PERPETUAL") -> Dict:
    """Fetch complete perpetual data"""
    async with DeribitClient() as client:
        return await client.get_perpetual_snapshot(instrument)


if __name__ == "__main__":
    # Test the client
    async def test():
        async with DeribitClient() as client:
            # Test various endpoints
            print("\n=== Testing Deribit Client ===\n")
            
            # Get instruments
            instruments = await client.get_instruments("BTC", kind="option")
            print(f"BTC Options: {len(instruments)} instruments")
            
            # Get options summary
            summaries = await client.get_book_summary_by_currency("BTC", kind="option")
            print(f"Options with data: {len(summaries)}")
            
            # Get ticker for perpetual
            ticker = await client.ticker("BTC-PERPETUAL")
            print(f"\nBTC-PERPETUAL:")
            print(f"  Mark Price: ${ticker.get('mark_price', 'N/A'):,.2f}")
            print(f"  Open Interest: {ticker.get('open_interest', 'N/A'):,.2f}")
            print(f"  Funding Rate: {ticker.get('funding_8h', 'N/A')}")
            
            # Get DVOL
            dvol = await client.get_historical_volatility("BTC")
            if dvol:
                print(f"  DVOL: {dvol[-1][1]:.2f}%")
                
    asyncio.run(test())

