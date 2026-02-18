"""
Data collectors for various cryptocurrency exchanges.
"""

from collectors.base import BaseCollector, CollectionResult
from collectors.deribit import DeribitClient, DeribitOHLCVCollector, DeribitTradesCollector

__all__ = [
    'BaseCollector',
    'CollectionResult',
    'DeribitClient',
    'DeribitOHLCVCollector',
    'DeribitTradesCollector'
]


