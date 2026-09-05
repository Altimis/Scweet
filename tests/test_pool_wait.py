"""A run waits a bounded time for a cooldown to expire before it fails.

When every account holds a cooldown, the run does not have to end with `AccountPoolExhausted`. A cooldown
expires, so a short wait finishes a run that would otherwise fail. The wait is bounded by `pool_wait_max_s`,
and `pool_wait_max_s` of 0 keeps the old behaviour, which fails at once.
"""

import asyncio
from types import SimpleNamespace

import pytest

import Scweet.runner as runner_mod
from Scweet.runner import Runner


class _RepoReturningAfter:
    """acquire_leases returns [] for the first `empty_times` calls, then one account."""

    def __init__(self, empty_times):
        self.empty_times = empty_times
        self.calls = 0

    async def acquire_leases(self, count, run_id, worker_id_prefix):
        self.calls += 1
        if self.calls <= self.empty_times:
            return []
        return [{"username": "acct-a", "lease_id": "lease-a"}]


def _runner(repo, *, max_s, poll_s=5.0):
    return Runner(
        config=SimpleNamespace(pool_wait_max_s=max_s, pool_wait_poll_s=poll_s),
        repos={"accounts_repo": repo},
        engines={"api_engine": object()},
        outputs=None,
    )


@pytest.fixture()
def no_real_sleep(monkeypatch):
    slept = []

    async def _fake_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(runner_mod.asyncio, "sleep", _fake_sleep)
    return slept


class TestARunWaitsForACooldown:
    def test_it_retries_until_an_account_frees_up(self, no_real_sleep):
        repo = _RepoReturningAfter(empty_times=2)
        runner = _runner(repo, max_s=120.0, poll_s=5.0)

        accounts = asyncio.run(runner._acquire_leases_with_wait(1, "run-1"))

        assert len(accounts) == 1, "the run did not pick up the account that freed up"
        assert repo.calls == 3, "the run did not retry after an empty pool"
        assert no_real_sleep == [5.0, 5.0], "the run did not wait between attempts"

    def test_it_stops_at_the_bound_and_returns_empty(self, no_real_sleep):
        repo = _RepoReturningAfter(empty_times=1000)  # never frees up
        runner = _runner(repo, max_s=12.0, poll_s=5.0)

        accounts = asyncio.run(runner._acquire_leases_with_wait(1, "run-1"))

        assert accounts == [], "an empty pool past the bound must return empty so the run fails"
        # 12s bound with a 5s poll: waits 5, 5, then 2 to reach the bound, then one final attempt.
        assert sum(no_real_sleep) <= 12.0 + 0.01, "the wait exceeded the bound"
        assert len(no_real_sleep) >= 2

    def test_zero_bound_fails_at_once_without_waiting(self, no_real_sleep):
        repo = _RepoReturningAfter(empty_times=1000)
        runner = _runner(repo, max_s=0.0, poll_s=5.0)

        accounts = asyncio.run(runner._acquire_leases_with_wait(1, "run-1"))

        assert accounts == []
        assert repo.calls == 1, "with a zero bound the run must try once"
        assert no_real_sleep == [], "with a zero bound the run must not wait"
