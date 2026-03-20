from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

from Scweet.cooldown import (
    compute_cooldown,
    effective_status_with_rate_limit_headers,
    parse_rate_limit_remaining,
    parse_rate_limit_reset,
)
from Scweet.limiter import TokenBucketLimiter


def _cooldown_config(**overrides):
    defaults = {
        "cooldown_default_s": 120,
        "transient_cooldown_s": 90,
        "auth_cooldown_s": 3600,
        "cooldown_jitter_s": 0,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_parse_rate_limit_reset_handles_supported_cases():
    assert parse_rate_limit_reset(None) is None
    assert parse_rate_limit_reset({}) is None
    assert parse_rate_limit_reset({"x-rate-limit-reset": "1700000100"}) == 1700000100
    assert parse_rate_limit_reset({"X-Rate-Limit-Reset": "1700000200"}) == 1700000200
    assert parse_rate_limit_reset({"x-rate-limit-reset": "not-an-int"}) is None


def test_parse_rate_limit_remaining_handles_supported_cases():
    assert parse_rate_limit_remaining(None) is None
    assert parse_rate_limit_remaining({}) is None
    assert parse_rate_limit_remaining({"x-rate-limit-remaining": "10"}) == 10
    assert parse_rate_limit_remaining({"X-Rate-Limit-Remaining": "0"}) == 0
    assert parse_rate_limit_remaining({"x-rate-limit-remaining": "not-an-int"}) is None


def test_effective_status_with_rate_limit_headers_marks_exhausted_remaining_as_429():
    assert effective_status_with_rate_limit_headers(200, {"x-rate-limit-remaining": "0"}) == 429
    assert effective_status_with_rate_limit_headers(200, {"x-rate-limit-remaining": "-1"}) == 429
    assert effective_status_with_rate_limit_headers(200, {"x-rate-limit-remaining": "1"}) == 200
    assert effective_status_with_rate_limit_headers(429, {"x-rate-limit-remaining": "10"}) == 429
    assert effective_status_with_rate_limit_headers(503, {"x-rate-limit-remaining": "0"}) == 503


def test_compute_cooldown_maps_auth_rate_limit_transient_and_success():
    cfg = _cooldown_config()
    now = time.time()

    status_auth, until_auth, reason_auth = compute_cooldown(401, headers=None, config=cfg)
    assert status_auth == 401
    assert reason_auth == "auth_failed"
    assert until_auth >= now + 3599

    reset_ts = int(now + 77)
    status_rl, until_rl, reason_rl = compute_cooldown(
        429,
        headers={"x-rate-limit-reset": str(reset_ts)},
        config=cfg,
    )
    assert status_rl == 1
    assert until_rl == float(reset_ts)
    assert reason_rl == "rate_limit"

    status_rl_default, until_rl_default, reason_rl_default = compute_cooldown(429, headers=None, config=cfg)
    assert status_rl_default == 1
    assert reason_rl_default == "rate_limit"
    assert until_rl_default >= now + 119

    status_transient, until_transient, reason_transient = compute_cooldown(503, headers=None, config=cfg)
    assert status_transient == 1
    assert reason_transient == "transient"
    assert until_transient >= now + 89

    status_network, until_network, reason_network = compute_cooldown(599, headers=None, config=cfg)
    assert status_network == 1
    assert reason_network == "transient"
    assert until_network >= now + 89

    status_ok, until_ok, reason_ok = compute_cooldown(200, headers=None, config=cfg)
    assert status_ok == 1
    assert until_ok == 0.0
    assert reason_ok is None


class _FakeClock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    async def sleep(self, seconds: float):
        self.now += seconds


def test_token_bucket_limiter_applies_min_delay_and_refill(monkeypatch):
    import Scweet.limiter as limiter_mod

    clock = _FakeClock()
    monkeypatch.setattr(limiter_mod.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(limiter_mod.asyncio, "sleep", clock.sleep)

    async def _run():
        paced = TokenBucketLimiter(requests_per_min=120, min_delay_s=0.5)
        await paced.acquire()  # immediate
        await paced.acquire()  # min-delay paced
        assert clock.now == 100.5

        refill = TokenBucketLimiter(requests_per_min=2, min_delay_s=0.0)
        await refill.acquire()  # consume token 1
        await refill.acquire()  # consume token 2
        await refill.acquire()  # wait for refill (30s at 2/min)
        assert clock.now == 130.5

    asyncio.run(_run())
