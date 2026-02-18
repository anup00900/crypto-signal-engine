"""
Logging configuration for Crypto Data Collector.
"""

import sys
from pathlib import Path
from typing import Optional

from loguru import logger

from config.settings import settings


def setup_logger(
    log_level: Optional[str] = None,
    log_file: Optional[str] = None,
    rotation: Optional[str] = None,
    retention: Optional[str] = None
) -> None:
    """
    Configure the application logger.
    
    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: Path to log file
        rotation: When to rotate log files (e.g., "10 MB", "1 day")
        retention: How long to keep log files (e.g., "30 days")
    """
    # Use settings defaults if not provided
    log_level = log_level or settings.logging.level
    log_file = log_file or settings.logging.file
    rotation = rotation or settings.logging.rotation
    retention = retention or settings.logging.retention
    
    # Remove default logger
    logger.remove()
    
    # Console handler with color
    logger.add(
        sys.stdout,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
               "<level>{level: <8}</level> | "
               "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
               "<level>{message}</level>",
        colorize=True
    )
    
    # Ensure log directory exists
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    
    # File handler with rotation
    logger.add(
        log_file,
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation=rotation,
        retention=retention,
        compression="gz"
    )
    
    # Separate error log
    error_log = log_path.parent / "errors.log"
    logger.add(
        str(error_log),
        level="ERROR",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}",
        rotation=rotation,
        retention=retention,
        compression="gz"
    )
    
    logger.info(f"Logger initialized with level: {log_level}")


def get_logger(name: str = "crypto_collector"):
    """
    Get a named logger instance.
    
    Args:
        name: Logger name for identification
        
    Returns:
        Logger instance
    """
    return logger.bind(name=name)


# Collection-specific loggers
def get_collection_logger(source: str, instrument: str):
    """Get a logger for data collection with context."""
    return logger.bind(source=source, instrument=instrument)


def log_collection_start(source: str, instrument: str, timeframe: str, start_time, end_time):
    """Log the start of a data collection run."""
    logger.info(
        f"Starting collection | source={source} | instrument={instrument} | "
        f"timeframe={timeframe} | range={start_time} to {end_time}"
    )


def log_collection_complete(
    source: str, 
    instrument: str, 
    timeframe: str, 
    records: int, 
    duration: float
):
    """Log the completion of a data collection run."""
    logger.success(
        f"Collection complete | source={source} | instrument={instrument} | "
        f"timeframe={timeframe} | records={records} | duration={duration:.2f}s"
    )


def log_collection_error(source: str, instrument: str, error: Exception):
    """Log a collection error."""
    logger.error(
        f"Collection error | source={source} | instrument={instrument} | "
        f"error={type(error).__name__}: {str(error)}"
    )


def log_rate_limit_hit(source: str, wait_time: float):
    """Log when rate limit is hit."""
    logger.warning(
        f"Rate limit hit | source={source} | waiting {wait_time:.2f}s"
    )


def log_data_gap_detected(instrument: str, gap_start, gap_end, expected_records: int):
    """Log detection of a data gap."""
    logger.warning(
        f"Data gap detected | instrument={instrument} | "
        f"range={gap_start} to {gap_end} | expected_records={expected_records}"
    )


