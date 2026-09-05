"""A failed write of an account must not report success.

`_attempt_account_repair` wrote the repaired account, swallowed any error from the write, then logged
"Account repair succeeded" and returned True. An operator who reads the log believes the pool holds a repaired
account, and the account is not there. This is the worst of the swallowed handlers in the package, because it
prints a false success after a lost write.
"""

import asyncio
import logging
from types import SimpleNamespace

import pytest

from Scweet.runner import Runner


class _ListHandler(logging.Handler):
    """Capture records straight off a named logger.

    `caplog` attaches to the root logger, and `Scweet/logging_config.py` sets `propagate = False` on the Scweet
    logger, so a record never reaches the root once logging is configured. A handler on the logger itself
    captures the record whatever the propagation setting is.
    """

    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


@pytest.fixture()
def runner_logs():
    logger = logging.getLogger("Scweet.runner")
    handler = _ListHandler()
    logger.addHandler(handler)
    previous_level = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)


def _runner_with_repo(repo):
    return Runner(
        config=SimpleNamespace(
            n_splits=1,
            concurrency=1,
            scheduler_min_interval_s=300,
            requests_per_min=10_000,
            min_delay_s=0.0,
            proxy=None,
        ),
        repos={"accounts_repo": repo},
        engines={"api_engine": object()},
        outputs=None,
    )


class _RepoThatFailsToWrite:
    """`upsert_account` raises, as a real write does when the disk or the schema rejects it."""

    def upsert_account(self, record):
        raise RuntimeError("disk is full")


class _RepoThatWrites:
    def __init__(self):
        self.written = []

    def upsert_account(self, record):
        self.written.append(record)


@pytest.fixture()
def fake_cookies(monkeypatch):
    async def _bootstrap(auth_token, timeout_s=30, **_kwargs):
        return {"auth_token": auth_token, "ct0": "csrf-new", "guest_id": "g-1"}

    import Scweet.runner as runner_mod

    monkeypatch.setattr(runner_mod, "_bootstrap_token_async", _bootstrap)


class TestAFailedRepairDoesNotReportSuccess:
    def test_a_failed_write_returns_false(self, fake_cookies):
        runner = _runner_with_repo(_RepoThatFailsToWrite())
        account = {"username": "acct-a", "auth_token": "tok-a"}

        repaired = asyncio.run(runner._attempt_account_repair(account, 401))

        assert repaired is False, "a repair whose write failed must not return True"

    def test_a_failed_write_does_not_log_success(self, fake_cookies, runner_logs):
        runner = _runner_with_repo(_RepoThatFailsToWrite())
        account = {"username": "acct-a", "auth_token": "tok-a"}

        asyncio.run(runner._attempt_account_repair(account, 401))

        assert not any("repair succeeded" in r.getMessage().lower() for r in runner_logs), (
            "the log claimed the repair succeeded after the write failed"
        )

    def test_a_failed_write_logs_the_failure(self, fake_cookies, runner_logs):
        runner = _runner_with_repo(_RepoThatFailsToWrite())
        account = {"username": "acct-a", "auth_token": "tok-a"}

        asyncio.run(runner._attempt_account_repair(account, 401))

        assert any(
            r.levelno >= logging.WARNING and "acct-a" in r.getMessage() for r in runner_logs
        ), "a failed write left no warning, so an operator cannot see the lost account"


class TestARealRepairStillSucceeds:
    def test_a_successful_write_returns_true_and_persists(self, fake_cookies):
        repo = _RepoThatWrites()
        runner = _runner_with_repo(repo)
        account = {"username": "acct-b", "auth_token": "tok-b"}

        repaired = asyncio.run(runner._attempt_account_repair(account, 401))

        assert repaired is True
        assert len(repo.written) == 1

    def test_a_successful_write_logs_success(self, fake_cookies, runner_logs):
        repo = _RepoThatWrites()
        runner = _runner_with_repo(repo)
        account = {"username": "acct-b", "auth_token": "tok-b"}

        asyncio.run(runner._attempt_account_repair(account, 401))

        assert any("repair succeeded" in r.getMessage().lower() for r in runner_logs)
