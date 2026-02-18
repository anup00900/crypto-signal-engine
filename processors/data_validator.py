"""
Data validation and quality checks for collected data.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from enum import Enum

from loguru import logger


class ValidationLevel(Enum):
    """Severity level of validation issues."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationIssue:
    """A single validation issue."""
    
    level: ValidationLevel
    code: str
    message: str
    timestamp: Optional[datetime] = None
    details: Optional[Dict[str, Any]] = None


@dataclass
class ValidationResult:
    """Result of data validation."""
    
    is_valid: bool
    total_records: int
    valid_records: int
    issues: List[ValidationIssue] = field(default_factory=list)
    
    @property
    def invalid_records(self) -> int:
        return self.total_records - self.valid_records
    
    @property
    def error_count(self) -> int:
        return len([i for i in self.issues if i.level in (ValidationLevel.ERROR, ValidationLevel.CRITICAL)])
    
    @property
    def warning_count(self) -> int:
        return len([i for i in self.issues if i.level == ValidationLevel.WARNING])
    
    def add_issue(
        self,
        level: ValidationLevel,
        code: str,
        message: str,
        timestamp: Optional[datetime] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        """Add a validation issue."""
        self.issues.append(ValidationIssue(
            level=level,
            code=code,
            message=message,
            timestamp=timestamp,
            details=details
        ))
    
    def summary(self) -> str:
        """Get a summary of validation results."""
        return (
            f"Validation: {'PASSED' if self.is_valid else 'FAILED'}\n"
            f"  Total records: {self.total_records}\n"
            f"  Valid records: {self.valid_records}\n"
            f"  Invalid records: {self.invalid_records}\n"
            f"  Errors: {self.error_count}\n"
            f"  Warnings: {self.warning_count}"
        )


class DataValidator:
    """
    Validates collected data for quality and consistency.
    
    Usage:
        validator = DataValidator()
        
        # Validate OHLCV candles
        result = validator.validate_ohlcv(candles)
        
        if not result.is_valid:
            for issue in result.issues:
                print(f"{issue.level.value}: {issue.message}")
        
        # Validate trades
        result = validator.validate_trades(trades)
    """
    
    def __init__(
        self,
        max_price_change_pct: float = 50.0,
        min_volume: float = 0.0,
        allow_zero_volume: bool = True
    ):
        """
        Initialize validator.
        
        Args:
            max_price_change_pct: Maximum allowed price change between candles (%)
            min_volume: Minimum required volume
            allow_zero_volume: Whether zero volume candles are allowed
        """
        self.max_price_change_pct = max_price_change_pct
        self.min_volume = min_volume
        self.allow_zero_volume = allow_zero_volume
    
    def validate_ohlcv(
        self,
        candles: List[Dict[str, Any]],
        expected_interval_seconds: Optional[int] = None
    ) -> ValidationResult:
        """
        Validate OHLCV candlestick data.
        
        Checks:
        - High >= Low
        - Open and Close between High and Low
        - Volume >= 0
        - Timestamps are sequential
        - No large price gaps
        - No missing candles (if interval provided)
        
        Args:
            candles: List of candle dictionaries
            expected_interval_seconds: Expected interval between candles
            
        Returns:
            ValidationResult
        """
        result = ValidationResult(
            is_valid=True,
            total_records=len(candles),
            valid_records=0
        )
        
        if not candles:
            result.add_issue(
                ValidationLevel.WARNING,
                "EMPTY_DATA",
                "No candles to validate"
            )
            return result
        
        prev_candle = None
        
        for i, candle in enumerate(candles):
            is_valid_candle = True
            
            timestamp = candle.get("timestamp")
            open_price = candle.get("open", 0)
            high = candle.get("high", 0)
            low = candle.get("low", 0)
            close = candle.get("close", 0)
            volume = candle.get("volume", 0)
            
            # Check High >= Low
            if high < low:
                result.add_issue(
                    ValidationLevel.ERROR,
                    "INVALID_HIGH_LOW",
                    f"High ({high}) < Low ({low})",
                    timestamp=timestamp,
                    details={"candle_index": i}
                )
                is_valid_candle = False
            
            # Check Open between High and Low
            if not (low <= open_price <= high):
                result.add_issue(
                    ValidationLevel.ERROR,
                    "INVALID_OPEN",
                    f"Open ({open_price}) not between Low ({low}) and High ({high})",
                    timestamp=timestamp,
                    details={"candle_index": i}
                )
                is_valid_candle = False
            
            # Check Close between High and Low
            if not (low <= close <= high):
                result.add_issue(
                    ValidationLevel.ERROR,
                    "INVALID_CLOSE",
                    f"Close ({close}) not between Low ({low}) and High ({high})",
                    timestamp=timestamp,
                    details={"candle_index": i}
                )
                is_valid_candle = False
            
            # Check Volume
            if volume < self.min_volume:
                result.add_issue(
                    ValidationLevel.WARNING,
                    "LOW_VOLUME",
                    f"Volume ({volume}) below minimum ({self.min_volume})",
                    timestamp=timestamp,
                    details={"candle_index": i}
                )
            
            if volume == 0 and not self.allow_zero_volume:
                result.add_issue(
                    ValidationLevel.WARNING,
                    "ZERO_VOLUME",
                    "Zero volume candle",
                    timestamp=timestamp,
                    details={"candle_index": i}
                )
            
            if volume < 0:
                result.add_issue(
                    ValidationLevel.ERROR,
                    "NEGATIVE_VOLUME",
                    f"Negative volume: {volume}",
                    timestamp=timestamp,
                    details={"candle_index": i}
                )
                is_valid_candle = False
            
            # Check against previous candle
            if prev_candle:
                prev_close = prev_candle.get("close", 0)
                prev_timestamp = prev_candle.get("timestamp")
                
                # Price change check
                if prev_close > 0:
                    price_change_pct = abs((open_price - prev_close) / prev_close * 100)
                    if price_change_pct > self.max_price_change_pct:
                        result.add_issue(
                            ValidationLevel.WARNING,
                            "LARGE_PRICE_GAP",
                            f"Price changed {price_change_pct:.1f}% between candles",
                            timestamp=timestamp,
                            details={
                                "candle_index": i,
                                "prev_close": prev_close,
                                "current_open": open_price
                            }
                        )
                
                # Timestamp sequence check
                if timestamp and prev_timestamp:
                    if timestamp <= prev_timestamp:
                        result.add_issue(
                            ValidationLevel.ERROR,
                            "TIMESTAMP_NOT_SEQUENTIAL",
                            f"Timestamp not after previous: {timestamp} <= {prev_timestamp}",
                            timestamp=timestamp,
                            details={"candle_index": i}
                        )
                        is_valid_candle = False
                    
                    # Gap check
                    if expected_interval_seconds:
                        expected_timestamp = prev_timestamp + timedelta(seconds=expected_interval_seconds)
                        if timestamp > expected_timestamp:
                            gap_seconds = (timestamp - prev_timestamp).total_seconds()
                            result.add_issue(
                                ValidationLevel.WARNING,
                                "GAP_DETECTED",
                                f"Gap of {gap_seconds}s detected (expected {expected_interval_seconds}s)",
                                timestamp=timestamp,
                                details={
                                    "candle_index": i,
                                    "gap_seconds": gap_seconds,
                                    "prev_timestamp": prev_timestamp
                                }
                            )
            
            if is_valid_candle:
                result.valid_records += 1
            
            prev_candle = candle
        
        # Set overall validity
        result.is_valid = result.error_count == 0
        
        return result
    
    def validate_trades(
        self,
        trades: List[Dict[str, Any]]
    ) -> ValidationResult:
        """
        Validate trade data.
        
        Checks:
        - Timestamps are sequential
        - Prices are positive
        - Amounts are non-zero
        - Trade IDs are unique
        
        Args:
            trades: List of trade dictionaries
            
        Returns:
            ValidationResult
        """
        result = ValidationResult(
            is_valid=True,
            total_records=len(trades),
            valid_records=0
        )
        
        if not trades:
            result.add_issue(
                ValidationLevel.WARNING,
                "EMPTY_DATA",
                "No trades to validate"
            )
            return result
        
        seen_ids = set()
        prev_timestamp = None
        
        for i, trade in enumerate(trades):
            is_valid_trade = True
            
            trade_id = trade.get("trade_id")
            timestamp = trade.get("timestamp")
            price = trade.get("price", 0)
            amount = trade.get("amount", 0)
            
            # Check for duplicate trade IDs
            if trade_id:
                if trade_id in seen_ids:
                    result.add_issue(
                        ValidationLevel.ERROR,
                        "DUPLICATE_TRADE_ID",
                        f"Duplicate trade ID: {trade_id}",
                        timestamp=timestamp,
                        details={"trade_index": i}
                    )
                    is_valid_trade = False
                seen_ids.add(trade_id)
            
            # Check price
            if price <= 0:
                result.add_issue(
                    ValidationLevel.ERROR,
                    "INVALID_PRICE",
                    f"Invalid price: {price}",
                    timestamp=timestamp,
                    details={"trade_index": i}
                )
                is_valid_trade = False
            
            # Check amount
            if amount == 0:
                result.add_issue(
                    ValidationLevel.WARNING,
                    "ZERO_AMOUNT",
                    "Trade with zero amount",
                    timestamp=timestamp,
                    details={"trade_index": i}
                )
            
            # Check timestamp sequence (for sorted data)
            if prev_timestamp and timestamp:
                if timestamp < prev_timestamp:
                    result.add_issue(
                        ValidationLevel.WARNING,
                        "TIMESTAMP_OUT_OF_ORDER",
                        f"Trade timestamp out of order",
                        timestamp=timestamp,
                        details={"trade_index": i}
                    )
            
            if is_valid_trade:
                result.valid_records += 1
            
            prev_timestamp = timestamp
        
        result.is_valid = result.error_count == 0
        
        return result
    
    def validate_funding_rates(
        self,
        rates: List[Dict[str, Any]]
    ) -> ValidationResult:
        """
        Validate funding rate data.
        
        Args:
            rates: List of funding rate dictionaries
            
        Returns:
            ValidationResult
        """
        result = ValidationResult(
            is_valid=True,
            total_records=len(rates),
            valid_records=0
        )
        
        if not rates:
            result.add_issue(
                ValidationLevel.WARNING,
                "EMPTY_DATA",
                "No funding rates to validate"
            )
            return result
        
        prev_timestamp = None
        
        for i, rate in enumerate(rates):
            is_valid = True
            
            timestamp = rate.get("timestamp")
            funding_rate = rate.get("funding_rate")
            
            # Check funding rate is present and reasonable
            if funding_rate is None:
                result.add_issue(
                    ValidationLevel.ERROR,
                    "MISSING_RATE",
                    "Missing funding rate",
                    timestamp=timestamp,
                    details={"rate_index": i}
                )
                is_valid = False
            elif abs(funding_rate) > 0.1:  # 10% is extreme
                result.add_issue(
                    ValidationLevel.WARNING,
                    "EXTREME_RATE",
                    f"Extreme funding rate: {funding_rate * 100:.4f}%",
                    timestamp=timestamp,
                    details={"rate_index": i}
                )
            
            # Check timestamp sequence
            if prev_timestamp and timestamp:
                if timestamp <= prev_timestamp:
                    result.add_issue(
                        ValidationLevel.WARNING,
                        "TIMESTAMP_NOT_SEQUENTIAL",
                        "Funding rate timestamp not sequential",
                        timestamp=timestamp,
                        details={"rate_index": i}
                    )
            
            if is_valid:
                result.valid_records += 1
            
            prev_timestamp = timestamp
        
        result.is_valid = result.error_count == 0
        
        return result


