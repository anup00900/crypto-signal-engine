"""
Rate limiting utilities for API requests.
"""

import asyncio
import time
from collections import deque
from threading import Lock
from typing import Optional

from loguru import logger


class RateLimiter:
    """
    Thread-safe rate limiter for synchronous API calls.
    
    Uses a sliding window algorithm to enforce rate limits.
    
    Usage:
        limiter = RateLimiter(max_requests=10, window_seconds=1)
        
        for item in items:
            limiter.wait()  # Blocks if rate limit exceeded
            make_api_call(item)
    """
    
    def __init__(
        self, 
        max_requests: int = 10, 
        window_seconds: float = 1.0,
        min_interval_ms: Optional[int] = None
    ):
        """
        Initialize rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
            min_interval_ms: Minimum interval between requests in milliseconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.min_interval = min_interval_ms / 1000 if min_interval_ms else 0
        
        self._timestamps: deque = deque()
        self._lock = Lock()
        self._last_request_time = 0.0
        
        self._total_requests = 0
        self._total_wait_time = 0.0
    
    def wait(self) -> float:
        """
        Wait if necessary to comply with rate limit.
        
        Returns:
            Time waited in seconds
        """
        wait_time = 0.0
        
        with self._lock:
            now = time.time()
            
            # Remove timestamps outside the window
            cutoff = now - self.window_seconds
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            
            # Check if we need to wait due to rate limit
            if len(self._timestamps) >= self.max_requests:
                # Wait until oldest request is outside window
                wait_time = self._timestamps[0] + self.window_seconds - now
                if wait_time > 0:
                    logger.debug(f"Rate limit: waiting {wait_time:.3f}s")
                    time.sleep(wait_time)
                    self._total_wait_time += wait_time
                    now = time.time()
                    
                    # Clean up again after wait
                    cutoff = now - self.window_seconds
                    while self._timestamps and self._timestamps[0] < cutoff:
                        self._timestamps.popleft()
            
            # Check minimum interval
            if self.min_interval > 0:
                time_since_last = now - self._last_request_time
                if time_since_last < self.min_interval:
                    interval_wait = self.min_interval - time_since_last
                    time.sleep(interval_wait)
                    wait_time += interval_wait
                    self._total_wait_time += interval_wait
                    now = time.time()
            
            # Record this request
            self._timestamps.append(now)
            self._last_request_time = now
            self._total_requests += 1
        
        return wait_time
    
    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        return {
            "total_requests": self._total_requests,
            "total_wait_time": self._total_wait_time,
            "avg_wait_time": self._total_wait_time / max(1, self._total_requests),
            "current_window_requests": len(self._timestamps)
        }
    
    def reset(self):
        """Reset the rate limiter."""
        with self._lock:
            self._timestamps.clear()
            self._last_request_time = 0.0


class AsyncRateLimiter:
    """
    Async rate limiter for asynchronous API calls.
    
    Usage:
        limiter = AsyncRateLimiter(max_requests=10, window_seconds=1)
        
        async for item in items:
            await limiter.wait()
            await make_api_call(item)
    """
    
    def __init__(
        self, 
        max_requests: int = 10, 
        window_seconds: float = 1.0,
        min_interval_ms: Optional[int] = None
    ):
        """
        Initialize async rate limiter.
        
        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Time window in seconds
            min_interval_ms: Minimum interval between requests in milliseconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.min_interval = min_interval_ms / 1000 if min_interval_ms else 0
        
        self._timestamps: deque = deque()
        self._lock = asyncio.Lock()
        self._last_request_time = 0.0
        
        self._total_requests = 0
        self._total_wait_time = 0.0
    
    async def wait(self) -> float:
        """
        Wait if necessary to comply with rate limit.
        
        Returns:
            Time waited in seconds
        """
        wait_time = 0.0
        
        async with self._lock:
            now = time.time()
            
            # Remove timestamps outside the window
            cutoff = now - self.window_seconds
            while self._timestamps and self._timestamps[0] < cutoff:
                self._timestamps.popleft()
            
            # Check if we need to wait due to rate limit
            if len(self._timestamps) >= self.max_requests:
                wait_time = self._timestamps[0] + self.window_seconds - now
                if wait_time > 0:
                    logger.debug(f"Rate limit: waiting {wait_time:.3f}s")
                    await asyncio.sleep(wait_time)
                    self._total_wait_time += wait_time
                    now = time.time()
                    
                    cutoff = now - self.window_seconds
                    while self._timestamps and self._timestamps[0] < cutoff:
                        self._timestamps.popleft()
            
            # Check minimum interval
            if self.min_interval > 0:
                time_since_last = now - self._last_request_time
                if time_since_last < self.min_interval:
                    interval_wait = self.min_interval - time_since_last
                    await asyncio.sleep(interval_wait)
                    wait_time += interval_wait
                    self._total_wait_time += interval_wait
                    now = time.time()
            
            # Record this request
            self._timestamps.append(now)
            self._last_request_time = now
            self._total_requests += 1
        
        return wait_time
    
    def get_stats(self) -> dict:
        """Get rate limiter statistics."""
        return {
            "total_requests": self._total_requests,
            "total_wait_time": self._total_wait_time,
            "avg_wait_time": self._total_wait_time / max(1, self._total_requests),
            "current_window_requests": len(self._timestamps)
        }
    
    def reset(self):
        """Reset the rate limiter."""
        self._timestamps.clear()
        self._last_request_time = 0.0


# Pre-configured rate limiters for different exchanges
class ExchangeRateLimiters:
    """Factory for exchange-specific rate limiters."""
    
    @staticmethod
    def deribit_public() -> RateLimiter:
        """Deribit public API: 20 requests/second."""
        return RateLimiter(max_requests=20, window_seconds=1.0, min_interval_ms=50)
    
    @staticmethod
    def deribit_authenticated() -> RateLimiter:
        """Deribit authenticated API: 100 requests/second."""
        return RateLimiter(max_requests=100, window_seconds=1.0, min_interval_ms=10)
    
    @staticmethod
    def binance() -> RateLimiter:
        """Binance API: 1200 requests/minute."""
        return RateLimiter(max_requests=1200, window_seconds=60.0, min_interval_ms=50)
    
    @staticmethod
    def coingecko_free() -> RateLimiter:
        """CoinGecko free API: 10-30 requests/minute."""
        return RateLimiter(max_requests=10, window_seconds=60.0, min_interval_ms=6000)
    
    @staticmethod
    def coingecko_pro() -> RateLimiter:
        """CoinGecko Pro API: 500 requests/minute."""
        return RateLimiter(max_requests=500, window_seconds=60.0, min_interval_ms=120)


class AsyncExchangeRateLimiters:
    """Factory for exchange-specific async rate limiters."""
    
    @staticmethod
    def deribit_public() -> AsyncRateLimiter:
        """Deribit public API: 20 requests/second."""
        return AsyncRateLimiter(max_requests=20, window_seconds=1.0, min_interval_ms=50)
    
    @staticmethod
    def deribit_authenticated() -> AsyncRateLimiter:
        """Deribit authenticated API: 100 requests/second."""
        return AsyncRateLimiter(max_requests=100, window_seconds=1.0, min_interval_ms=10)
    
    @staticmethod
    def binance() -> AsyncRateLimiter:
        """Binance API: 1200 requests/minute."""
        return AsyncRateLimiter(max_requests=1200, window_seconds=60.0, min_interval_ms=50)


