"""
Rate Limiter with Token Bucket Algorithm
Protects services from abuse by enforcing request quotas per IP.
Uses Redis for distributed rate limit tracking.
"""

import json
import time
from typing import Optional, Tuple

from gateway.redis_client import redis_client


class TokenBucketRateLimiter:
    """
    Token bucket algorithm for rate limiting.

    ALGORITHM:
    ----------
    A "bucket" holds up to `capacity` tokens.
    Tokens refill at a constant rate (e.g., 100 tokens/minute).
    Each request consumes 1 token.
    If no tokens available → request rejected with 429.

    PROS:
    - Handles bursts gracefully (up to capacity)
    - Fair for different request patterns
    - Easy to understand and tune

    CONS:
    - Requires state persistence (Redis)
    - Must update bucket on every request

    EXAMPLE:
    --------
    limiter = TokenBucketRateLimiter(
        rate=100,              # tokens per minute
        capacity=100,          # max burst
        window_seconds=60      # refill window
    )

    allowed = await limiter.is_allowed("192.168.1.1")
    if not allowed:
        return 429 Too Many Requests
    """

    def __init__(
        self,
        rate: int = 100,           # tokens per window
        capacity: int = 100,       # bucket capacity
        window_seconds: int = 60,  # refill window (seconds)
    ):
        """
        Initialize the token bucket limiter.

        Args:
            rate: Number of tokens added per window (e.g., 100 requests/minute)
            capacity: Maximum tokens in bucket (allows bursts up to this)
            window_seconds: Time window for refill (e.g., 60 for per-minute)
        """
        self.rate = rate
        self.capacity = capacity
        self.window_seconds = window_seconds
        self.refill_rate = rate / window_seconds  # tokens per second

    async def is_allowed(self, identifier: str) -> Tuple[bool, dict]:
        """
        Check if a request from the given identifier is allowed.

        Uses Redis hash to store bucket state:
        - tokens: current token count
        - last_refill: timestamp of last refill

        Args:
            identifier: Unique identifier (e.g., IP address)

        Returns:
            (allowed: bool, state: dict with tokens, limit, window)
        """
        try:
            bucket_key = f"ratelimit:{identifier}"

            # Get current bucket state
            bucket_data = await redis_client.hgetall(bucket_key)

            if bucket_data:
                tokens = float(bucket_data.get("tokens", 0))
                last_refill = float(bucket_data.get("last_refill", 0))
            else:
                # First request from this IP
                tokens = self.capacity
                last_refill = time.time()

            now = time.time()
            elapsed = now - last_refill

            # Refill tokens based on time elapsed
            refilled_tokens = elapsed * self.refill_rate
            tokens = min(self.capacity, tokens + refilled_tokens)

            # Check if request is allowed
            if tokens >= 1:
                tokens -= 1  # Consume 1 token
                allowed = True
            else:
                allowed = False

            # Update bucket in Redis (no expiry = persistent until traffic stops)
            await redis_client.hset(
                bucket_key,
                mapping={
                    "tokens": str(tokens),
                    "last_refill": str(now),
                },
            )

            state = {
                "allowed": allowed,
                "tokens_remaining": int(tokens),
                "capacity": self.capacity,
                "rate": f"{self.rate}/{self.window_seconds}s",
                "identifier": identifier,
            }

            return allowed, state

        except RuntimeError as e:
            # If event loop is closed, still log and fail-open
            if "Event loop is closed" in str(e):
                print(f"⚠️  Rate limiter Redis error (event loop closed): {e}")
                return True, {"error": "event_loop_closed"}
            raise
        except Exception as e:
            # If Redis fails, fail open (allow request, log error)
            print(f"⚠️  Rate limiter Redis error: {e}")
            return True, {"error": "rate_limiter_unavailable"}


class SlidingWindowRateLimiter:
    """
    Sliding window algorithm for rate limiting.

    ALGORITHM:
    ----------
    Maintain a list of request timestamps in Redis.
    For each new request:
    1. Remove timestamps older than window size
    2. Count remaining timestamps
    3. If count < limit → allow and add new timestamp
    4. Else → reject

    PROS:
    - More precise rate limiting (exact window)
    - No burst allowance (stricter)
    - Familiar to many systems

    CONS:
    - Requires list operations (less efficient)
    - More data in Redis
    - Less burst-friendly

    EXAMPLE:
    --------
    limiter = SlidingWindowRateLimiter(
        limit=100,            # max requests
        window_seconds=60     # per time window
    )

    allowed = await limiter.is_allowed("192.168.1.1")
    """

    def __init__(self, limit: int = 100, window_seconds: int = 60):
        """
        Initialize the sliding window limiter.

        Args:
            limit: Maximum requests per window
            window_seconds: Time window size (seconds)
        """
        self.limit = limit
        self.window_seconds = window_seconds

    async def is_allowed(self, identifier: str) -> Tuple[bool, dict]:
        """
        Check if a request from the given identifier is allowed.

        Uses Redis list to store request timestamps.

        Args:
            identifier: Unique identifier (e.g., IP address)

        Returns:
            (allowed: bool, state: dict with request_count, limit, window)
        """
        try:
            request_key = f"ratelimit:window:{identifier}"
            now = int(time.time() * 1000)  # milliseconds for precision
            window_start = now - (self.window_seconds * 1000)

            # Remove old requests outside window
            await redis_client.zremrangebyscore(request_key, 0, window_start)

            # Count requests in current window
            request_count = await redis_client.zcard(request_key)

            # Check if allowed
            if request_count < self.limit:
                # Add this request timestamp
                await redis_client.zadd(request_key, {str(now): now})
                # Set expiry to window size
                await redis_client.expire(request_key, self.window_seconds)
                allowed = True
            else:
                allowed = False

            state = {
                "allowed": allowed,
                "requests_made": request_count,
                "limit": self.limit,
                "window_seconds": self.window_seconds,
                "identifier": identifier,
            }

            return allowed, state

        except Exception as e:
            # If Redis fails, fail open
            print(f"⚠️  Rate limiter Redis error: {e}")
            return True, {"error": "rate_limiter_unavailable"}


class RateLimiterManager:
    """
    Manage rate limiting for the gateway.
    Supports both token bucket and sliding window.
    """

    def __init__(
        self,
        algorithm: str = "token_bucket",
        rate: int = 100,
        capacity: int = 100,
        window_seconds: int = 60,
    ):
        """
        Initialize rate limiter manager.

        Args:
            algorithm: "token_bucket" or "sliding_window"
            rate: Tokens/requests per window
            capacity: Bucket capacity (for token bucket)
            window_seconds: Window size in seconds
        """
        self.algorithm = algorithm

        if algorithm == "token_bucket":
            self.limiter = TokenBucketRateLimiter(
                rate=rate,
                capacity=capacity,
                window_seconds=window_seconds,
            )
        elif algorithm == "sliding_window":
            self.limiter = SlidingWindowRateLimiter(
                limit=rate,
                window_seconds=window_seconds,
            )
        else:
            raise ValueError(f"Unknown algorithm: {algorithm}")

    async def check_limit(self, identifier: str) -> Tuple[bool, dict]:
        """Check if request is allowed."""
        return await self.limiter.is_allowed(identifier)
