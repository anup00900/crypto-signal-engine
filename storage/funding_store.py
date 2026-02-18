"""
Storage handler for funding rate data.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from decimal import Decimal

from loguru import logger
from sqlalchemy.dialects.postgresql import insert

from database.connection import get_session, get_connection
from database.models import FundingRate


class FundingStore:
    """
    Handles storage and retrieval of funding rate data.
    
    Usage:
        store = FundingStore()
        
        # Store funding rates
        store.store_funding_rates(
            instrument="BTC-PERPETUAL",
            rates=funding_data,
            source="deribit"
        )
        
        # Retrieve funding rates
        rates = store.get_funding_rates(
            instrument="BTC-PERPETUAL",
            start=start_time,
            end=end_time
        )
    """
    
    def __init__(self, batch_size: int = 1000):
        """
        Initialize funding store.
        
        Args:
            batch_size: Number of records to insert per batch
        """
        self.batch_size = batch_size
    
    def store_funding_rates(
        self,
        instrument: str,
        rates: List[Dict[str, Any]],
        source: str = "deribit"
    ) -> int:
        """
        Store funding rates in the database.
        
        Uses upsert (insert or update) to handle duplicates.
        
        Args:
            instrument: Instrument name
            rates: List of funding rate dictionaries
            source: Data source
            
        Returns:
            Number of records stored
        """
        if not rates:
            return 0
        
        stored_count = 0
        
        with get_session("collector") as session:
            for i in range(0, len(rates), self.batch_size):
                batch = rates[i:i + self.batch_size]
                
                records = []
                for rate in batch:
                    timestamp = rate.get("timestamp")
                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    
                    record = {
                        "instrument": instrument,
                        "timestamp": timestamp,
                        "funding_rate": Decimal(str(rate.get("funding_rate", 0))),
                        "mark_price": Decimal(str(rate.get("mark_price", 0))) if rate.get("mark_price") else None,
                        "index_price": Decimal(str(rate.get("index_price", 0))) if rate.get("index_price") else None,
                        "source": source
                    }
                    records.append(record)
                
                stmt = insert(FundingRate).values(records)
                stmt = stmt.on_conflict_do_update(
                    index_elements=['instrument', 'timestamp'],
                    set_={
                        'funding_rate': stmt.excluded.funding_rate,
                        'mark_price': stmt.excluded.mark_price,
                        'index_price': stmt.excluded.index_price,
                        'source': stmt.excluded.source,
                        'collected_at': datetime.now(timezone.utc)
                    }
                )
                
                session.execute(stmt)
                stored_count += len(batch)
        
        logger.info(f"Stored {stored_count} funding rates for {instrument}")
        return stored_count
    
    def get_funding_rates(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve funding rates from the database.
        
        Args:
            instrument: Instrument name
            start: Start datetime
            end: End datetime
            limit: Maximum number of records
            
        Returns:
            List of funding rate dictionaries
        """
        query = """
        SELECT 
            timestamp, funding_rate, mark_price, index_price, source
        FROM crypto.funding_rates
        WHERE instrument = :instrument
          AND timestamp >= :start
          AND timestamp < :end
        ORDER BY timestamp ASC
        """
        
        if limit:
            query += f" LIMIT {limit}"
        
        with get_connection("analyst") as conn:
            cursor = conn.cursor()
            cursor.execute(query, {
                "instrument": instrument,
                "start": start,
                "end": end
            })
            
            columns = ['timestamp', 'funding_rate', 'mark_price', 'index_price', 'source']
            
            rates = []
            for row in cursor.fetchall():
                rate = dict(zip(columns, row))
                for key in ['funding_rate', 'mark_price', 'index_price']:
                    if rate[key] is not None:
                        rate[key] = float(rate[key])
                rates.append(rate)
            
            return rates
    
    def get_latest_funding_timestamp(
        self,
        instrument: str
    ) -> Optional[datetime]:
        """
        Get the timestamp of the most recent funding rate.
        
        Args:
            instrument: Instrument name
            
        Returns:
            Latest timestamp or None
        """
        query = """
        SELECT MAX(timestamp) 
        FROM crypto.funding_rates
        WHERE instrument = :instrument
        """
        
        with get_connection("analyst") as conn:
            cursor = conn.cursor()
            cursor.execute(query, {"instrument": instrument})
            result = cursor.fetchone()
            return result[0] if result and result[0] else None
    
    def get_funding_rate_count(
        self,
        instrument: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> int:
        """
        Get count of funding rates for an instrument.
        
        Args:
            instrument: Instrument name
            start: Optional start datetime
            end: Optional end datetime
            
        Returns:
            Number of funding rates
        """
        query = """
        SELECT COUNT(*) 
        FROM crypto.funding_rates
        WHERE instrument = :instrument
        """
        
        params = {"instrument": instrument}
        
        if start:
            query += " AND timestamp >= :start"
            params["start"] = start
        if end:
            query += " AND timestamp < :end"
            params["end"] = end
        
        with get_connection("analyst") as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            result = cursor.fetchone()
            return result[0] if result else 0
    
    def get_average_funding_rate(
        self,
        instrument: str,
        start: datetime,
        end: datetime
    ) -> Optional[float]:
        """
        Get average funding rate for a period.
        
        Args:
            instrument: Instrument name
            start: Start datetime
            end: End datetime
            
        Returns:
            Average funding rate or None
        """
        query = """
        SELECT AVG(funding_rate) 
        FROM crypto.funding_rates
        WHERE instrument = :instrument
          AND timestamp >= :start
          AND timestamp < :end
        """
        
        with get_connection("analyst") as conn:
            cursor = conn.cursor()
            cursor.execute(query, {
                "instrument": instrument,
                "start": start,
                "end": end
            })
            result = cursor.fetchone()
            return float(result[0]) if result and result[0] else None


