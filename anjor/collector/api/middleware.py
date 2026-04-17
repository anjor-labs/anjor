"""Rate-limiting middleware for the Anjor collector API.

Token bucket per client IP, applied only to POST /events.
All other endpoints are unrestricted (read-only dashboard traffic).
"""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class _TokenBucket:
    """Thread-unsafe token bucket — safe in asyncio (no await between read/write)."""

    __slots__ = ("_burst", "_buckets", "_rps")

    def __init__(self, rps: float, burst: int) -> None:
        self._rps = rps
        self._burst = burst
        self._buckets: dict[str, tuple[float, float]] = {}

    def consume(self, key: str) -> bool:
        """Return True if the request is allowed; False if rate-limited."""
        now = time.monotonic()
        tokens, last = self._buckets.get(key, (float(self._burst), now))
        tokens = min(float(self._burst), tokens + (now - last) * self._rps)
        if tokens < 1.0:
            self._buckets[key] = (tokens, now)
            return False
        self._buckets[key] = (tokens - 1.0, now)
        return True


class EventsRateLimitMiddleware(BaseHTTPMiddleware):
    """Token-bucket rate limiter applied only to POST /events.

    Args:
        rps:   Sustained refill rate — tokens per second per source IP.
        burst: Bucket capacity — max tokens that can accumulate.

    Returns 429 with a ``Retry-After: 1`` header when the bucket is empty.
    """

    def __init__(self, app: object, *, rps: float, burst: int) -> None:
        super().__init__(app)  # type: ignore
        self._bucket = _TokenBucket(rps=float(rps), burst=burst)

    async def dispatch(self, request: Request, call_next: object) -> Response:
        if request.method == "POST" and request.url.path == "/events":
            ip = request.client.host if request.client else "127.0.0.1"
            if not self._bucket.consume(ip):
                return JSONResponse(
                    {"detail": "Rate limit exceeded — reduce event frequency."},
                    status_code=429,
                    headers={"Retry-After": "1"},
                )
        return await call_next(request)  # type: ignore
