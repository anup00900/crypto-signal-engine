"""
Deribit instrument information fetcher.
"""

from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from loguru import logger

from collectors.deribit.client import DeribitClient, DeribitAPIError


class DeribitInstrumentFetcher:
    """
    Fetches and manages instrument information from Deribit.
    
    Usage:
        fetcher = DeribitInstrumentFetcher()
        
        # Get all perpetual instruments
        perpetuals = fetcher.get_perpetual_instruments()
        
        # Get instruments for a specific currency
        btc_instruments = fetcher.get_instruments_by_currency("BTC")
        
        # Get instrument details
        details = fetcher.get_instrument_details("BTC-PERPETUAL")
    """
    
    # Supported base currencies
    SUPPORTED_CURRENCIES = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "MATIC"]
    
    def __init__(self, client: Optional[DeribitClient] = None):
        """
        Initialize instrument fetcher.
        
        Args:
            client: Deribit client instance
        """
        self.client = client or DeribitClient()
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 3600  # 1 hour cache
    
    def _is_cache_valid(self) -> bool:
        """Check if cache is still valid."""
        if not self._cache or not self._cache_time:
            return False
        
        age = (datetime.now(timezone.utc) - self._cache_time).total_seconds()
        return age < self._cache_ttl_seconds
    
    def _refresh_cache(self):
        """Refresh the instrument cache."""
        self._cache.clear()
        
        for currency in self.SUPPORTED_CURRENCIES:
            try:
                # Get all instrument types
                for kind in ["future", "spot"]:
                    instruments = self.client.get_instruments(
                        currency=currency,
                        kind=kind,
                        expired=False
                    )
                    
                    for inst in instruments:
                        name = inst.get("instrument_name")
                        self._cache[name] = inst
                        
            except DeribitAPIError as e:
                logger.warning(f"Failed to fetch {currency} instruments: {e}")
        
        self._cache_time = datetime.now(timezone.utc)
        logger.info(f"Refreshed instrument cache: {len(self._cache)} instruments")
    
    def get_all_instruments(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """
        Get all available instruments.
        
        Args:
            force_refresh: Force cache refresh
            
        Returns:
            Dictionary mapping instrument name to details
        """
        if force_refresh or not self._is_cache_valid():
            self._refresh_cache()
        
        return self._cache.copy()
    
    def get_instrument_details(self, instrument: str) -> Optional[Dict[str, Any]]:
        """
        Get details for a specific instrument.
        
        Args:
            instrument: Instrument name
            
        Returns:
            Instrument details or None
        """
        if not self._is_cache_valid():
            self._refresh_cache()
        
        return self._cache.get(instrument)
    
    def get_perpetual_instruments(self) -> List[Dict[str, Any]]:
        """
        Get all perpetual contract instruments.
        
        Returns:
            List of perpetual instrument details
        """
        if not self._is_cache_valid():
            self._refresh_cache()
        
        perpetuals = []
        for name, details in self._cache.items():
            if details.get("settlement_period") == "perpetual":
                perpetuals.append(details)
        
        return perpetuals
    
    def get_perpetual_names(self) -> List[str]:
        """
        Get names of all perpetual instruments.
        
        Returns:
            List of perpetual instrument names
        """
        return [inst["instrument_name"] for inst in self.get_perpetual_instruments()]
    
    def get_instruments_by_currency(
        self,
        currency: str,
        kind: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get instruments for a specific currency.
        
        Args:
            currency: Base currency (BTC, ETH, etc.)
            kind: Optional filter by kind (future, spot, option)
            
        Returns:
            List of matching instruments
        """
        if not self._is_cache_valid():
            self._refresh_cache()
        
        instruments = []
        for name, details in self._cache.items():
            if details.get("base_currency") == currency:
                if kind is None or details.get("kind") == kind:
                    instruments.append(details)
        
        return instruments
    
    def get_top_10_perpetuals(self) -> List[Dict[str, Any]]:
        """
        Get the top 10 perpetual instruments (by our predefined list).
        
        Returns:
            List of top 10 perpetual instrument details
        """
        perpetuals = self.get_perpetual_instruments()
        
        # Filter to our top 10 currencies
        top_10 = []
        for currency in self.SUPPORTED_CURRENCIES:
            perpetual_name = f"{currency}-PERPETUAL"
            for inst in perpetuals:
                if inst["instrument_name"] == perpetual_name:
                    top_10.append(inst)
                    break
        
        return top_10
    
    def format_instrument_info(self, instrument: str) -> str:
        """
        Format instrument information for display.
        
        Args:
            instrument: Instrument name
            
        Returns:
            Formatted string
        """
        details = self.get_instrument_details(instrument)
        
        if not details:
            return f"Instrument not found: {instrument}"
        
        lines = [
            f"Instrument: {details.get('instrument_name')}",
            f"  Type: {details.get('kind')}",
            f"  Base Currency: {details.get('base_currency')}",
            f"  Quote Currency: {details.get('quote_currency')}",
            f"  Contract Size: {details.get('contract_size')}",
            f"  Tick Size: {details.get('tick_size')}",
            f"  Min Trade Amount: {details.get('min_trade_amount')}",
            f"  Settlement Period: {details.get('settlement_period')}",
            f"  Is Active: {details.get('is_active')}"
        ]
        
        return "\n".join(lines)
    
    def to_database_format(self, instrument: str) -> Optional[Dict[str, Any]]:
        """
        Convert instrument to database storage format.
        
        Args:
            instrument: Instrument name
            
        Returns:
            Dictionary for database insertion
        """
        details = self.get_instrument_details(instrument)
        
        if not details:
            return None
        
        return {
            "symbol": details.get("base_currency"),
            "name": details.get("instrument_name"),
            "exchange": "deribit",
            "instrument_name": details.get("instrument_name"),
            "instrument_type": details.get("settlement_period", details.get("kind")),
            "base_currency": details.get("base_currency"),
            "quote_currency": details.get("quote_currency"),
            "contract_size": details.get("contract_size"),
            "tick_size": details.get("tick_size"),
            "min_trade_amount": details.get("min_trade_amount"),
            "is_active": details.get("is_active", True),
            "metadata": {
                "maker_commission": details.get("maker_commission"),
                "taker_commission": details.get("taker_commission"),
                "block_trade_commission": details.get("block_trade_commission"),
                "creation_timestamp": details.get("creation_timestamp")
            }
        }


