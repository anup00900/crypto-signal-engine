"""
Database connection manager for PostgreSQL.
"""

import logging
from contextlib import contextmanager
from typing import Generator, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import QueuePool

from config.settings import settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages database connections with role-based access.
    
    Usage:
        db = DatabaseManager()
        
        # Using raw psycopg2 connection
        with db.get_connection('analyst') as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM crypto.ohlcv_1d")
            
        # Using SQLAlchemy session
        with db.get_session('collector') as session:
            session.add(new_record)
            session.commit()
    """
    
    def __init__(self):
        self._engines = {}
        self._session_makers = {}
    
    def get_engine(self, role: str = "collector"):
        """
        Get or create a SQLAlchemy engine for the specified role.
        
        Args:
            role: One of 'admin', 'collector', 'analyst', 'api'
            
        Returns:
            SQLAlchemy Engine instance
        """
        if role not in self._engines:
            connection_url = settings.database.get_connection_string(role)
            self._engines[role] = create_engine(
                connection_url,
                poolclass=QueuePool,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,
                echo=False
            )
            logger.info(f"Created database engine for role: {role}")
        
        return self._engines[role]
    
    def get_session_maker(self, role: str = "collector"):
        """Get or create a session maker for the specified role."""
        if role not in self._session_makers:
            engine = self.get_engine(role)
            self._session_makers[role] = sessionmaker(bind=engine)
        return self._session_makers[role]
    
    @contextmanager
    def get_session(self, role: str = "collector") -> Generator[Session, None, None]:
        """
        Get a SQLAlchemy session context manager.
        
        Args:
            role: Database role to use
            
        Yields:
            SQLAlchemy Session
        """
        SessionClass = self.get_session_maker(role)
        session = SessionClass()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Session error: {e}")
            raise
        finally:
            session.close()
    
    @contextmanager
    def get_connection(self, role: str = "collector") -> Generator[psycopg2.extensions.connection, None, None]:
        """
        Get a raw psycopg2 connection context manager.
        
        Args:
            role: Database role to use
            
        Yields:
            psycopg2 connection
        """
        from config.database import get_connection_params
        params = get_connection_params(role)
        
        conn = psycopg2.connect(**params)
        try:
            yield conn
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.error(f"Connection error: {e}")
            raise
        finally:
            conn.close()
    
    def execute_query(
        self, 
        query: str, 
        params: Optional[tuple] = None,
        role: str = "analyst",
        fetch: bool = True
    ):
        """
        Execute a query and return results as dictionaries.
        
        Args:
            query: SQL query string
            params: Query parameters
            role: Database role to use
            fetch: Whether to fetch results
            
        Returns:
            List of dictionaries if fetch=True, else None
        """
        with self.get_connection(role) as conn:
            cursor = conn.cursor(cursor_factory=RealDictCursor)
            cursor.execute(query, params)
            
            if fetch:
                return cursor.fetchall()
            return None
    
    def close_all(self):
        """Close all database connections and engines."""
        for role, engine in self._engines.items():
            engine.dispose()
            logger.info(f"Closed engine for role: {role}")
        
        self._engines.clear()
        self._session_makers.clear()


# Singleton instance
_db_manager: Optional[DatabaseManager] = None


def get_db_manager() -> DatabaseManager:
    """Get the singleton database manager instance."""
    global _db_manager
    if _db_manager is None:
        _db_manager = DatabaseManager()
    return _db_manager


def get_engine(role: str = "collector"):
    """Convenience function to get SQLAlchemy engine."""
    return get_db_manager().get_engine(role)


def get_session(role: str = "collector"):
    """Convenience function to get session context manager."""
    return get_db_manager().get_session(role)


def get_connection(role: str = "collector"):
    """Convenience function to get raw connection context manager."""
    return get_db_manager().get_connection(role)


def test_connection(role: str = "collector") -> bool:
    """
    Test database connection.
    
    Args:
        role: Database role to test
        
    Returns:
        True if connection successful, False otherwise
    """
    try:
        with get_connection(role) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            return result[0] == 1
    except Exception as e:
        logger.error(f"Connection test failed for role {role}: {e}")
        return False


def get_table_stats(table_name: str, schema: str = "crypto") -> dict:
    """
    Get statistics for a table.
    
    Args:
        table_name: Name of the table
        schema: Schema name
        
    Returns:
        Dictionary with table statistics
    """
    query = f"""
    SELECT 
        relname as table_name,
        n_live_tup as row_count,
        pg_size_pretty(pg_total_relation_size(relid)) as total_size,
        pg_size_pretty(pg_table_size(relid)) as table_size,
        pg_size_pretty(pg_indexes_size(relid)) as index_size
    FROM pg_stat_user_tables
    WHERE schemaname = %s AND relname = %s
    """
    
    results = get_db_manager().execute_query(query, (schema, table_name), role="analyst")
    
    if results:
        return dict(results[0])
    return {}


