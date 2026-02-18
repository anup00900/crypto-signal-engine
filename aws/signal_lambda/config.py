"""
Configuration for Signal Engine Lambda
"""

# Symbols to track
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

# Binance Futures REST base URL (no auth needed)
BINANCE_FUTURES_BASE = "https://fapi.binance.com/fapi/v1"

# S3 key prefix for all signal data
S3_PREFIX = "signals"

# Rolling buffer sizes (rows per symbol, ~25 hours of 1m candles)
ROLLING_CANDLE_LIMIT = 1500
ROLLING_DERIV_LIMIT = 1500
ROLLING_LIQUIDATION_LIMIT = 500

# Signal weights for TDS computation
SIGNAL_WEIGHTS = {
    "vep": 0.22,
    "sci": 0.20,
    "lcs": 0.18,
    "flow": 0.12,
    "dps": 0.10,
    "grav": 0.10,
    "cap": 0.08,
}

# Volume profile recomputation interval (minutes)
VOLUME_PROFILE_INTERVAL_MIN = 5

# Price bin size for volume profile histogram
VOLUME_PROFILE_BIN_SIZE = {
    "BTCUSDT": 10.0,
    "ETHUSDT": 1.0,
}
