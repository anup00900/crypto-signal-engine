#!/usr/bin/env python3
"""
Data validation script for Crypto Data Collector.

This script validates collected data and generates reports:
- Check data completeness
- Detect gaps
- Validate data quality
- Generate summary statistics

Usage:
    # Validate all data
    python scripts/validate_data.py
    
    # Validate specific instrument
    python scripts/validate_data.py --instrument BTC-PERPETUAL
    
    # Check for gaps and attempt to fill
    python scripts/validate_data.py --check-gaps --fill-gaps
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from config.instruments import TOP_10_INSTRUMENTS
from storage import OHLCVStore, FundingStore
from processors import DataValidator, GapFiller, ValidationResult
from utils.logger import setup_logger
from utils.time_utils import now_utc, get_timeframe_seconds


console = Console()


def get_data_coverage(instrument: str, store: OHLCVStore) -> dict:
    """Get data coverage for an instrument."""
    timeframes = ["1d", "1h", "15m", "5m", "1m", "1s"]
    coverage = {}
    
    for tf in timeframes:
        earliest = store.get_earliest_timestamp(instrument, tf)
        latest = store.get_latest_timestamp(instrument, tf)
        count = store.get_candle_count(instrument, tf)
        
        coverage[tf] = {
            "earliest": earliest,
            "latest": latest,
            "count": count
        }
    
    return coverage


def display_coverage_report(instruments: List[str]):
    """Display data coverage report."""
    store = OHLCVStore()
    
    console.print("\n[bold]DATA COVERAGE REPORT[/bold]\n")
    
    for instrument in instruments:
        console.print(f"\n[cyan]{instrument}[/cyan]")
        
        coverage = get_data_coverage(instrument, store)
        
        table = Table()
        table.add_column("Timeframe")
        table.add_column("Earliest")
        table.add_column("Latest")
        table.add_column("Records")
        table.add_column("Days")
        
        for tf, data in coverage.items():
            if data["count"] > 0:
                earliest = data["earliest"].strftime("%Y-%m-%d") if data["earliest"] else "-"
                latest = data["latest"].strftime("%Y-%m-%d") if data["latest"] else "-"
                days = (data["latest"] - data["earliest"]).days if data["earliest"] and data["latest"] else 0
                
                table.add_row(
                    tf,
                    earliest,
                    latest,
                    f"{data['count']:,}",
                    str(days)
                )
            else:
                table.add_row(tf, "-", "-", "0", "0")
        
        console.print(table)


def validate_data_quality(
    instrument: str,
    timeframe: str,
    days: int = 30
) -> ValidationResult:
    """Validate data quality for recent data."""
    store = OHLCVStore()
    validator = DataValidator()
    
    end = now_utc()
    start = end - timedelta(days=days)
    
    candles = store.get_candles(
        instrument=instrument,
        timeframe=timeframe,
        start=start,
        end=end
    )
    
    interval_seconds = get_timeframe_seconds(timeframe)
    result = validator.validate_ohlcv(candles, expected_interval_seconds=interval_seconds)
    
    return result


def display_validation_report(instruments: List[str], timeframes: List[str], days: int = 30):
    """Display data validation report."""
    console.print(f"\n[bold]DATA QUALITY VALIDATION (Last {days} days)[/bold]\n")
    
    table = Table()
    table.add_column("Instrument")
    table.add_column("Timeframe")
    table.add_column("Records")
    table.add_column("Valid")
    table.add_column("Errors")
    table.add_column("Warnings")
    table.add_column("Status")
    
    for instrument in instruments:
        for timeframe in timeframes:
            try:
                result = validate_data_quality(instrument, timeframe, days)
                
                status = "[green]PASS[/green]" if result.is_valid else "[red]FAIL[/red]"
                if result.warning_count > 0 and result.is_valid:
                    status = "[yellow]WARN[/yellow]"
                
                table.add_row(
                    instrument,
                    timeframe,
                    str(result.total_records),
                    str(result.valid_records),
                    str(result.error_count),
                    str(result.warning_count),
                    status
                )
            except Exception as e:
                table.add_row(
                    instrument,
                    timeframe,
                    "-",
                    "-",
                    "-",
                    "-",
                    f"[red]ERROR: {str(e)[:20]}[/red]"
                )
    
    console.print(table)


def check_and_display_gaps(
    instruments: List[str],
    timeframes: List[str],
    days: int = 30
):
    """Check and display data gaps."""
    store = OHLCVStore()
    
    console.print(f"\n[bold]GAP DETECTION (Last {days} days)[/bold]\n")
    
    end = now_utc()
    start = end - timedelta(days=days)
    
    all_gaps = []
    
    for instrument in instruments:
        for timeframe in timeframes:
            interval_seconds = get_timeframe_seconds(timeframe)
            gap_filler = GapFiller(interval_seconds=interval_seconds)
            
            candles = store.get_candles(
                instrument=instrument,
                timeframe=timeframe,
                start=start,
                end=end
            )
            
            gaps = gap_filler.detect_gaps(
                candles=candles,
                expected_start=start,
                expected_end=end,
                instrument=instrument,
                data_type=f"ohlcv_{timeframe}"
            )
            
            all_gaps.extend(gaps)
    
    if all_gaps:
        console.print(f"[yellow]Found {len(all_gaps)} gaps:[/yellow]\n")
        
        table = Table()
        table.add_column("Instrument")
        table.add_column("Timeframe")
        table.add_column("Start")
        table.add_column("End")
        table.add_column("Duration")
        table.add_column("Missing")
        
        for gap in all_gaps:
            table.add_row(
                gap.instrument,
                gap.data_type.replace("ohlcv_", ""),
                gap.start.strftime("%Y-%m-%d %H:%M"),
                gap.end.strftime("%Y-%m-%d %H:%M"),
                gap.duration_human,
                str(gap.expected_records)
            )
        
        console.print(table)
    else:
        console.print("[green]No gaps detected![/green]")
    
    return all_gaps


def display_summary_stats(instruments: List[str]):
    """Display summary statistics."""
    store = OHLCVStore()
    funding_store = FundingStore()
    
    console.print("\n[bold]SUMMARY STATISTICS[/bold]\n")
    
    total_ohlcv = 0
    total_funding = 0
    
    for instrument in instruments:
        coverage = get_data_coverage(instrument, store)
        for tf, data in coverage.items():
            total_ohlcv += data["count"]
        
        funding_count = funding_store.get_funding_rate_count(instrument)
        total_funding += funding_count
    
    panel_content = f"""
[bold]Total OHLCV Records:[/bold] {total_ohlcv:,}
[bold]Total Funding Rates:[/bold] {total_funding:,}
[bold]Instruments:[/bold] {len(instruments)}
[bold]Last Updated:[/bold] {now_utc().strftime('%Y-%m-%d %H:%M:%S UTC')}
"""
    
    console.print(Panel(panel_content, title="Database Statistics"))


def main():
    """Main function."""
    parser = argparse.ArgumentParser(
        description="Data validation for Crypto Data Collector"
    )
    parser.add_argument(
        "--instrument",
        type=str,
        help="Validate specific instrument only"
    )
    parser.add_argument(
        "--timeframes",
        type=str,
        default="1d,1h,15m",
        help="Timeframes to validate (default: 1d,1h,15m)"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days of history to validate (default: 30)"
    )
    parser.add_argument(
        "--check-gaps",
        action="store_true",
        help="Check for data gaps"
    )
    parser.add_argument(
        "--coverage",
        action="store_true",
        help="Show data coverage report"
    )
    parser.add_argument(
        "--quality",
        action="store_true",
        help="Run data quality validation"
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Show summary statistics"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run all validations"
    )
    
    args = parser.parse_args()
    
    setup_logger()
    
    console.print("\n[bold blue]╔══════════════════════════════════════════════════════════╗[/bold blue]")
    console.print("[bold blue]║       CRYPTO DATA COLLECTOR - DATA VALIDATION            ║[/bold blue]")
    console.print("[bold blue]╚══════════════════════════════════════════════════════════╝[/bold blue]\n")
    
    # Get instruments
    if args.instrument:
        instruments = [args.instrument]
    else:
        instruments = [inst.deribit_perpetual for inst in TOP_10_INSTRUMENTS]
    
    timeframes = [t.strip() for t in args.timeframes.split(",")]
    
    # Run all if no specific option selected
    run_all = args.all or not (args.check_gaps or args.coverage or args.quality or args.summary)
    
    try:
        if run_all or args.coverage:
            display_coverage_report(instruments)
        
        if run_all or args.quality:
            display_validation_report(instruments, timeframes, args.days)
        
        if run_all or args.check_gaps:
            check_and_display_gaps(instruments, timeframes, args.days)
        
        if run_all or args.summary:
            display_summary_stats(instruments)
        
        console.print("\n[green]Validation complete![/green]\n")
        
    except Exception as e:
        console.print(f"\n[red]Validation failed: {e}[/red]")
        logger.exception("Validation failed")
        sys.exit(1)


if __name__ == "__main__":
    main()


