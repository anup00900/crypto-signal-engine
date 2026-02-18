"""
Deribit funding rate history collector.
"""

import time
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from loguru import logger

from collectors.base import (
    BaseFundingCollector,
    CollectionResult,
    CollectionStatus,
    FundingRate,
    OHLCVCandle
)
from collectors.deribit.client import DeribitClient, DeribitAPIError
from utils.time_utils import to_unix_ms, from_unix_ms
from utils.logger import log_collection_start, log_collection_complete, log_collection_error


class DeribitFundingCollector(BaseFundingCollector):
    """
    Collector for Deribit perpetual funding rate history.
    
    Funding rates are applied every 8 hours on Deribit perpetual contracts.
    
    Usage:
        collector = DeribitFundingCollector()
        
        result = collector.collect_funding_rates(
            instrument="BTC-PERPETUAL",
            start=datetime(2024, 1, 1),
            end=datetime(2024, 1, 31)
        )
        
        if result.is_success:
            for rate in result.data:
                print(f"{rate['timestamp']}: {rate['funding_rate']}")
    """
    
    def __init__(self, client: Optional[DeribitClient] = None):
        """
        Initialize funding collector.
        
        Args:
            client: Deribit client instance
        """
        super().__init__(source="deribit")
        self.client = client or DeribitClient()
        self._instruments_cache: Optional[List[str]] = None
    
    def get_available_instruments(self) -> List[str]:
        """Get list of available perpetual instruments."""
        if self._instruments_cache is None:
            self._instruments_cache = []
            for currency in ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK", "DOT", "MATIC"]:
                try:
                    instruments = self.client.get_instruments(currency=currency, kind="future")
                    for inst in instruments:
                        if inst.get("settlement_period") == "perpetual":
                            self._instruments_cache.append(inst["instrument_name"])
                except DeribitAPIError as e:
                    logger.warning(f"Failed to get instruments for {currency}: {e}")
        return self._instruments_cache
    
    def collect_ohlcv(
        self,
        instrument: str,
        timeframe: str,
        start: datetime,
        end: datetime
    ) -> CollectionResult:
        """Not implemented - use DeribitOHLCVCollector for OHLCV data."""
        raise NotImplementedError("Use DeribitOHLCVCollector for OHLCV data")
    
    def collect_funding_rates(
        self,
        instrument: str,
        start: datetime,
        end: datetime
    ) -> CollectionResult:
        """
        Collect funding rate history for a perpetual instrument.
        
        Args:
            instrument: Perpetual instrument name (e.g., "BTC-PERPETUAL")
            start: Start datetime
            end: End datetime
            
        Returns:
            CollectionResult with funding rate data
        """
        start_time = time.time()
        
        log_collection_start(self.source, instrument, "funding", start, end)
        
        # Validate instrument is a perpetual
        if "PERPETUAL" not in instrument.upper():
            return CollectionResult(
                status=CollectionStatus.FAILED,
                instrument=instrument,
                data_type="funding",
                source=self.source,
                start_time=start,
                end_time=end,
                records_collected=0,
                duration_seconds=time.time() - start_time,
                error_message=f"{instrument} is not a perpetual contract"
            )
        
        try:
            start_ms = to_unix_ms(start)
            end_ms = to_unix_ms(end)
            
            result = self.client.get_funding_rate_history(
                instrument=instrument,
                start_timestamp=start_ms,
                end_timestamp=end_ms
            )
            
            # Parse funding rates
            funding_rates = []
            
            for item in result:
                funding_rate = FundingRate(
                    timestamp=from_unix_ms(item.get("timestamp")),
                    funding_rate=item.get("interest_8h"),
                    mark_price=item.get("prev_index_price"),
                    index_price=item.get("index_price")
                )
                funding_rates.append(funding_rate.to_dict())
            
            # Sort by timestamp
            funding_rates.sort(key=lambda x: x["timestamp"])
            
            duration = time.time() - start_time
            log_collection_complete(self.source, instrument, "funding", len(funding_rates), duration)
            
            return CollectionResult(
                status=CollectionStatus.SUCCESS,
                instrument=instrument,
                data_type="funding",
                source=self.source,
                start_time=start,
                end_time=end,
                records_collected=len(funding_rates),
                duration_seconds=duration,
                data=funding_rates
            )
            
        except DeribitAPIError as e:
            duration = time.time() - start_time
            log_collection_error(self.source, instrument, e)
            
            return CollectionResult(
                status=CollectionStatus.FAILED,
                instrument=instrument,
                data_type="funding",
                source=self.source,
                start_time=start,
                end_time=end,
                records_collected=0,
                duration_seconds=duration,
                error_message=e.message
            )
    
    def get_current_funding_rate(self, instrument: str) -> Optional[Dict[str, Any]]:
        """
        Get the current funding rate for an instrument.
        
        Args:
            instrument: Perpetual instrument name
            
        Returns:
            Current funding rate info or None
        """
        try:
            ticker = self.client.get_ticker(instrument)
            
            return {
                "instrument": instrument,
                "timestamp": datetime.now(timezone.utc),
                "funding_rate": ticker.get("funding_8h"),
                "current_funding": ticker.get("current_funding"),
                "mark_price": ticker.get("mark_price"),
                "index_price": ticker.get("index_price")
            }
            
        except DeribitAPIError as e:
            logger.error(f"Failed to get current funding rate for {instrument}: {e}")
            return None
    
    def collect_all_perpetual_funding(
        self,
        start: datetime,
        end: datetime
    ) -> Dict[str, CollectionResult]:
        """
        Collect funding rates for all perpetual instruments.
        
        Args:
            start: Start datetime
            end: End datetime
            
        Returns:
            Dictionary mapping instrument to CollectionResult
        """
        results = {}
        instruments = self.get_available_instruments()
        
        for instrument in instruments:
            if "PERPETUAL" in instrument.upper():
                logger.info(f"Collecting funding rates for {instrument}")
                results[instrument] = self.collect_funding_rates(
                    instrument=instrument,
                    start=start,
                    end=end
                )
        
        return results


