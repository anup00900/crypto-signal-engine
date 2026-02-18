"""
Storage handler for OHLCV candlestick data.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from decimal import Decimal

from loguru import logger
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from database.connection import get_session, get_connection
from database.models import (
    OHLCV1s, OHLCV1m, OHLCV5m, OHLCV15m,
    OHLCV1h, OHLCV4h, OHLCV1d,
    get_ohlcv_model, CollectionLog
)


class OHLCVStore:
    """
    Handles storage and retrieval of OHLCV candlestick data.
    
    Usage:
        store = OHLCVStore()
        
        # Store candles
        store.store_candles(
            instrument="BTC-PERPETUAL",
            timeframe="1h",
            candles=candle_data,
            source="deribit"
        )
        
        # Retrieve candles
        candles = store.get_candles(
            instrument="BTC-PERPETUAL",
            timeframe="1h",
            start=start_time,
            end=end_time
        )
    """
    
    TIMEFRAME_TABLE_MAP = {
        "1s": "ohlcv_1s",
        "1m": "ohlcv_1m",
        "5m": "ohlcv_5m",
        "15m": "ohlcv_15m",
        "1h": "ohlcv_1h",
        "4h": "ohlcv_4h",
        "1d": "ohlcv_1d"
    }
    
    def __init__(self, batch_size: int = 1000):
        """
        Initialize OHLCV store.
        
        Args:
            batch_size: Number of records to insert per batch
        """
        self.batch_size = batch_size
    
    def store_candles(
        self,
        instrument: str,
        timeframe: str,
        candles: List[Dict[str, Any]],
        source: str = "deribit"
    ) -> int:
        """
        Store OHLCV candles in the database.
        
        Uses upsert (insert or update) to handle duplicates.
        
        Args:
            instrument: Instrument name
            timeframe: Timeframe string (1s, 1m, 5m, etc.)
            candles: List of candle dictionaries
            source: Data source
            
        Returns:
            Number of records stored
        """
        if not candles:
            return 0
        
        table_name = self.TIMEFRAME_TABLE_MAP.get(timeframe)
        if not table_name:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        
        model = get_ohlcv_model(timeframe)
        if not model:
            raise ValueError(f"No model for timeframe: {timeframe}")
        
        stored_count = 0
        
        with get_session("collector") as session:
            # Process in batches
            for i in range(0, len(candles), self.batch_size):
                batch = candles[i:i + self.batch_size]
                
                # Prepare records
                records = []
                for candle in batch:
                    timestamp = candle.get("timestamp")
                    if isinstance(timestamp, str):
                        timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                    
                    record = {
                        "instrument": instrument,
                        "timestamp": timestamp,
                        "open": Decimal(str(candle.get("open", 0))),
                        "high": Decimal(str(candle.get("high", 0))),
                        "low": Decimal(str(candle.get("low", 0))),
                        "close": Decimal(str(candle.get("close", 0))),
                        "volume": Decimal(str(candle.get("volume", 0))),
                        "volume_usd": Decimal(str(candle.get("volume_usd", 0))) if candle.get("volume_usd") else None,
                        "trades_count": candle.get("trades_count"),
                        "source": source
                    }
                    records.append(record)
                
                # Upsert using PostgreSQL ON CONFLICT
                stmt = insert(model).values(records)
                stmt = stmt.on_conflict_do_update(
                    index_elements=['instrument', 'timestamp'],
                    set_={
                        'open': stmt.excluded.open,
                        'high': stmt.excluded.high,
                        'low': stmt.excluded.low,
                        'close': stmt.excluded.close,
                        'volume': stmt.excluded.volume,
                        'volume_usd': stmt.excluded.volume_usd,
                        'trades_count': stmt.excluded.trades_count,
                        'source': stmt.excluded.source,
                        'collected_at': datetime.now(timezone.utc)
                    }
                )
                
                session.execute(stmt)
                stored_count += len(batch)
        
        logger.info(f"Stored {stored_count} {timeframe} candles for {instrument}")
        return stored_count
    
    def get_candles(
        self,
        instrument: str,
        timeframe: str,
        start: datetime,
        end: datetime,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve OHLCV candles from the database.
        
        Args:
            instrument: Instrument name
            timeframe: Timeframe string
            start: Start datetime
            end: End datetime
            limit: Maximum number of records
            
        Returns:
            List of candle dictionaries
        """
        table_name = self.TIMEFRAME_TABLE_MAP.get(timeframe)
        if not table_name:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        
        query = f"""
        SELECT 
            timestamp, open, high, low, close, 
            volume, volume_usd, trades_count, source
        FROM crypto.{table_name}
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
            
            columns = ['timestamp', 'open', 'high', 'low', 'close', 
                      'volume', 'volume_usd', 'trades_count', 'source']
            
            candles = []
            for row in cursor.fetchall():
                candle = dict(zip(columns, row))
                # Convert Decimal to float for easier use
                for key in ['open', 'high', 'low', 'close', 'volume', 'volume_usd']:
                    if candle[key] is not None:
                        candle[key] = float(candle[key])
                candles.append(candle)
            
            return candles
    
    def get_latest_timestamp(
        self,
        instrument: str,
        timeframe: str
    ) -> Optional[datetime]:
        """
        Get the timestamp of the most recent candle.
        
        Args:
            instrument: Instrument name
            timeframe: Timeframe string
            
        Returns:
            Latest timestamp or None
        """
        table_name = self.TIMEFRAME_TABLE_MAP.get(timeframe)
        if not table_name:
            return None
        
        query = f"""
        SELECT MAX(timestamp) 
        FROM crypto.{table_name}
        WHERE instrument = :instrument
        """
        
        with get_connection("analyst") as conn:
            cursor = conn.cursor()
            cursor.execute(query, {"instrument": instrument})
            result = cursor.fetchone()
            return result[0] if result and result[0] else None
    
    def get_earliest_timestamp(
        self,
        instrument: str,
        timeframe: str
    ) -> Optional[datetime]:
        """
        Get the timestamp of the earliest candle.
        
        Args:
            instrument: Instrument name
            timeframe: Timeframe string
            
        Returns:
            Earliest timestamp or None
        """
        table_name = self.TIMEFRAME_TABLE_MAP.get(timeframe)
        if not table_name:
            return None
        
        query = f"""
        SELECT MIN(timestamp) 
        FROM crypto.{table_name}
        WHERE instrument = :instrument
        """
        
        with get_connection("analyst") as conn:
            cursor = conn.cursor()
            cursor.execute(query, {"instrument": instrument})
            result = cursor.fetchone()
            return result[0] if result and result[0] else None
    
    def get_candle_count(
        self,
        instrument: str,
        timeframe: str,
        start: Optional[datetime] = None,
        end: Optional[datetime] = None
    ) -> int:
        """
        Get count of candles for an instrument.
        
        Args:
            instrument: Instrument name
            timeframe: Timeframe string
            start: Optional start datetime
            end: Optional end datetime
            
        Returns:
            Number of candles
        """
        table_name = self.TIMEFRAME_TABLE_MAP.get(timeframe)
        if not table_name:
            return 0
        
        query = f"""
        SELECT COUNT(*) 
        FROM crypto.{table_name}
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
    
    def delete_candles(
        self,
        instrument: str,
        timeframe: str,
        start: datetime,
        end: datetime
    ) -> int:
        """
        Delete candles in a time range.
        
        Args:
            instrument: Instrument name
            timeframe: Timeframe string
            start: Start datetime
            end: End datetime
            
        Returns:
            Number of deleted records
        """
        table_name = self.TIMEFRAME_TABLE_MAP.get(timeframe)
        if not table_name:
            return 0
        
        query = f"""
        DELETE FROM crypto.{table_name}
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
            
            logger.info(f"Deleted {deleted} {timeframe} candles for {instrument}")
            return deleted
    
    def log_collection(
        self,
        instrument: str,
        timeframe: str,
        source: str,
        start_time: datetime,
        end_time: datetime,
        records_collected: int,
        status: str,
        error_message: Optional[str] = None,
        duration_seconds: Optional[float] = None
    ):
        """
        Log a collection operation.
        
        Args:
            instrument: Instrument name
            timeframe: Timeframe string
            source: Data source
            start_time: Collection start time
            end_time: Collection end time
            records_collected: Number of records collected
            status: Collection status
            error_message: Error message if failed
            duration_seconds: Collection duration
        """
        with get_session("collector") as session:
            log_entry = CollectionLog(
                instrument=instrument,
                data_type=f"ohlcv_{timeframe}",
                source=source,
                start_time=start_time,
                end_time=end_time,
                records_collected=records_collected,
                status=status,
                error_message=error_message,
                duration_seconds=Decimal(str(duration_seconds)) if duration_seconds else None
            )
            session.add(log_entry)


