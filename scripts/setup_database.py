#!/usr/bin/env python3
"""
Database setup script for Crypto Data Collector.

This script initializes the PostgreSQL database with:
- Required schemas
- Tables for OHLCV, trades, funding rates
- Role-based user permissions
- Indexes for optimal query performance

Usage:
    python scripts/setup_database.py
    
    # Or with options
    python scripts/setup_database.py --drop-existing
"""

import argparse
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import psycopg2
from psycopg2 import sql
from loguru import logger

from config.settings import settings
from utils.logger import setup_logger


def create_database_if_not_exists():
    """Create the database if it doesn't exist."""
    # Connect to postgres database to create our database
    conn = psycopg2.connect(
        host=settings.database.host,
        port=settings.database.port,
        database="postgres",
        user=settings.database.admin_user,
        password=settings.database.admin_password
    )
    conn.autocommit = True
    
    cursor = conn.cursor()
    
    # Check if database exists
    cursor.execute(
        "SELECT 1 FROM pg_database WHERE datname = %s",
        (settings.database.database,)
    )
    
    if not cursor.fetchone():
        logger.info(f"Creating database: {settings.database.database}")
        cursor.execute(
            sql.SQL("CREATE DATABASE {}").format(
                sql.Identifier(settings.database.database)
            )
        )
        logger.success(f"Database {settings.database.database} created")
    else:
        logger.info(f"Database {settings.database.database} already exists")
    
    cursor.close()
    conn.close()


def create_roles():
    """Create database roles if they don't exist."""
    conn = psycopg2.connect(
        host=settings.database.host,
        port=settings.database.port,
        database=settings.database.database,
        user=settings.database.admin_user,
        password=settings.database.admin_password
    )
    conn.autocommit = True
    cursor = conn.cursor()
    
    roles = [
        ("crypto_collector", settings.database.collector_password),
        ("crypto_analyst", settings.database.analyst_password),
        ("crypto_api", settings.database.api_password),
    ]
    
    for role_name, password in roles:
        cursor.execute(
            "SELECT 1 FROM pg_roles WHERE rolname = %s",
            (role_name,)
        )
        
        if not cursor.fetchone():
            logger.info(f"Creating role: {role_name}")
            cursor.execute(
                sql.SQL("CREATE ROLE {} WITH LOGIN PASSWORD %s").format(
                    sql.Identifier(role_name)
                ),
                (password,)
            )
            cursor.execute(
                sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(
                    sql.Identifier(settings.database.database),
                    sql.Identifier(role_name)
                )
            )
        else:
            logger.info(f"Role {role_name} already exists")
    
    cursor.close()
    conn.close()


def create_schema_and_tables():
    """Create the crypto schema and all tables."""
    conn = psycopg2.connect(
        host=settings.database.host,
        port=settings.database.port,
        database=settings.database.database,
        user=settings.database.admin_user,
        password=settings.database.admin_password
    )
    cursor = conn.cursor()
    
    # Create schema
    logger.info("Creating crypto schema...")
    cursor.execute("CREATE SCHEMA IF NOT EXISTS crypto")
    
    # Instruments table
    logger.info("Creating instruments table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crypto.instruments (
            id SERIAL PRIMARY KEY,
            symbol VARCHAR(20) NOT NULL,
            name VARCHAR(100) NOT NULL,
            exchange VARCHAR(50) NOT NULL,
            instrument_name VARCHAR(100) NOT NULL UNIQUE,
            instrument_type VARCHAR(50) NOT NULL,
            base_currency VARCHAR(20) NOT NULL,
            quote_currency VARCHAR(20) NOT NULL,
            contract_size DECIMAL(20, 8),
            tick_size DECIMAL(20, 10),
            min_trade_amount DECIMAL(20, 8),
            is_active BOOLEAN DEFAULT true,
            coingecko_id VARCHAR(100),
            metadata JSONB,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    
    # Create OHLCV tables for each timeframe
    ohlcv_tables = ['ohlcv_1s', 'ohlcv_1m', 'ohlcv_5m', 'ohlcv_15m', 'ohlcv_1h', 'ohlcv_4h', 'ohlcv_1d']
    
    for table_name in ohlcv_tables:
        logger.info(f"Creating {table_name} table...")
        
        # For 1s and trades, use partitioning
        if table_name in ['ohlcv_1s']:
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS crypto.{table_name} (
                    id BIGSERIAL,
                    instrument_id INTEGER REFERENCES crypto.instruments(id),
                    instrument VARCHAR(100) NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    open DECIMAL(20, 8) NOT NULL,
                    high DECIMAL(20, 8) NOT NULL,
                    low DECIMAL(20, 8) NOT NULL,
                    close DECIMAL(20, 8) NOT NULL,
                    volume DECIMAL(20, 8) NOT NULL,
                    volume_usd DECIMAL(20, 2),
                    trades_count INTEGER,
                    source VARCHAR(50) DEFAULT 'deribit',
                    collected_at TIMESTAMPTZ DEFAULT NOW(),
                    PRIMARY KEY (id, timestamp),
                    UNIQUE(instrument, timestamp)
                ) PARTITION BY RANGE (timestamp)
            """)
            
            # Create partitions for 2024-2026
            for year in [2024, 2025, 2026]:
                for month in range(1, 13):
                    partition_name = f"{table_name}_{year}_{month:02d}"
                    start_date = f"{year}-{month:02d}-01"
                    if month == 12:
                        end_date = f"{year + 1}-01-01"
                    else:
                        end_date = f"{year}-{month + 1:02d}-01"
                    
                    try:
                        cursor.execute(f"""
                            CREATE TABLE IF NOT EXISTS crypto.{partition_name} 
                            PARTITION OF crypto.{table_name}
                            FOR VALUES FROM ('{start_date}') TO ('{end_date}')
                        """)
                    except psycopg2.errors.DuplicateTable:
                        pass
        else:
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS crypto.{table_name} (
                    id BIGSERIAL PRIMARY KEY,
                    instrument_id INTEGER REFERENCES crypto.instruments(id),
                    instrument VARCHAR(100) NOT NULL,
                    timestamp TIMESTAMPTZ NOT NULL,
                    open DECIMAL(20, 8) NOT NULL,
                    high DECIMAL(20, 8) NOT NULL,
                    low DECIMAL(20, 8) NOT NULL,
                    close DECIMAL(20, 8) NOT NULL,
                    volume DECIMAL(20, 8) NOT NULL,
                    volume_usd DECIMAL(20, 2),
                    trades_count INTEGER,
                    source VARCHAR(50) DEFAULT 'deribit',
                    collected_at TIMESTAMPTZ DEFAULT NOW(),
                    UNIQUE(instrument, timestamp)
                )
            """)
        
        # Create indexes
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{table_name}_instrument_ts 
            ON crypto.{table_name}(instrument, timestamp)
        """)
        cursor.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{table_name}_timestamp 
            ON crypto.{table_name}(timestamp)
        """)
    
    # Trades table (partitioned)
    logger.info("Creating trades table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crypto.trades (
            id BIGSERIAL,
            instrument_id INTEGER REFERENCES crypto.instruments(id),
            instrument VARCHAR(100) NOT NULL,
            trade_id VARCHAR(100) NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            price DECIMAL(20, 8) NOT NULL,
            amount DECIMAL(20, 8) NOT NULL,
            direction VARCHAR(10),
            tick_direction INTEGER,
            liquidation BOOLEAN DEFAULT false,
            source VARCHAR(50) DEFAULT 'deribit',
            collected_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (id, timestamp),
            UNIQUE(instrument, trade_id, timestamp)
        ) PARTITION BY RANGE (timestamp)
    """)
    
    # Create trade partitions
    for year in [2024, 2025, 2026]:
        for month in range(1, 13):
            partition_name = f"trades_{year}_{month:02d}"
            start_date = f"{year}-{month:02d}-01"
            if month == 12:
                end_date = f"{year + 1}-01-01"
            else:
                end_date = f"{year}-{month + 1:02d}-01"
            
            try:
                cursor.execute(f"""
                    CREATE TABLE IF NOT EXISTS crypto.{partition_name} 
                    PARTITION OF crypto.trades
                    FOR VALUES FROM ('{start_date}') TO ('{end_date}')
                """)
            except psycopg2.errors.DuplicateTable:
                pass
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_trades_instrument_ts 
        ON crypto.trades(instrument, timestamp)
    """)
    
    # Funding rates table
    logger.info("Creating funding_rates table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crypto.funding_rates (
            id BIGSERIAL PRIMARY KEY,
            instrument_id INTEGER REFERENCES crypto.instruments(id),
            instrument VARCHAR(100) NOT NULL,
            timestamp TIMESTAMPTZ NOT NULL,
            funding_rate DECIMAL(20, 10) NOT NULL,
            mark_price DECIMAL(20, 8),
            index_price DECIMAL(20, 8),
            source VARCHAR(50) DEFAULT 'deribit',
            collected_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(instrument, timestamp)
        )
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_funding_instrument_ts 
        ON crypto.funding_rates(instrument, timestamp)
    """)
    
    # Collection log table
    logger.info("Creating collection_log table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crypto.collection_log (
            id SERIAL PRIMARY KEY,
            instrument VARCHAR(100) NOT NULL,
            data_type VARCHAR(50) NOT NULL,
            source VARCHAR(50) NOT NULL,
            start_time TIMESTAMPTZ NOT NULL,
            end_time TIMESTAMPTZ NOT NULL,
            records_collected INTEGER NOT NULL,
            status VARCHAR(20) NOT NULL,
            error_message TEXT,
            duration_seconds DECIMAL(10, 2),
            collected_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)
    
    # Data gaps table
    logger.info("Creating data_gaps table...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS crypto.data_gaps (
            id SERIAL PRIMARY KEY,
            instrument VARCHAR(100) NOT NULL,
            data_type VARCHAR(50) NOT NULL,
            gap_start TIMESTAMPTZ NOT NULL,
            gap_end TIMESTAMPTZ NOT NULL,
            expected_records INTEGER,
            detected_at TIMESTAMPTZ DEFAULT NOW(),
            filled_at TIMESTAMPTZ,
            status VARCHAR(20) DEFAULT 'detected'
        )
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    
    logger.success("All tables created successfully")


def grant_permissions():
    """Grant appropriate permissions to each role."""
    conn = psycopg2.connect(
        host=settings.database.host,
        port=settings.database.port,
        database=settings.database.database,
        user=settings.database.admin_user,
        password=settings.database.admin_password
    )
    cursor = conn.cursor()
    
    logger.info("Granting permissions...")
    
    # Grant schema usage
    cursor.execute("GRANT USAGE ON SCHEMA crypto TO crypto_collector")
    cursor.execute("GRANT USAGE ON SCHEMA crypto TO crypto_analyst")
    cursor.execute("GRANT USAGE ON SCHEMA crypto TO crypto_api")
    
    # Collector: SELECT, INSERT, UPDATE
    cursor.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA crypto TO crypto_collector")
    cursor.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA crypto TO crypto_collector")
    
    # Analyst: SELECT only
    cursor.execute("GRANT SELECT ON ALL TABLES IN SCHEMA crypto TO crypto_analyst")
    
    # API: SELECT only
    cursor.execute("GRANT SELECT ON ALL TABLES IN SCHEMA crypto TO crypto_api")
    
    # Default privileges for future tables
    cursor.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA crypto 
        GRANT SELECT, INSERT, UPDATE ON TABLES TO crypto_collector
    """)
    cursor.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA crypto 
        GRANT SELECT ON TABLES TO crypto_analyst
    """)
    cursor.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA crypto 
        GRANT SELECT ON TABLES TO crypto_api
    """)
    cursor.execute("""
        ALTER DEFAULT PRIVILEGES IN SCHEMA crypto 
        GRANT USAGE, SELECT ON SEQUENCES TO crypto_collector
    """)
    
    conn.commit()
    cursor.close()
    conn.close()
    
    logger.success("Permissions granted successfully")


def drop_all_tables():
    """Drop all tables (use with caution!)."""
    conn = psycopg2.connect(
        host=settings.database.host,
        port=settings.database.port,
        database=settings.database.database,
        user=settings.database.admin_user,
        password=settings.database.admin_password
    )
    cursor = conn.cursor()
    
    logger.warning("Dropping all tables in crypto schema...")
    cursor.execute("DROP SCHEMA IF EXISTS crypto CASCADE")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    logger.success("Schema dropped")


def main():
    """Main setup function."""
    parser = argparse.ArgumentParser(description="Setup Crypto Data Collector database")
    parser.add_argument(
        "--drop-existing",
        action="store_true",
        help="Drop existing tables before creating (WARNING: destroys data)"
    )
    
    args = parser.parse_args()
    
    setup_logger()
    
    logger.info("=" * 60)
    logger.info("Crypto Data Collector - Database Setup")
    logger.info("=" * 60)
    
    try:
        # Create database
        logger.info("Step 1: Creating database...")
        create_database_if_not_exists()
        
        # Create roles
        logger.info("Step 2: Creating roles...")
        create_roles()
        
        # Drop existing if requested
        if args.drop_existing:
            logger.warning("Dropping existing tables as requested...")
            drop_all_tables()
        
        # Create schema and tables
        logger.info("Step 3: Creating schema and tables...")
        create_schema_and_tables()
        
        # Grant permissions
        logger.info("Step 4: Granting permissions...")
        grant_permissions()
        
        logger.success("=" * 60)
        logger.success("Database setup completed successfully!")
        logger.success("=" * 60)
        
        logger.info("\nConnection details:")
        logger.info(f"  Host: {settings.database.host}")
        logger.info(f"  Port: {settings.database.port}")
        logger.info(f"  Database: {settings.database.database}")
        logger.info("\nAvailable users:")
        logger.info(f"  Admin: {settings.database.admin_user}")
        logger.info(f"  Collector: {settings.database.collector_user}")
        logger.info(f"  Analyst: {settings.database.analyst_user}")
        logger.info(f"  API: {settings.database.api_user}")
        
    except Exception as e:
        logger.error(f"Setup failed: {e}")
        raise


if __name__ == "__main__":
    main()

