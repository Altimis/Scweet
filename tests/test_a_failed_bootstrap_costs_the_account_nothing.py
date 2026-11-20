"""A failed build of the transaction id costs the account nothing, and a retry reaches a new exit.

Measured 2026-11-20 with one account and a rotating proxy: the first search of a new state file returned
0 tweets, its account took a cooldown, and the next call raised AccountPoolExhausted. A rerun two minutes
later gave 100 of 100. The bootstrap filled `{session}` once for the life of the provider, so each attempt
reached the same exit; the requests then left without the header, X answered 404, and that 404 put the only
account to rest and ended the task.
"""

from __future__ import annotations

import asyncio
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock

from Scweet.api_engine import ApiEngine
from Scweet.cooldown import compute_cooldown
from Scweet.http_utils import NO_SIGNATURE_DETAIL, UNSIGNED_REQUEST_STATUS
from Scweet.models import SearchRequest, SearchResult, TweetRecord
from Scweet.runner import Runner
from Scweet.transaction import TransactionIdProvider

_HOME_HTML_WITH_ONDEMAND = (
    '<html><head></head><body>'
    '<script>var a={,123:"ondemand.s",456:"other"};var b={123:"abc123def456",456:"xyz"};</script>'
    '</body></html>'
)


class _ProxySession:
    """Keeps the proxies that the bootstrap gives it."""

    def __init__(self):
        self.headers = {}
        self.proxies = {}

    def get(self, url, **kwargs):
        return SimpleNamespace(status_code=200, text="ondemand js", url=url)

    def close(self):
        pass


def test_each_bootstrap_attempt_reaches_a_new_exit(monkeypatch):
    from bs4 import BeautifulSoup

    monkeypatch.delenv("SCWEET_X_CLIENT_TRANSACTION_ID", raising=False)
    calls = {"n": 0}

    def _migration(session):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TimeoutError("curl: (28) Connection timed out after 20001 milliseconds")
        return BeautifulSoup(_HOME_HTML_WITH_ONDEMAND, "html.parser")

    generator = MagicMock()
    generator.generate_transaction_id.return_value = "tx-from-the-second-exit"
    xct = types.ModuleType("x_client_transaction")
    xct.ClientTransaction = MagicMock(return_value=generator)
    utils = types.ModuleType("x_client_transaction.utils")
    utils.handle_x_migration = _migration
    monkeypatch.setitem(sys.modules, "x_client_transaction", xct)
    monkeypatch.setitem(sys.modules, "x_client_transaction.utils", utils)

    sessions: list[_ProxySession] = []

    def _factory():
        sessions.append(_ProxySession())
        return sessions[-1]

    provider = TransactionIdProvider(
        proxy="http://user,session-{session}:secret@proxy.example:8000",
        session_factory=_factory,
        prefer_curl_cffi=False,
        init_attempts=3,
        init_backoff_s=0.0,
    )

    assert provider.generate(method="GET", path="/i/api/graphql/x/SearchTimeline") == "tx-from-the-second-exit"
    assert len(sessions) == 2
    first, second = (s.proxies.get("https") for s in sessions)
    assert "{session}" not in first and "{session}" not in second
    assert first != second, "the retry used the exit of the failed attempt"


class _AlwaysNotFound:
    async def get(self, url, **kwargs):
        return SimpleNamespace(status_code=404, text="", headers={})

    async def close(self):
        pass


class _Provider:
    def __init__(self, tx_id):
        self.enabled = True
        self._tx_id = tx_id

    def generate(self, *, method: str, path: str):
        return self._tx_id

    def refresh(self):
        return False


def _get(provider):
    session = _AlwaysNotFound()
    engine = ApiEngine(
        config={"request_404_retries": 0},
        accounts_repo=None,
        manifest_provider=None,
        session_factory=lambda: session,
        transaction_id_provider=provider,
    )
    return asyncio.run(
        engine._graphql_get(url="https://x.com/i/api/graphql/x/SearchTimeline", params={}, timeout_s=5, session=session)
    )


def test_an_unsigned_404_returns_its_own_status():
    _data, status, _headers, snippet = _get(_Provider(None))
    assert status == UNSIGNED_REQUEST_STATUS
    assert snippet == NO_SIGNATURE_DETAIL


def test_a_404_that_carried_the_header_stays_a_404():
    """A stale query id or a removed item: not our signature, so the old path applies."""
    _data, status, _headers, _snippet = _get(_Provider("tx-present"))
    assert status == 404


def test_an_unsigned_request_gives_the_account_no_cooldown():
    config = SimpleNamespace(cooldown_default_s=60, transient_cooldown_s=120, auth_cooldown_s=3600, cooldown_jitter_s=0)
    assert compute_cooldown(UNSIGNED_REQUEST_STATUS, {}, config) == (1, 0.0, None)
    assert compute_cooldown(404, {}, config)[2] == "transient"


class _Accounts:
    def __init__(self):
        self.release_calls: list[dict] = []

    def acquire_leases(self, count, run_id, worker_id_prefix):
        return [{"username": "only-account", "lease_id": "lease-1"}][:count]

    def record_usage(self, lease_id, pages=0, tweets=0):
        pass

    def release(self, lease_id, fields_to_set, fields_to_inc=None):
        self.release_calls.append(dict(fields_to_set))
        return True


class _Runs:
    def create_run(self, query_hash, input_payload):
        return "run-1"

    def finalize_run(self, run_id, status, tweets_count, stats=None):
        self.status = status


class _UnsignedThenSigned:
    def __init__(self):
        self.calls = 0

    async def search_tweets(self, request):
        self.calls += 1
        if self.calls == 1:
            return {
                "result": SearchResult(),
                "cursor": None,
                "status_code": UNSIGNED_REQUEST_STATUS,
                "headers": {},
                "text_snippet": NO_SIGNATURE_DETAIL,
            }
        return {
            "result": SearchResult(tweets=[TweetRecord(tweet_id="t-1", text="ok")]),
            "cursor": None,
            "status_code": 200,
            "headers": {},
        }


def test_the_run_retries_an_unsigned_page_and_the_account_does_not_rest():
    accounts, runs, engine = _Accounts(), _Runs(), _UnsignedThenSigned()
    config = SimpleNamespace(
        n_splits=1, concurrency=1, scheduler_min_interval_s=3600, task_retry_base_s=0, task_retry_max_s=0,
        max_task_attempts=3, max_fallback_attempts=3, max_account_switches=2, requests_per_min=10_000,
        min_delay_s=0.0, cooldown_default_s=60, transient_cooldown_s=120, auth_cooldown_s=3600, cooldown_jitter_s=0,
    )
    runner = Runner(
        config=config,
        repos={"accounts_repo": accounts, "runs_repo": runs},
        engines={"api_engine": engine},
        outputs=None,
    )
    result = asyncio.run(
        runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC", until="2026-02-01_00:10:00_UTC", search_query="bitcoin", limit=10
            )
        )
    )

    assert result.stats.tasks_done == 1 and result.stats.tasks_failed == 0
    assert result.stats.retries == 1
    assert len(result.tweets) == 1
    assert accounts.release_calls, "the worker released its lease"
    assert all(not call.get("available_til") and call.get("cooldown_reason") is None for call in accounts.release_calls)
