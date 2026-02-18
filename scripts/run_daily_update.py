#!/usr/bin/env python3
"""
Daily data update script - Collects from Deribit and pushes to Supabase.

Run manually or via cron:
    python scripts/run_daily_update.py              # Collect last 2 days
    python scripts/run_daily_update.py --days 7     # Collect last 7 days

Cron example (runs daily at 1 AM):
    0 1 * * * cd /path/to/crypto-data-collector && ./venv/bin/python scripts/run_daily_update.py
"""

import os
import sys
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from loguru import logger

# Cloud Supabase connection (24/7 accessible)
# Set these environment variables: SUPABASE_HOST, SUPABASE_PASSWORD
SUPABASE_CONFIG = {
    "host": os.environ.get("SUPABASE_HOST", "localhost"),
    "port": int(os.environ.get("SUPABASE_PORT", "5432")),
    "database": os.environ.get("SUPABASE_DB", "postgres"),
    "user": os.environ.get("SUPABASE_USER", "postgres"),
    "password": os.environ.get("SUPABASE_PASSWORD", ""),
}

DATA_DIR = "data_exports"


from collectors.deribit.comprehensive_collector import ComprehensiveCollector, CollectionConfig


def get_connection():
    """Get Supabase connection."""
    return psycopg2.connect(**SUPABASE_CONFIG)


def get_instrument_id(conn, instrument_name: str) -> int:
    """Get or create instrument ID."""
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM instruments WHERE instrument_name = %s", (instrument_name,))
    result = cursor.fetchone()
    
    if result:
        return result[0]
    
    cursor.execute("""
        INSERT INTO instruments (instrument_name, kind, base_currency)
        VALUES (%s, %s, %s) ON CONFLICT (instrument_name) DO NOTHING RETURNING id
    """, (instrument_name, 'future' if 'PERPETUAL' in instrument_name else 'option', instrument_name.split('-')[0]))
    
    result = cursor.fetchone()
    if result:
        conn.commit()
        return result[0]
    
    cursor.execute("SELECT id FROM instruments WHERE instrument_name = %s", (instrument_name,))
    result = cursor.fetchone()
    conn.commit()
    return result[0] if result else None


def load_ohlcv_to_supabase(conn, instrument_name: str, timeframe: str):
    """Load OHLCV CSV to Supabase."""
    filepath = f"{DATA_DIR}/ohlcv_{instrument_name}_{timeframe}.csv"
    if not os.path.exists(filepath):
        return 0
    
    df = pd.read_csv(filepath)
    if df.empty:
        return 0
    
    instrument_id = get_instrument_id(conn, instrument_name)
    if not instrument_id:
        return 0
    
    tf_map = {"1": "1m", "5": "5m", "15": "15m", "60": "1h", "1D": "1d"}
    db_timeframe = tf_map.get(timeframe, timeframe)
    
    cursor = conn.cursor()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    values = [(row['timestamp'], instrument_id, db_timeframe, row['open'], row['high'], 
               row['low'], row['close'], row['volume'], None) for _, row in df.iterrows()]
    
    execute_values(cursor, """
        INSERT INTO ohlcv (time, instrument_id, timeframe, open, high, low, close, volume, trades_count)
        VALUES %s ON CONFLICT (time, instrument_id, timeframe) DO UPDATE SET
            close = EXCLUDED.close, volume = EXCLUDED.volume
    """, values, page_size=1000)
    
    conn.commit()
    return len(values)


def load_funding_to_supabase(conn, instrument_name: str):
    """Load funding CSV to Supabase."""
    filepath = f"{DATA_DIR}/funding_{instrument_name}.csv"
    if not os.path.exists(filepath):
        return 0
    
    df = pd.read_csv(filepath)
    if df.empty:
        return 0
    
    instrument_id = get_instrument_id(conn, instrument_name)
    if not instrument_id:
        return 0
    
    cursor = conn.cursor()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    
    values = [(row['timestamp'], instrument_id, row.get('interest_8h', 0), row.get('interest_8h', 0),
               None, row.get('index_price'), None, None, None) for _, row in df.iterrows()]
    
    execute_values(cursor, """
        INSERT INTO funding_rates (time, instrument_id, funding_rate, funding_rate_8h, 
                                   funding_rate_annualized, index_price, mark_price, premium, premium_percent)
        VALUES %s ON CONFLICT (time, instrument_id) DO NOTHING
    """, values, page_size=1000)
    
    conn.commit()
    return len(values)


def load_options_to_supabase(conn, currency: str):
    """Load options CSV to Supabase."""
    filepath = f"{DATA_DIR}/options_surface_{currency}.csv"
    if not os.path.exists(filepath):
        return 0
    
    df = pd.read_csv(filepath)
    if df.empty:
        return 0
    
    cursor = conn.cursor()
    
    # Create instruments first
    for _, row in df.iterrows():
        instr_name = row.get('instrument_name')
        if instr_name:
            cursor.execute("""
                INSERT INTO instruments (instrument_name, kind, base_currency, strike, option_type)
                VALUES (%s, 'option', %s, %s, %s) ON CONFLICT (instrument_name) DO NOTHING
            """, (instr_name, currency, row.get('strike'), row.get('option_type')))
    conn.commit()
    
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
                INSERT INTO options_market_data (time, instrument_id, mark_price, underlying_price,
                    mark_iv, delta, gamma, theta, vega, open_interest, volume_24h)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (time, instrument_id) DO NOTHING
            """, (timestamp, instrument_id, row.get('mark_price'), row.get('underlying_price'),
                  row.get('mark_iv'), row.get('delta'), row.get('gamma'), row.get('theta'),
                  row.get('vega'), row.get('open_interest'), row.get('volume_24h')))
            inserted += 1
        except Exception:
            pass
    
    conn.commit()
    return inserted


async def collect_daily_data(days: int = 2):
    """Collect last N days of data from Deribit."""
    os.makedirs(DATA_DIR, exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    config = CollectionConfig(
        currencies=["BTC", "ETH"],
        years_history=days / 365,  # Convert days to years
        ohlcv_timeframes=["1", "5", "15", "60", "1D"],
        output_dir=DATA_DIR
    )
    
    logger.info(f"Collecting last {days} days of data...")
    
    async with ComprehensiveCollector(config) as collector:
        await collector.collect_all(include_historical=True)


def push_to_supabase():
    """Push collected data to Supabase."""
    logger.info("Pushing data to Supabase...")
    
    try:
        conn = get_connection()
        logger.info("Connected to Supabase")
    except Exception as e:
        logger.error(f"Failed to connect to Supabase: {e}")
        return
    
    total = 0
    
    # OHLCV
    for instrument in ["BTC-PERPETUAL", "ETH-PERPETUAL"]:
        for tf in ["1", "5", "15", "60", "1D"]:
            count = load_ohlcv_to_supabase(conn, instrument, tf)
            if count:
                logger.info(f"  {instrument} {tf}: {count} records")
            total += count
    
    # Funding
    for instrument in ["BTC-PERPETUAL", "ETH-PERPETUAL"]:
        count = load_funding_to_supabase(conn, instrument)
        if count:
            logger.info(f"  {instrument} funding: {count} records")
        total += count
    
    # Options
    for currency in ["BTC", "ETH"]:
        count = load_options_to_supabase(conn, currency)
        if count:
            logger.info(f"  {currency} options: {count} records")
        total += count
    
    conn.close()
    logger.info(f"Total: {total:,} records pushed to Supabase")


def main():
    """Main daily update function."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Daily Deribit data update to Supabase")
    parser.add_argument("--days", type=int, default=2, help="Days of data to collect (default: 2)")
    parser.add_argument("--skip-collect", action="store_true", help="Skip collection, only push existing CSVs")
    args = parser.parse_args()
    
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║           DAILY UPDATE - DERIBIT → SUPABASE                       ║
╚═══════════════════════════════════════════════════════════════════╝
    """)
    
    logger.remove()
    logger.add(sys.stderr, level="INFO", format="<green>{time:HH:mm:ss}</green> | {message}")
    logger.add("logs/daily_update.log", rotation="10 MB", level="DEBUG")
    
    start_time = datetime.now()
    logger.info(f"Starting at {start_time}")
    
    # Step 1: Collect from Deribit
    if not args.skip_collect:
        asyncio.run(collect_daily_data(args.days))
    
    # Step 2: Push to Supabase
    push_to_supabase()
    
    duration = datetime.now() - start_time
    logger.info(f"Completed in {duration}")
    
    print(f"""
╔═══════════════════════════════════════════════════════════════════╗
║                    DAILY UPDATE COMPLETE ✓                        ║
╠═══════════════════════════════════════════════════════════════════╣
║  Duration: {str(duration).split('.')[0]}                                              ║
║  Data pushed to Supabase                                          ║
║                                                                   ║
║  Team access: https://supabase.com/dashboard                      ║
║  Login: (see .env for credentials)                                ║
╚═══════════════════════════════════════════════════════════════════╝
    """)


if __name__ == "__main__":
    main()


