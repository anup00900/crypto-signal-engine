"""
AWS Deployment Package for Crypto Data Collector

Components:
- collector: Main data collector (works locally and on Lambda)
- lambda_handler: AWS Lambda entry point (requires boto3)
- s3_storage: S3 upload/download utilities (requires boto3)
- signal_lambda: Signal engine (1-minute Binance signal computation)
"""

# Lazy imports to avoid pulling in heavy dependencies at package load time.
# The signal_lambda module does NOT need CryptoCollector or DeribitClient,
# so eager importing here would add ~100ms cold start overhead to the
# signal engine Lambda for no benefit.


def __getattr__(name):
    if name == "CryptoCollector":
        from .collector import CryptoCollector
        return CryptoCollector
    if name == "Config":
        from .collector import Config
        return Config
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "CryptoCollector",
    "Config",
]

