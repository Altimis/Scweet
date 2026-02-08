from __future__ import annotations

import asyncio
import time


class TokenBucketLimiter:
    """Per-account token bucket limiter with optional min-delay pacing."""

    def __init__(self, *, requests_per_min: int, min_delay_s: float) -> None:
        self.capacity = max(1, int(requests_per_min))
        self.tokens = float(self.capacity)
        self.refill_rate = self.capacity / 60.0
        self.min_delay_s = max(0.0, float(min_delay_s))
        self._lock = asyncio.Lock()
        self._last_refill = time.monotonic()
        self._last_request_at = 0.0

    async def acquire(self) -> None:
        while True:
            wait_s = 0.0
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                if elapsed > 0:
                    self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
                    self._last_refill = now

                if self.tokens < 1.0:
                    wait_s = (1.0 - self.tokens) / self.refill_rate
                else:
                    since_last = now - self._last_request_at
                    if since_last < self.min_delay_s:
                        wait_s = self.min_delay_s - since_last
                    else:
                        self.tokens -= 1.0
                        self._last_request_at = time.monotonic()
                        return

            if wait_s > 0:
                await asyncio.sleep(wait_s)
