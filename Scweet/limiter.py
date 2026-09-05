from __future__ import annotations

import asyncio
import time


class TokenBucketLimiter:
    """A per-account token bucket that paces to the window of X, not to the gap between two requests.

    X counts the total number of requests inside a window of about 15 minutes for each account, and not the time
    between two requests. So the bucket holds the budget of one window (`capacity`) and refills it over the whole
    window (`refill_window_s`). The bucket starts full, so a short run spends its few requests at once and waits
    nothing, and a long run slows to the refill rate once the window budget is gone.

    An earlier version refilled `capacity` over 60 seconds and forced a fixed delay between two requests. That
    made a short run slow for no benefit, and it let a long run exceed the window of X, which returns 429 and
    removes the account. Measured on a comparable engine: an even delay made a run of 400 tweets take 373 seconds
    instead of 41.

    `min_delay_s` stays as an optional floor between two requests. It defaults to 0, so it adds no delay unless a
    caller sets it.
    """

    def __init__(self, *, capacity: int, refill_window_s: float = 60.0, min_delay_s: float = 0.0) -> None:
        self.capacity = max(1, int(capacity))
        self.tokens = float(self.capacity)
        self.refill_rate = self.capacity / max(1.0, float(refill_window_s))
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
                    if self.min_delay_s > 0 and since_last < self.min_delay_s:
                        wait_s = self.min_delay_s - since_last
                    else:
                        self.tokens -= 1.0
                        self._last_request_at = time.monotonic()
                        return

            if wait_s > 0:
                await asyncio.sleep(wait_s)
