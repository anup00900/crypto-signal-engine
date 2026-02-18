"""
Top 10 cryptocurrency instruments configuration.
"""

from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum


class Exchange(Enum):
    """Supported exchanges."""
    DERIBIT = "deribit"
    BINANCE = "binance"


class Timeframe(Enum):
    """Supported timeframes."""
    SECOND_1 = "1s"
    MINUTE_1 = "1m"
    MINUTE_5 = "5m"
    MINUTE_15 = "15m"
    HOUR_1 = "1h"
    HOUR_4 = "4h"
    DAY_1 = "1d"


@dataclass
class InstrumentConfig:
    """Configuration for a single instrument."""
    
    symbol: str  # Base symbol (BTC, ETH, etc.)
    name: str  # Full name
    rank: int  # Market cap rank
    
    # Deribit instruments
    deribit_perpetual: str
    deribit_spot: Optional[str] = None
    
    # Binance instruments
    binance_spot: Optional[str] = None
    binance_futures: Optional[str] = None
    
    # CoinGecko ID for metadata
    coingecko_id: str = ""


# Top 10 Cryptocurrencies Configuration
TOP_10_INSTRUMENTS: List[InstrumentConfig] = [
    InstrumentConfig(
        symbol="BTC",
        name="Bitcoin",
        rank=1,
        deribit_perpetual="BTC-PERPETUAL",
        deribit_spot="BTC_USDC",
        binance_spot="BTCUSDT",
        binance_futures="BTCUSDT",
        coingecko_id="bitcoin"
    ),
    InstrumentConfig(
        symbol="ETH",
        name="Ethereum",
        rank=2,
        deribit_perpetual="ETH-PERPETUAL",
        deribit_spot="ETH_USDC",
        binance_spot="ETHUSDT",
        binance_futures="ETHUSDT",
        coingecko_id="ethereum"
    ),
    InstrumentConfig(
        symbol="SOL",
        name="Solana",
        rank=3,
        deribit_perpetual="SOL-PERPETUAL",
        deribit_spot="SOL_USDC",
        binance_spot="SOLUSDT",
        binance_futures="SOLUSDT",
        coingecko_id="solana"
    ),
    InstrumentConfig(
        symbol="XRP",
        name="XRP",
        rank=4,
        deribit_perpetual="XRP-PERPETUAL",
        deribit_spot="XRP_USDC",
        binance_spot="XRPUSDT",
        binance_futures="XRPUSDT",
        coingecko_id="ripple"
    ),
    InstrumentConfig(
        symbol="DOGE",
        name="Dogecoin",
        rank=5,
        deribit_perpetual="DOGE-PERPETUAL",
        deribit_spot="DOGE_USDC",
        binance_spot="DOGEUSDT",
        binance_futures="DOGEUSDT",
        coingecko_id="dogecoin"
    ),
    InstrumentConfig(
        symbol="ADA",
        name="Cardano",
        rank=6,
        deribit_perpetual="ADA-PERPETUAL",
        deribit_spot="ADA_USDC",
        binance_spot="ADAUSDT",
        binance_futures="ADAUSDT",
        coingecko_id="cardano"
    ),
    InstrumentConfig(
        symbol="AVAX",
        name="Avalanche",
        rank=7,
        deribit_perpetual="AVAX-PERPETUAL",
        deribit_spot="AVAX_USDC",
        binance_spot="AVAXUSDT",
        binance_futures="AVAXUSDT",
        coingecko_id="avalanche-2"
    ),
    InstrumentConfig(
        symbol="LINK",
        name="Chainlink",
        rank=8,
        deribit_perpetual="LINK-PERPETUAL",
        deribit_spot="LINK_USDC",
        binance_spot="LINKUSDT",
        binance_futures="LINKUSDT",
        coingecko_id="chainlink"
    ),
    InstrumentConfig(
        symbol="DOT",
        name="Polkadot",
        rank=9,
        deribit_perpetual="DOT-PERPETUAL",
        deribit_spot="DOT_USDC",
        binance_spot="DOTUSDT",
        binance_futures="DOTUSDT",
        coingecko_id="polkadot"
    ),
    InstrumentConfig(
        symbol="MATIC",
        name="Polygon",
        rank=10,
        deribit_perpetual="MATIC-PERPETUAL",
        deribit_spot="MATIC_USDC",
        binance_spot="MATICUSDT",
        binance_futures="MATICUSDT",
        coingecko_id="matic-network"
    ),
]

# Timeframe configurations
TIMEFRAMES: Dict[Timeframe, Dict] = {
    Timeframe.SECOND_1: {
        "resolution": "1",  # Not directly supported - aggregated from trades
        "seconds": 1,
        "deribit_resolution": None,  # Must be aggregated from trades
        "binance_interval": None,  # Must be aggregated from trades
        "description": "1 Second (aggregated from trades)"
    },
    Timeframe.MINUTE_1: {
        "resolution": "1",
        "seconds": 60,
        "deribit_resolution": "1",
        "binance_interval": "1m",
        "description": "1 Minute"
    },
    Timeframe.MINUTE_5: {
        "resolution": "5",
        "seconds": 300,
        "deribit_resolution": "5",
        "binance_interval": "5m",
        "description": "5 Minutes"
    },
    Timeframe.MINUTE_15: {
        "resolution": "15",
        "seconds": 900,
        "deribit_resolution": "15",
        "binance_interval": "15m",
        "description": "15 Minutes"
    },
    Timeframe.HOUR_1: {
        "resolution": "60",
        "seconds": 3600,
        "deribit_resolution": "60",
        "binance_interval": "1h",
        "description": "1 Hour"
    },
    Timeframe.HOUR_4: {
        "resolution": "240",
        "seconds": 14400,
        "deribit_resolution": "240",
        "binance_interval": "4h",
        "description": "4 Hours"
    },
    Timeframe.DAY_1: {
        "resolution": "1D",
        "seconds": 86400,
        "deribit_resolution": "1D",
        "binance_interval": "1d",
        "description": "1 Day"
    },
}


def get_instrument_by_symbol(symbol: str) -> Optional[InstrumentConfig]:
    """Get instrument configuration by symbol."""
    for instrument in TOP_10_INSTRUMENTS:
        if instrument.symbol == symbol.upper():
            return instrument
    return None


def get_all_deribit_perpetuals() -> List[str]:
    """Get list of all Deribit perpetual instruments."""
    return [inst.deribit_perpetual for inst in TOP_10_INSTRUMENTS]


def get_all_binance_futures() -> List[str]:
    """Get list of all Binance futures instruments."""
    return [inst.binance_futures for inst in TOP_10_INSTRUMENTS if inst.binance_futures]


def get_timeframe_seconds(timeframe: Timeframe) -> int:
    """Get number of seconds for a timeframe."""
    return TIMEFRAMES[timeframe]["seconds"]


