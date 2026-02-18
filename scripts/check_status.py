#!/usr/bin/env python3
"""
Quick status check for the crypto database
"""
import sys
sys.path.insert(0, "/Users/anup/Downloads/Crypto Data Collector/crypto-data-collector")

import psycopg2
from config.settings import settings

def main():
    conn = psycopg2.connect(
        host=settings.database.host,
        port=settings.database.port,
        user=settings.database.admin_user,
        password=settings.database.admin_password,
        database=settings.database.database
    )
    cursor = conn.cursor()
    
    print("\n" + "="*70)
    print("📊 CRYPTO DATA COLLECTION STATUS")
    print("="*70)
    
    tables = [
        ('ohlcv_1d', '1 Day'),
        ('ohlcv_1h', '1 Hour'),
        ('ohlcv_15m', '15 Min'),
        ('ohlcv_5m', '5 Min'),
        ('ohlcv_1m', '1 Min'),
        ('ohlcv_1s', '1 Sec'),
    ]
    
    total_candles = 0
    
    print("\n📈 OHLCV Data:")
    print("-" * 70)
    print(f"{'Timeframe':<12} {'BTC-PERPETUAL':>15} {'ETH-PERPETUAL':>15} {'SOL-PERPETUAL':>15}")
    print("-" * 70)
    
    for table, name in tables:
        counts = {}
        for instr in ['BTC-PERPETUAL', 'ETH-PERPETUAL', 'SOL-PERPETUAL']:
            cursor.execute(f"SELECT COUNT(*) FROM crypto.{table} WHERE instrument = %s", (instr,))
            counts[instr] = cursor.fetchone()[0]
            total_candles += counts[instr]
        
        print(f"{name:<12} {counts['BTC-PERPETUAL']:>15,} {counts['ETH-PERPETUAL']:>15,} {counts['SOL-PERPETUAL']:>15,}")
    
    print("-" * 70)
    print(f"{'TOTAL':<12} {total_candles:>47,}")
    
    # Funding rates
    print("\n💰 Funding Rates:")
    print("-" * 50)
    cursor.execute("""
        SELECT instrument, COUNT(*) as count,
               MIN(timestamp)::date as earliest,
               MAX(timestamp)::date as latest
        FROM crypto.funding_rates
        GROUP BY instrument
    """)
    for row in cursor.fetchall():
        print(f"  {row[0]}: {row[1]:,} rates ({row[2]} to {row[3]})")
    
    # Database size
    cursor.execute("""
        SELECT pg_size_pretty(pg_database_size('crypto_data'))
    """)
    db_size = cursor.fetchone()[0]
    
    print(f"\n💾 Database Size: {db_size}")
    print("="*70 + "\n")
    
    cursor.close()
    conn.close()

if __name__ == "__main__":
    main()

