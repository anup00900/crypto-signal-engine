#!/usr/bin/env python3
"""
Comprehensive Deribit Data Collection Script
Downloads 2 years of data and stores in PostgreSQL

Data collected:
- OHLCV (1m, 5m, 15m, 1h, 1d)
- Options surface (IV, Greeks)
- Order book snapshots
- Funding rates
- Open interest
- Basis (futures vs spot)
- DVOL (volatility index)
"""

import asyncio
import os
import sys
from datetime import datetime

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collectors.deribit.comprehensive_collector import ComprehensiveCollector, CollectionConfig
from loguru import logger

# Configure logging
logger.remove()
logger.add(sys.stderr, level="INFO", 
           format="<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | {message}")
logger.add("logs/collection.log", rotation="100 MB", level="DEBUG")


async def main():
    """Main collection function"""
    
    print("""
╔═══════════════════════════════════════════════════════════════════╗
║           DERIBIT COMPREHENSIVE DATA COLLECTOR                    ║
╠═══════════════════════════════════════════════════════════════════╣
║  Collecting:                                                      ║
║    • OHLCV (1m, 5m, 15m, 1h, 1d) - 2 years                       ║
║    • Options Surface (IV, Greeks, Skew)                           ║
║    • Order Book Snapshots                                         ║
║    • Funding Rates History                                        ║
║    • Open Interest                                                ║
║    • Basis (Futures vs Spot)                                      ║
║    • DVOL (Volatility Index)                                      ║
╚═══════════════════════════════════════════════════════════════════╝
    """)
    
    # Ensure output directories exist
    os.makedirs("data_exports", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    # Configuration
    config = CollectionConfig(
        currencies=["BTC", "ETH"],  # Main currencies
        years_history=2,
        ohlcv_timeframes=["1", "5", "15", "60", "1D"],  # 1m, 5m, 15m, 1h, 1d
        output_dir="data_exports"
    )
    
    start_time = datetime.now()
    logger.info(f"Starting collection at {start_time}")
    
    try:
        async with ComprehensiveCollector(config) as collector:
            results = await collector.collect_all(include_historical=True)
            
        end_time = datetime.now()
        duration = end_time - start_time
        
        print(f"""
╔═══════════════════════════════════════════════════════════════════╗
║                    COLLECTION COMPLETE ✓                          ║
╠═══════════════════════════════════════════════════════════════════╣
║  Duration: {str(duration).split('.')[0]}                                            ║
║  Data saved to: data_exports/                                     ║
║                                                                   ║
║  Files created:                                                   ║""")
        
        # List created files
        for f in sorted(os.listdir("data_exports")):
            if f.endswith('.csv'):
                size = os.path.getsize(f"data_exports/{f}") / 1024 / 1024
                print(f"║    • {f}: {size:.2f} MB")
                
        print("""║                                                                   ║
║  Next: Load data into PostgreSQL with:                            ║
║    python scripts/load_to_database.py                             ║
╚═══════════════════════════════════════════════════════════════════╝
        """)
        
    except Exception as e:
        logger.error(f"Collection failed: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())

