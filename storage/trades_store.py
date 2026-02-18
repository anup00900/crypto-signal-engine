"""
Storage handler for trade data.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from decimal import Decimal

from loguru import logger
from sqlalchemy.dialects.postgresql import insert

from database.connection import get_session, get_connection
from database.models import Trade


class TradesStore:
    """
    Handles storage and retrieval of trade data.
    
    Usage:
        store = TradesStore()
        
        # Store trades
        store.store_trades(
            instrument="BTC-PERPETUAL",
            trades=trade_data,
            source="deribit"
        )
        
        # Retrieve trades
        trades = store.get_trades(
            instrument="BTC-PERPETUAL",
            start=start_time,
            end=end_time
        )
    """
    
    def __init__(self, batch_size: int = 5000):
        """
        Initialize trades store.
        
        Args:
            batch_size: Number of records to insert per batch
        """
        self.batch_size = batch_size
    
    def store_trades(
        self,
        instrument: str,
        trades: List[Dict[str, Any]],
        source: str = "deribit"
    ) -> int:
        """
        Store trades in the database.
        
        Uses upsert (insert or update) to handle duplicates.
        
        Args:
            instrument: Instrument name
            trades: List of trade dictionaries
            source: Data source
            
        Returns:
            Number of records stored
        """
        if not trades:
            return 0
        
        stored_count = 0
        
        with get_session("collector") as session:
            # Process in batches
            for i in range(0, len(trades), self.batch_size):
                batch = trades[i:i + self.batch_size]
                
                # Prepare records
                records = []
                for trade in batch:
                    timestamp = trade.get("timestamp")
                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    
                    record = {
                        "instrument": instrument,
                        "trade_id": str(trade.get("trade_id")),
                        "timestamp": timestamp,
                        "price": Decimal(str(trade.get("price", 0))),
                        "amount": Decimal(str(trade.get("amount", 0))),
                        "direction": trade.get("direction"),
                        "tick_direction": trade.get("tick_direction"),
                        "liquidation": trade.get("liquidation", False),
                        "source": source
                    }
                    records.append(record)
                
                # Upsert using PostgreSQL ON CONFLICT
                stmt = insert(Trade).values(records)
                stmt = stmt.on_conflict_do_update(
                    index_elements=['instrument', 'trade_id'],
                    set_={
                        'timestamp': stmt.excluded.timestamp,
                        'price': stmt.excluded.price,
                        'amount': stmt.excluded.amount,
                        'direction': stmt.excluded.direction,
                        'tick_direction': stmt.excluded.tick_direction,
                        'liquidation': stmt.excluded.liquidation,
                        'source': stmt.excluded.source,
                        'collected_at': datetime.now(timezone.utc)
                    }
                )
                
                session.execute(stmt)
                stored_count += len(batch)
        
        logger.info(f"Stored {stored_count} trades for {instrument}")
        return stored_count
    
    def get_trades(
        self,
        instrument: str,
        start: datetime,
        end: datetime,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve trades from the database.
        
        Args:
            instrument: Instrument name
            start: Start datetime
            end: End datetime
            limit: Maximum number of records
            
        Returns:
            List of trade dictionaries
        """
        query = """
        SELECT 
            trade_id, timestamp, price, amount, 
            direction, tick_direction, liquidation, source
        FROM crypto.trades
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
            
            columns = ['trade_id', 'timestamp', 'price', 'amount', 
                      'direction', 'tick_direction', 'liquidation', 'source']
            
            trades = []
            for row in cursor.fetchall():
                trade = dict(zip(columns, row))
                # Convert Decimal to float
                for key in ['price', 'amount']:
                    if trade[key] is not None:
                        trade[key] = float(trade[key])
                trades.append(trade)
            
            return trades
    
    def get_trade_count(
        self,
        instrument: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> int:
        """
        Get count of trades for an instrument.
        
        Args:
            instrument: Instrument name
            start: Optional start datetime
            end: Optional end datetime
            
        Returns:
            Number of trades
        """
        query = """
        SELECT COUNT(*) 
        FROM crypto.trades
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
    
    def get_latest_trade_timestamp(
        self,
        instrument: str
    ) -> Optional[datetime]:
        """
        Get the timestamp of the most recent trade.
        
        Args:
            instrument: Instrument name
            
        Returns:
            Latest timestamp or None
        """
        query = """
        SELECT MAX(timestamp) 
        FROM crypto.trades
        WHERE instrument = :instrument
        """
        
        with get_connection("analyst") as conn:
            cursor = conn.cursor()
            cursor.execute(query, {"instrument": instrument})
            result = cursor.fetchone()
            return result[0] if result and result[0] else None
    
    def delete_trades(
        self,
        instrument: str,
        start: datetime,
        end: datetime
    ) -> int:
        """
        Delete trades in a time range.
        
        Args:
            instrument: Instrument name
            start: Start datetime
            end: End datetime
            
        Returns:
            Number of deleted records
        """
        query = """
        DELETE FROM crypto.trades
        WHERE instrument = :instrument
          AND timestamp >= :start
          AND timestamp < :end
        """
        
        with get_connection("collector") as conn:
            cursor = conn.cursor()
            cursor.execute(query, {
                "instrument": instrument,
                "start": start,
                "end": end
            })
            deleted = cursor.rowcount
            conn.commit()
            
            logger.info(f"Deleted {deleted} trades for {instrument}")
            return deleted


