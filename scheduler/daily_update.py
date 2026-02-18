"""
Daily update scheduler for automated data collection.
"""

import time
from datetime import datetime, timezone
from typing import List, Optional, Callable

import schedule
from loguru import logger

from config.settings import settings
from config.instruments import TOP_10_INSTRUMENTS
from collectors.deribit import DeribitClient, DeribitOHLCVCollector, DeribitFundingCollector
from storage import OHLCVStore, FundingStore


class DailyUpdateScheduler:
    """
    Schedules and runs daily data updates.
    
    Usage:
        scheduler = DailyUpdateScheduler()
        
        # Run once
        scheduler.run_update()
        
        # Schedule and run continuously
        scheduler.start()
    """
    
    def __init__(
        self,
        instruments: Optional[List[str]] = None,
        timeframes: Optional[List[str]] = None,
        overlap_days: int = 2
    ):
        """
        Initialize scheduler.
        
        Args:
            instruments: Instruments to update
            timeframes: Timeframes to update
            overlap_days: Days of overlap for safety
        """
        self.instruments = instruments or [inst.deribit_perpetual for inst in TOP_10_INSTRUMENTS]
        self.timeframes = timeframes or ["1d", "1h", "15m"]
        self.overlap_days = overlap_days
        
        self.client = None
        self.ohlcv_collector = None
        self.funding_collector = None
        self.ohlcv_store = OHLCVStore()
        self.funding_store = FundingStore()
        
        self._running = False
        self._callbacks: List[Callable] = []
    
    def _init_collectors(self):
        """Initialize collectors."""
        if self.client is None:
            self.client = DeribitClient()
            self.ohlcv_collector = DeribitOHLCVCollector(client=self.client)
            self.funding_collector = DeribitFundingCollector(client=self.client)
    
    def add_callback(self, callback: Callable):
        """Add a callback to run after each update."""
        self._callbacks.append(callback)
    
    def run_update(self):
        """Run a single update cycle."""
        self._init_collectors()
        
        from datetime import timedelta
        from utils.time_utils import now_utc
        
        end = now_utc()
        start = end - timedelta(days=self.overlap_days)
        
        logger.info(f"Starting daily update at {datetime.now(timezone.utc)}")
        logger.info(f"Instruments: {len(self.instruments)}, Timeframes: {self.timeframes}")
        
        success_count = 0
        error_count = 0
        
        # Update OHLCV
        for instrument in self.instruments:
            for timeframe in self.timeframes:
                try:
                    result = self.ohlcv_collector.collect_ohlcv(
                        instrument=instrument,
                        timeframe=timeframe,
                        start=start,
                        end=end
                    )
                    
                    if result.is_success and result.data:
                        self.ohlcv_store.store_candles(
                            instrument=instrument,
                            timeframe=timeframe,
                            candles=result.data,
                            source="deribit"
                        )
                        success_count += 1
                    else:
                        error_count += 1
                        
                except Exception as e:
                    logger.error(f"Error updating {instrument} {timeframe}: {e}")
                    error_count += 1
        
        # Update funding rates
        for instrument in self.instruments:
            if "PERPETUAL" not in instrument.upper():
                continue
            
            try:
                result = self.funding_collector.collect_funding_rates(
                    instrument=instrument,
                    start=start,
                    end=end
                )
                
                if result.is_success and result.data:
                    self.funding_store.store_funding_rates(
                        instrument=instrument,
                        rates=result.data,
                        source="deribit"
                    )
                    
            except Exception as e:
                logger.error(f"Error updating funding for {instrument}: {e}")
        
        logger.info(f"Daily update completed: {success_count} successful, {error_count} errors")
        
        # Run callbacks
        for callback in self._callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Callback error: {e}")
    
    def schedule_daily(
        self,
        hour: Optional[int] = None,
        minute: Optional[int] = None
    ):
        """
        Schedule daily updates.
        
        Args:
            hour: Hour to run (UTC)
            minute: Minute to run
        """
        hour = hour or settings.scheduler.daily_update_hour
        minute = minute or settings.scheduler.daily_update_minute
        
        time_str = f"{hour:02d}:{minute:02d}"
        
        schedule.every().day.at(time_str).do(self.run_update)
        logger.info(f"Scheduled daily update at {time_str} UTC")
    
    def start(self):
        """Start the scheduler loop."""
        self._running = True
        logger.info("Scheduler started")
        
        while self._running:
            schedule.run_pending()
            time.sleep(60)  # Check every minute
    
    def stop(self):
        """Stop the scheduler."""
        self._running = False
        logger.info("Scheduler stopped")


def run_scheduled_updates():
    """Convenience function to run scheduled updates."""
    scheduler = DailyUpdateScheduler()
    scheduler.schedule_daily()
    scheduler.start()


