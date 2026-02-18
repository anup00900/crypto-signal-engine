#!/usr/bin/env python3
"""
Initial historical data load script for Crypto Data Collector.

This script performs the first-time historical data collection for:
- Top 10 cryptocurrencies
- Multiple timeframes (1d, 1h, 15m, 5m, 1m)
- 1-second data (aggregated from trades)
- Funding rates for perpetual contracts

Usage:
    # Load daily data for all top 10 cryptos
    python scripts/initial_load.py --timeframes 1d
    
    # Load specific instruments
    python scripts/initial_load.py --instruments BTC-PERPETUAL,ETH-PERPETUAL --timeframes 1d,1h
    
    # Load all timeframes for all instruments
    python scripts/initial_load.py --all
    
    # Load 1-second data (trades aggregation)
    python scripts/initial_load.py --instruments BTC-PERPETUAL --timeframes 1s --days 7
"""

import argparse
import sys
import time
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table

from config.settings import settings
from config.instruments import TOP_10_INSTRUMENTS, get_all_deribit_perpetuals
from collectors.deribit import (
    DeribitClient,
    DeribitOHLCVCollector,
    DeribitTradesCollector,
    DeribitFundingCollector
)
from storage import OHLCVStore, TradesStore, FundingStore
from processors import DataValidator, TradeAggregator
from utils.logger import setup_logger
from utils.time_utils import years_ago, now_utc


console = Console()


def get_instruments(instrument_arg: Optional[str], all_flag: bool) -> List[str]:
    """Get list of instruments to collect."""
    if instrument_arg:
        return [i.strip() for i in instrument_arg.split(",")]
    
    if all_flag:
        return get_all_deribit_perpetuals()
    
    # Default to top 10 perpetuals
    return [inst.deribit_perpetual for inst in TOP_10_INSTRUMENTS]


def get_timeframes(timeframe_arg: Optional[str], all_flag: bool) -> List[str]:
    """Get list of timeframes to collect."""
    if timeframe_arg:
        return [t.strip() for t in timeframe_arg.split(",")]
    
    if all_flag:
        return ["1d", "1h", "15m", "5m", "1m"]
    
    # Default to daily and hourly
    return ["1d", "1h"]


def collect_ohlcv_data(
    instruments: List[str],
    timeframes: List[str],
    start: datetime,
    end: datetime,
    client: DeribitClient
):
    """Collect OHLCV data for all instruments and timeframes."""
    collector = DeribitOHLCVCollector(client=client)
    store = OHLCVStore()
    validator = DataValidator()
    
    total_tasks = len(instruments) * len(timeframes)
    completed = 0
    
    results_table = Table(title="OHLCV Collection Results")
    results_table.add_column("Instrument")
    results_table.add_column("Timeframe")
    results_table.add_column("Records")
    results_table.add_column("Duration")
    results_table.add_column("Status")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        
        main_task = progress.add_task(
            f"Collecting OHLCV data ({total_tasks} tasks)",
            total=total_tasks
        )
        
        for instrument in instruments:
            for timeframe in timeframes:
                task_desc = f"{instrument} - {timeframe}"
                progress.update(main_task, description=task_desc)
                
                try:
                    # Collect data
                    result = collector.collect_ohlcv(
                        instrument=instrument,
                        timeframe=timeframe,
                        start=start,
                        end=end
                    )
                    
                    if result.is_success and result.data:
                        # Validate data
                        validation = validator.validate_ohlcv(result.data)
                        
                        # Store data
                        stored = store.store_candles(
                            instrument=instrument,
                            timeframe=timeframe,
                            candles=result.data,
                            source="deribit"
                        )
                        
                        # Log collection
                        store.log_collection(
                            instrument=instrument,
                            timeframe=timeframe,
                            source="deribit",
                            start_time=start,
                            end_time=end,
                            records_collected=stored,
                            status="success" if validation.is_valid else "partial",
                            duration_seconds=result.duration_seconds
                        )
                        
                        results_table.add_row(
                            instrument,
                            timeframe,
                            str(stored),
                            f"{result.duration_seconds:.1f}s",
                            "[green]OK[/green]" if validation.is_valid else "[yellow]WARN[/yellow]"
                        )
                    else:
                        results_table.add_row(
                            instrument,
                            timeframe,
                            "0",
                            f"{result.duration_seconds:.1f}s",
                            f"[red]FAILED[/red]: {result.error_message[:30] if result.error_message else 'Unknown'}"
                        )
                        
                except Exception as e:
                    logger.error(f"Error collecting {instrument} {timeframe}: {e}")
                    results_table.add_row(
                        instrument,
                        timeframe,
                        "0",
                        "-",
                        f"[red]ERROR[/red]: {str(e)[:30]}"
                    )
                
                completed += 1
                progress.update(main_task, completed=completed)
    
    console.print(results_table)


def collect_1s_data(
    instruments: List[str],
    days: int,
    client: DeribitClient
):
    """Collect 1-second data by aggregating trades."""
    trades_collector = DeribitTradesCollector(client=client)
    ohlcv_store = OHLCVStore()
    
    end = now_utc()
    start = end - timedelta(days=days)
    
    console.print(f"\n[bold]Collecting 1s data for {len(instruments)} instruments ({days} days)[/bold]")
    console.print(f"Time range: {start} to {end}")
    console.print("[yellow]Note: 1s data is aggregated from trades, this may take a while...[/yellow]\n")
    
    for instrument in instruments:
        console.print(f"\n[cyan]Processing {instrument}...[/cyan]")
        
        try:
            # Estimate trade count
            estimated_trades = trades_collector.estimate_trade_count(instrument, start, end)
            console.print(f"  Estimated trades: ~{estimated_trades:,}")
            
            # Collect and aggregate in chunks
            aggregator = TradeAggregator(interval_seconds=1)
            total_candles = 0
            
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TimeElapsedColumn(),
                console=console
            ) as progress:
                
                task = progress.add_task(f"Collecting trades for {instrument}", total=None)
                
                for trade_chunk in trades_collector.stream_trades(
                    instrument=instrument,
                    start=start,
                    end=end,
                    chunk_seconds=3600  # 1 hour chunks
                ):
                    # Aggregate to 1s candles
                    candles = aggregator.process_trades(trade_chunk)
                    
                    if candles:
                        ohlcv_store.store_candles(
                            instrument=instrument,
                            timeframe="1s",
                            candles=candles,
                            source="deribit"
                        )
                        total_candles += len(candles)
                    
                    progress.update(task, description=f"{instrument}: {total_candles:,} candles")
                
                # Flush remaining
                final_candles = aggregator.flush()
                if final_candles:
                    ohlcv_store.store_candles(
                        instrument=instrument,
                        timeframe="1s",
                        candles=final_candles,
                        source="deribit"
                    )
                    total_candles += len(final_candles)
            
            stats = aggregator.get_stats()
            console.print(f"  [green]✓ Completed: {total_candles:,} candles from {stats['trades_processed']:,} trades[/green]")
            
        except Exception as e:
            console.print(f"  [red]✗ Error: {e}[/red]")
            logger.error(f"Error collecting 1s data for {instrument}: {e}")


def collect_funding_rates(
    instruments: List[str],
    start: datetime,
    end: datetime,
    client: DeribitClient
):
    """Collect funding rates for perpetual contracts."""
    collector = DeribitFundingCollector(client=client)
    store = FundingStore()
    
    console.print(f"\n[bold]Collecting funding rates for {len(instruments)} instruments[/bold]")
    
    for instrument in instruments:
        if "PERPETUAL" not in instrument.upper():
            continue
        
        try:
            result = collector.collect_funding_rates(
                instrument=instrument,
                start=start,
                end=end
            )
            
            if result.is_success and result.data:
                stored = store.store_funding_rates(
                    instrument=instrument,
                    rates=result.data,
                    source="deribit"
                )
                console.print(f"  [green]✓ {instrument}: {stored} funding rates[/green]")
            else:
                console.print(f"  [yellow]⚠ {instrument}: No data[/yellow]")
                
        except Exception as e:
            console.print(f"  [red]✗ {instrument}: {e}[/red]")


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Initial historical data load for Crypto Data Collector"
    )
    parser.add_argument(
        "--instruments",
        type=str,
        help="Comma-separated list of instruments (e.g., BTC-PERPETUAL,ETH-PERPETUAL)"
    )
    parser.add_argument(
        "--timeframes",
        type=str,
        help="Comma-separated list of timeframes (e.g., 1d,1h,15m)"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Collect all timeframes for all top 10 instruments"
    )
    parser.add_argument(
        "--years",
        type=int,
        default=2,
        help="Years of history to collect (default: 2)"
    )
    parser.add_argument(
        "--days",
        type=int,
        help="Days of history (overrides --years for 1s data)"
    )
    parser.add_argument(
        "--skip-ohlcv",
        action="store_true",
        help="Skip OHLCV collection"
    )
    parser.add_argument(
        "--skip-funding",
        action="store_true",
        help="Skip funding rate collection"
    )
    parser.add_argument(
        "--include-1s",
        action="store_true",
        help="Include 1-second data (trades aggregation)"
    )
    
    args = parser.parse_args()
    
    setup_logger()
    
    console.print("\n[bold blue]╔══════════════════════════════════════════════════════════╗[/bold blue]")
    console.print("[bold blue]║       CRYPTO DATA COLLECTOR - INITIAL DATA LOAD          ║[/bold blue]")
    console.print("[bold blue]╚══════════════════════════════════════════════════════════╝[/bold blue]\n")
    
    # Get instruments and timeframes
    instruments = get_instruments(args.instruments, args.all)
    timeframes = get_timeframes(args.timeframes, args.all)
    
    # Calculate time range
    end = now_utc()
    start = years_ago(args.years)
    
    console.print(f"[bold]Configuration:[/bold]")
    console.print(f"  Instruments: {', '.join(instruments)}")
    console.print(f"  Timeframes: {', '.join(timeframes)}")
    console.print(f"  Date range: {start.date()} to {end.date()}")
    console.print(f"  History: {args.years} years")
    console.print()
    
    # Initialize client
    console.print("[bold]Testing Deribit API connection...[/bold]")
    client = DeribitClient()
    
    if not client.test_connection():
        console.print("[red]✗ Failed to connect to Deribit API[/red]")
        sys.exit(1)
    
    console.print("[green]✓ Connected to Deribit API[/green]\n")
    
    start_time = time.time()
    
    try:
        # Collect OHLCV data
        if not args.skip_ohlcv:
            # Filter out 1s from regular OHLCV collection
            regular_timeframes = [t for t in timeframes if t != "1s"]
            if regular_timeframes:
                collect_ohlcv_data(instruments, regular_timeframes, start, end, client)
        
        # Collect 1-second data
        if args.include_1s or "1s" in timeframes:
            days = args.days or 7  # Default to 7 days for 1s data
            collect_1s_data(instruments, days, client)
        
        # Collect funding rates
        if not args.skip_funding:
            collect_funding_rates(instruments, start, end, client)
        
        total_time = time.time() - start_time
        
        console.print("\n[bold green]╔══════════════════════════════════════════════════════════╗[/bold green]")
        console.print(f"[bold green]║  INITIAL LOAD COMPLETED - Total time: {total_time/60:.1f} minutes        ║[/bold green]")
        console.print("[bold green]╚══════════════════════════════════════════════════════════╝[/bold green]\n")
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Collection interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Collection failed: {e}[/red]")
        logger.exception("Initial load failed")
        sys.exit(1)


if __name__ == "__main__":
    main()


