#!/usr/bin/env python3
"""
Load collected CSV data into PostgreSQL database
"""

import os
import sys
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from datetime import datetime
from loguru import logger

# Database connection settings - Local Supabase
# Set these environment variables or use .env file
DB_CONFIG = {
    "host": os.environ.get("DB_HOST", "127.0.0.1"),
    "port": int(os.environ.get("DB_PORT", "54322")),
    "database": os.environ.get("DB_NAME", "postgres"),
    "user": os.environ.get("DB_USER", "postgres"),
    "password": os.environ.get("DB_PASSWORD", ""),
}

DATA_DIR = "data_exports"


def get_connection():
    """Get database connection"""
    return psycopg2.connect(**DB_CONFIG)


def load_instruments(conn, currency: str):
    """Load instruments from CSV to database"""
    filepath = f"{DATA_DIR}/instruments_{currency}.csv"
    if not os.path.exists(filepath):
        logger.warning(f"  File not found: {filepath}")
        return 0
        
    df = pd.read_csv(filepath)
    logger.info(f"  Loading {len(df)} {currency} instruments...")
    
    cursor = conn.cursor()
    
    inserted = 0
    for _, row in df.iterrows():
        try:
            cursor.execute("""
                INSERT INTO instruments (
                    instrument_name, kind, base_currency, quote_currency,
                    strike, option_type, expiration_timestamp, 
                    tick_size, min_trade_amount, contract_size, is_active
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (instrument_name) DO UPDATE SET
                    is_active = EXCLUDED.is_active,
                    updated_at = NOW()
            """, (
                row.get('instrument_name'),
                row.get('kind'),
                row.get('base_currency'),
                row.get('quote_currency', 'USD'),
                row.get('strike'),
                row.get('option_type'),
                row.get('expiration_timestamp'),
                row.get('tick_size'),
                row.get('min_trade_amount'),
                row.get('contract_size'),
                row.get('is_active', True)
            ))
            inserted += 1
        except Exception as e:
            logger.debug(f"    Skip: {e}")
            
    conn.commit()
    return inserted


def get_instrument_id(conn, instrument_name: str) -> int:
    """Get or create instrument ID"""
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id FROM instruments WHERE instrument_name = %s",
        (instrument_name,)
    )
    result = cursor.fetchone()
    
    if result:
        return result[0]
        
    # Create instrument
    cursor.execute("""
        INSERT INTO instruments (instrument_name, kind, base_currency)
        VALUES (%s, %s, %s)
        ON CONFLICT (instrument_name) DO NOTHING
        RETURNING id
    """, (
        instrument_name,
        'future' if 'PERPETUAL' in instrument_name else 'option',
        instrument_name.split('-')[0]
    ))
    
    result = cursor.fetchone()
    if result:
        conn.commit()
        return result[0]
        
    # Fetch again
    cursor.execute(
        "SELECT id FROM instruments WHERE instrument_name = %s",
        (instrument_name,)
    )
    result = cursor.fetchone()
    conn.commit()
    return result[0] if result else None


def load_ohlcv(conn, instrument_name: str, timeframe: str):
    """Load OHLCV data"""
    filepath = f"{DATA_DIR}/ohlcv_{instrument_name}_{timeframe}.csv"
    if not os.path.exists(filepath):
        return 0
        
    df = pd.read_csv(filepath)
    if df.empty:
        return 0
        
    instrument_id = get_instrument_id(conn, instrument_name)
    if not instrument_id:
        logger.warning(f"  Could not get instrument ID for {instrument_name}")
        return 0
        
    logger.info(f"  Loading {len(df)} {instrument_name} {timeframe} candles...")
    
    # Map timeframe
    tf_map = {"1": "1m", "5": "5m", "15": "15m", "60": "1h", "1D": "1d"}
    db_timeframe = tf_map.get(timeframe, timeframe)
    
    cursor = conn.cursor()
    
    # Prepare data
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    values = [
        (
            row['timestamp'],
            instrument_id,
            db_timeframe,
            row['open'],
            row['high'],
            row['low'],
            row['close'],
            row['volume'],
            None  # trades_count
        )
        for _, row in df.iterrows()
    ]
    
    # Batch insert
    execute_values(
        cursor,
        """
        INSERT INTO ohlcv (time, instrument_id, timeframe, open, high, low, close, volume, trades_count)
        VALUES %s
        ON CONFLICT (time, instrument_id, timeframe) DO UPDATE SET
            close = EXCLUDED.close,
            volume = EXCLUDED.volume
        """,
        values,
        page_size=1000
    )
    
    conn.commit()
    return len(values)


def load_funding(conn, instrument_name: str):
    """Load funding rate history"""
    filepath = f"{DATA_DIR}/funding_{instrument_name}.csv"
    if not os.path.exists(filepath):
        return 0
        
    df = pd.read_csv(filepath)
    if df.empty:
        return 0
        
    instrument_id = get_instrument_id(conn, instrument_name)
    if not instrument_id:
        return 0
        
    logger.info(f"  Loading {len(df)} {instrument_name} funding records...")
    
    cursor = conn.cursor()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    values = [
        (
            row['timestamp'],
            instrument_id,
            row.get('interest_8h', 0),
            row.get('interest_8h', 0),
            None,  # annualized
            row.get('index_price'),
            None,  # mark_price
            None,  # premium
            None   # premium_percent
        )
        for _, row in df.iterrows()
    ]
    
    execute_values(
        cursor,
        """
        INSERT INTO funding_rates (time, instrument_id, funding_rate, funding_rate_8h, 
                                   funding_rate_annualized, index_price, mark_price, premium, premium_percent)
        VALUES %s
        ON CONFLICT (time, instrument_id) DO NOTHING
        """,
        values,
        page_size=1000
    )
    
    conn.commit()
    return len(values)


def load_dvol(conn, currency: str):
    """Load DVOL history"""
    filepath = f"{DATA_DIR}/dvol_{currency}.csv"
    if not os.path.exists(filepath):
        return 0
        
    df = pd.read_csv(filepath)
    if df.empty:
        return 0
        
    logger.info(f"  Loading {len(df)} {currency} DVOL records...")
    
    cursor = conn.cursor()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    values = [
        (
            row['timestamp'],
            currency,
            row.get('dvol_close', row.get('dvol', 0)),
            None, None, None, None  # rv values
        )
        for _, row in df.iterrows()
    ]
    
    execute_values(
        cursor,
        """
        INSERT INTO volatility_index (time, base_currency, dvol, rv_7d, rv_30d, rv_90d, vol_premium)
        VALUES %s
        ON CONFLICT (time, base_currency) DO NOTHING
        """,
        values,
        page_size=1000
    )
    
    conn.commit()
    return len(values)


def load_options_surface(conn, currency: str):
    """Load options surface data"""
    filepath = f"{DATA_DIR}/options_surface_{currency}.csv"
    if not os.path.exists(filepath):
        return 0
        
    df = pd.read_csv(filepath)
    if df.empty:
        return 0
        
    logger.info(f"  Loading {len(df)} {currency} options records...")
    
    cursor = conn.cursor()
    
    # First ensure all options instruments exist
    for _, row in df.iterrows():
        instr_name = row.get('instrument_name')
        if not instr_name:
            continue
            
        cursor.execute("""
            INSERT INTO instruments (instrument_name, kind, base_currency, strike, option_type)
            VALUES (%s, 'option', %s, %s, %s)
            ON CONFLICT (instrument_name) DO NOTHING
        """, (
            instr_name,
            currency,
            row.get('strike'),
            row.get('option_type')
        ))
    
    conn.commit()
    
    # Now load the market data
    inserted = 0
    for _, row in df.iterrows():
        instr_name = row.get('instrument_name')
        if not instr_name:
            continue
            
        instrument_id = get_instrument_id(conn, instr_name)
        if not instrument_id:
            continue
            
        try:
            timestamp = pd.to_datetime(row.get('timestamp', datetime.now()))
            
            cursor.execute("""
                INSERT INTO options_market_data (
                    time, instrument_id, mark_price, underlying_price,
                    mark_iv, delta, gamma, theta, vega, open_interest, volume_24h
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (time, instrument_id) DO NOTHING
            """, (
                timestamp,
                instrument_id,
                row.get('mark_price'),
                row.get('underlying_price'),
                row.get('mark_iv'),
                row.get('delta'),
                row.get('gamma'),
                row.get('theta'),
                row.get('vega'),
                row.get('open_interest'),
                row.get('volume_24h')
            ))
            inserted += 1
        except Exception as e:
            logger.debug(f"    Skip option: {e}")
            
    conn.commit()
    return inserted


def main():
    """Main function"""
    
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║           LOADING DATA INTO POSTGRESQL                            ║
╠═══════════════════════════════════════════════════════════════════╣
║  Database: deribit_data                                           ║
║  Host: localhost:5433                                             ║
╚═══════════════════════════════════════════════════════════════════╝
    """)
    
    try:
        conn = get_connection()
        logger.info("Connected to database")
    except Exception as e:
        logger.error(f"Failed to connect: {e}")
        logger.info("Make sure PostgreSQL is running: docker-compose up -d")
        return
        
    total_records = 0
    
    # 1. Load instruments
    logger.info("\n📦 Loading Instruments...")
    for currency in ["BTC", "ETH", "SOL"]:
        count = load_instruments(conn, currency)
        total_records += count
        
    # 2. Load OHLCV data
    logger.info("\n📈 Loading OHLCV Data...")
    for instrument in ["BTC-PERPETUAL", "ETH-PERPETUAL", "SOL-PERPETUAL"]:
        for tf in ["1", "5", "15", "60", "1D"]:
            count = load_ohlcv(conn, instrument, tf)
            total_records += count
            
    # 3. Load funding rates
    logger.info("\n💰 Loading Funding Rates...")
    for instrument in ["BTC-PERPETUAL", "ETH-PERPETUAL"]:
        count = load_funding(conn, instrument)
        total_records += count
        
    # 4. Load DVOL
    logger.info("\n📊 Loading DVOL...")
    for currency in ["BTC", "ETH"]:
        count = load_dvol(conn, currency)
        total_records += count
        
    # 5. Load options surface
    logger.info("\n🎯 Loading Options Data...")
    for currency in ["BTC", "ETH"]:
        count = load_options_surface(conn, currency)
        total_records += count
        
    conn.close()
    
    print(f"""
╔═══════════════════════════════════════════════════════════════════╗
║                    LOAD COMPLETE ✓                                ║
╠═══════════════════════════════════════════════════════════════════╣
║  Total records loaded: {total_records:,}                                  ║
║                                                                   ║
║  Access the data:                                                 ║
║    • pgAdmin: http://localhost:5050                               ║
║    • PostgreSQL: localhost:5433                                   ║
║                                                                   ║
║  Login:                                                           ║
║    • Email: admin@example.com                                     ║
║    • Password: (set in .env)                                      ║
╚═══════════════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    main()

