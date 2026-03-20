from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace

import pytest

from Scweet.account_session import AccountSessionBuilder
from Scweet.api_engine import ApiEngine
from Scweet.exceptions import AccountSessionAuthError, AccountSessionTransientError
from Scweet.manifest import ManifestModel
from Scweet.models import RunStats, SearchRequest, SearchResult, TweetRecord
from Scweet.queue import InMemoryTaskQueue
from Scweet.runner import Runner
from Scweet.scheduler import build_tasks_for_intervals, split_time_intervals


# ── Shared fakes ───────────────────────────────────────────────────────


class _FakeAccountsRepo:
    def __init__(self, usernames: list[str]):
        self._usernames = usernames
        self.acquire_calls: list[dict] = []
        self.usage_calls: list[dict] = []
        self.release_calls: list[dict] = []

    def acquire_leases(self, count: int, run_id: str, worker_id_prefix: str):
        self.acquire_calls.append({"count": count, "run_id": run_id, "worker_id_prefix": worker_id_prefix})
        leases = []
        for idx, username in enumerate(self._usernames[:count]):
            leases.append({"username": username, "lease_id": f"lease-{idx + 1}"})
        return leases

    def record_usage(self, lease_id: str, pages: int = 0, tweets: int = 0):
        self.usage_calls.append({"lease_id": lease_id, "pages": pages, "tweets": tweets})

    def release(self, lease_id: str, fields_to_set: dict, fields_to_inc: dict | None = None):
        self.release_calls.append(
            {"lease_id": lease_id, "fields_to_set": dict(fields_to_set), "fields_to_inc": dict(fields_to_inc or {})}
        )
        return True


class _FakeRunsRepo:
    def __init__(self):
        self.created: list[dict] = []
        self.finalized: list[dict] = []

    def create_run(self, query_hash: str, input_payload: dict):
        self.created.append({"query_hash": query_hash, "input_payload": dict(input_payload)})
        return "run-fixed-id"

    def finalize_run(self, run_id: str, status: str, tweets_count: int, stats: dict | None = None):
        self.finalized.append(
            {"run_id": run_id, "status": status, "tweets_count": tweets_count, "stats": dict(stats or {})}
        )


def _runner_config(*, n_splits: int = 1, concurrency: int = 1, retry_base_s: int = 0, retry_max_s: int = 0):
    return SimpleNamespace(
        n_splits=n_splits,
        concurrency=concurrency,
        scheduler_min_interval_s=300,
        task_retry_base_s=retry_base_s,
        task_retry_max_s=retry_max_s,
        max_task_attempts=3,
        max_fallback_attempts=3,
        max_account_switches=2,
        requests_per_min=10_000,
        min_delay_s=0.0,
        cooldown_default_s=60,
        transient_cooldown_s=30,
        auth_cooldown_s=3600,
        cooldown_jitter_s=0,
    )


# ── Scheduler & queue tests ────────────────────────────────────────────


def test_split_time_intervals_and_task_generation():
    since = "2026-02-01_00:00:00_UTC"
    until = "2026-02-01_01:00:00_UTC"

    intervals = split_time_intervals(since, until, n_intervals=10, min_interval_seconds=900)
    assert len(intervals) == 4
    assert intervals[0][0] == since
    assert intervals[-1][1] == until

    base_query = {"words": ["bitcoin"], "since": since, "until": until}
    tasks = build_tasks_for_intervals(base_query, run_id="run-1", priority=7, intervals=intervals)
    assert len(tasks) == 4
    assert len({task["task_id"] for task in tasks}) == 4
    assert all(task["run_id"] == "run-1" for task in tasks)
    assert all(task["priority"] == 7 for task in tasks)
    assert all(task["query"]["cursor"] is None for task in tasks)


def test_in_memory_task_queue_lease_ack_retry_fail_cancel():
    async def _run():
        queue = InMemoryTaskQueue()
        task = {
            "task_id": "task-1",
            "run_id": "run-1",
            "query": {"raw": {"words": ["x"]}, "since": "s", "until": "u", "cursor": None},
        }
        await queue.enqueue([task])

        leased = await queue.lease("worker-a")
        assert leased is not None
        assert leased["attempt"] == 0
        assert leased["fallback_attempts"] == 0
        assert leased["account_switches"] == 0
        assert leased["lease_worker_id"] == "worker-a"
        assert leased["lease_id"]

        assert await queue.ack(leased, {"pages": 2, "tweets": 5}) is True
        assert leased["stats"]["pages"] == 2
        assert leased["stats"]["tweets"] == 5

        assert await queue.retry(
            leased, delay_s=0, reason="transient", cursor="CUR-1",
            last_error_code=429, fallback_inc=1, account_switch_inc=1,
        ) is True

        retried = await queue.lease("worker-b")
        assert retried is not None
        assert retried["attempt"] == 1
        assert retried["fallback_attempts"] == 1
        assert retried["account_switches"] == 1
        assert retried["query"]["cursor"] == "CUR-1"
        assert retried["last_error_code"] == 429
        assert retried["last_error_reason"] == "transient"

        assert await queue.fail(retried, reason="fatal_error", last_error_code=503) is True
        assert retried["last_error_code"] == 503
        assert retried["last_error_reason"] == "fatal_error"

        queue.cancel_pending()

    asyncio.run(_run())


# ── Runner happy path ──────────────────────────────────────────────────


def test_runner_happy_path_with_mocked_engine_and_repos():
    class _HappyEngine:
        def __init__(self):
            self.calls = 0

        async def search_tweets(self, request):
            self.calls += 1
            tweet_id = f"tweet-{self.calls}"
            return {
                "result": SearchResult(tweets=[TweetRecord(tweet_id=tweet_id, text="ok")]),
                "cursor": None,
                "status_code": 200,
                "headers": {},
            }

    async def _run():
        accounts = _FakeAccountsRepo(["acct-a", "acct-b"])
        runs = _FakeRunsRepo()
        engine = _HappyEngine()
        runner = Runner(
            config=_runner_config(n_splits=2, concurrency=2),
            repos={"accounts_repo": accounts, "runs_repo": runs},
            engines={"api_engine": engine},
            outputs=None,
        )

        result = await runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:20:00_UTC",
                search_query="bitcoin",
                limit=10,
            )
        )

        assert result.stats.tasks_total == 2
        assert result.stats.tasks_done == 2
        assert result.stats.tasks_failed == 0
        assert result.stats.retries == 0
        assert result.stats.tweets_count == 2
        assert len(result.tweets) == 2
        assert len(accounts.usage_calls) == 2
        assert len(accounts.release_calls) == 2
        assert all(call["fields_to_set"]["status"] == 1 for call in accounts.release_calls)
        assert runs.finalized[-1]["status"] == "completed"
        assert runs.finalized[-1]["tweets_count"] == 2

    asyncio.run(_run())


# ── Retry path ─────────────────────────────────────────────────────────


def test_runner_retry_path_requeues_and_releases_with_cooldown():
    reset_ts = int(time.time() + 120)

    class _RetryThenSuccessEngine:
        def __init__(self):
            self.calls = 0

        async def search_tweets(self, request):
            self.calls += 1
            if self.calls == 1:
                return {
                    "result": SearchResult(),
                    "cursor": "CURSOR-429",
                    "status_code": 429,
                    "headers": {"x-rate-limit-reset": str(reset_ts)},
                }
            return {
                "result": SearchResult(tweets=[TweetRecord(tweet_id="tweet-success", text="ok")]),
                "cursor": None,
                "status_code": 200,
                "headers": {},
            }

    async def _run():
        accounts = _FakeAccountsRepo(["acct-a", "acct-b"])
        runs = _FakeRunsRepo()
        engine = _RetryThenSuccessEngine()
        runner = Runner(
            config=_runner_config(n_splits=1, concurrency=2),
            repos={"accounts_repo": accounts, "runs_repo": runs},
            engines={"api_engine": engine},
            outputs=None,
        )

        result = await runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:10:00_UTC",
                search_query="ethereum",
                limit=10,
            )
        )

        assert result.stats.tasks_total == 1
        assert result.stats.tasks_done == 1
        assert result.stats.tasks_failed == 0
        assert result.stats.retries == 1
        assert result.stats.tweets_count == 1
        assert len(result.tweets) == 1

        assert len(accounts.release_calls) == 2
        cooldown_releases = [
            call for call in accounts.release_calls if call["fields_to_set"].get("cooldown_reason") == "rate_limit"
        ]
        assert len(cooldown_releases) == 1
        assert cooldown_releases[0]["fields_to_set"]["available_til"] == float(reset_ts)
        assert runs.finalized[-1]["status"] == "completed"

    asyncio.run(_run())


def test_runner_preemptive_rate_limit_header_handoffs_after_success_page():
    reset_ts = int(time.time() + 90)

    class _HeaderRateLimitedEngine:
        def __init__(self):
            self.calls = 0

        async def search_tweets(self, request):
            self.calls += 1
            if self.calls == 1:
                return {
                    "result": SearchResult(tweets=[TweetRecord(tweet_id="tweet-1", text="ok-1")]),
                    "cursor": "CURSOR-2",
                    "continue_with_cursor": True,
                    "status_code": 200,
                    "headers": {
                        "x-rate-limit-remaining": "0",
                        "x-rate-limit-reset": str(reset_ts),
                    },
                }
            return {
                "result": SearchResult(tweets=[TweetRecord(tweet_id="tweet-2", text="ok-2")]),
                "cursor": None,
                "continue_with_cursor": False,
                "status_code": 200,
                "headers": {"x-rate-limit-remaining": "9"},
            }

    async def _run():
        accounts = _FakeAccountsRepo(["acct-a", "acct-b"])
        runs = _FakeRunsRepo()
        engine = _HeaderRateLimitedEngine()
        runner = Runner(
            config=_runner_config(n_splits=1, concurrency=2),
            repos={"accounts_repo": accounts, "runs_repo": runs},
            engines={"api_engine": engine},
            outputs=None,
        )

        result = await runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:10:00_UTC",
                search_query="header-rate-limit",
                limit=10,
            )
        )

        assert result.stats.tasks_total == 1
        assert result.stats.tasks_done == 1
        assert result.stats.tasks_failed == 0
        assert result.stats.tweets_count == 2
        assert len(result.tweets) == 2

        cooldown_releases = [
            call for call in accounts.release_calls if call["fields_to_set"].get("cooldown_reason") == "rate_limit"
        ]
        assert len(cooldown_releases) == 1
        assert cooldown_releases[0]["fields_to_set"]["available_til"] == float(reset_ts)
        assert runs.finalized[-1]["status"] == "completed"

    asyncio.run(_run())


def test_runner_auth_error_triggers_auth_failed_cooldown_and_release_fields():
    class _AuthThenSuccessEngine:
        def __init__(self):
            self.calls = 0

        async def search_tweets(self, request):
            self.calls += 1
            if self.calls == 1:
                return {
                    "result": SearchResult(),
                    "cursor": "CURSOR-401",
                    "status_code": 401,
                    "headers": {},
                }
            return {
                "result": SearchResult(tweets=[TweetRecord(tweet_id="tweet-auth-ok", text="ok")]),
                "cursor": None,
                "status_code": 200,
                "headers": {},
            }

    async def _run():
        now_before = time.time()
        accounts = _FakeAccountsRepo(["acct-a", "acct-b"])
        engine = _AuthThenSuccessEngine()
        runner = Runner(
            config=_runner_config(n_splits=1, concurrency=2),
            repos={"accounts_repo": accounts},
            engines={"api_engine": engine},
            outputs=None,
        )

        result = await runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:10:00_UTC",
                search_query="solana",
                limit=10,
            )
        )
        now_after = time.time()

        assert result.stats.tasks_done == 1
        assert result.stats.tasks_failed == 0
        assert result.stats.retries == 1

        auth_releases = [
            call for call in accounts.release_calls if call["fields_to_set"].get("cooldown_reason") == "auth_failed"
        ]
        assert len(auth_releases) == 1
        fields = auth_releases[0]["fields_to_set"]
        assert fields["status"] == 401
        assert fields["last_error_code"] == 401
        assert fields["available_til"] >= now_before + 3000
        assert fields["available_til"] <= now_after + 3700

    asyncio.run(_run())


# ── Limit & pagination ─────────────────────────────────────────────────


def test_runner_enforces_global_limit_and_paginates_with_cursor_continuation():
    class _PaginatingEngine:
        def __init__(self):
            self.calls = 0

        async def search_tweets(self, request):
            self.calls += 1
            return {
                "result": SearchResult(
                    tweets=[TweetRecord(tweet_id=f"tweet-{self.calls}", text=f"page-{self.calls}")]
                ),
                "cursor": f"CURSOR-{self.calls}",
                "continue_with_cursor": True,
                "status_code": 200,
                "headers": {},
            }

    async def _run():
        accounts = _FakeAccountsRepo(["acct-a"])
        runs = _FakeRunsRepo()
        engine = _PaginatingEngine()
        runner = Runner(
            config=_runner_config(n_splits=1, concurrency=1),
            repos={"accounts_repo": accounts, "runs_repo": runs},
            engines={"api_engine": engine},
            outputs=None,
        )

        result = await runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:10:00_UTC",
                search_query="limit-check",
                limit=2,
            )
        )

        assert engine.calls == 2
        assert result.stats.tweets_count == 2
        assert len(result.tweets) == 2
        assert result.stats.tasks_total == 1
        assert result.stats.tasks_done == 1
        assert result.stats.tasks_failed == 0
        assert runs.finalized[-1]["status"] == "completed"

    asyncio.run(_run())


def test_runner_treats_limit_as_stop_signal_and_keeps_overshoot_from_last_page():
    class _SinglePageOvershootEngine:
        def __init__(self):
            self.calls = 0

        async def search_tweets(self, request):
            self.calls += 1
            tweets = [TweetRecord(tweet_id=f"tweet-{i}", text="bulk") for i in range(120)]
            return {
                "result": SearchResult(tweets=tweets),
                "cursor": "CURSOR-BULK",
                "continue_with_cursor": True,
                "status_code": 200,
                "headers": {},
            }

    async def _run():
        accounts = _FakeAccountsRepo(["acct-a"])
        runs = _FakeRunsRepo()
        engine = _SinglePageOvershootEngine()
        runner = Runner(
            config=_runner_config(n_splits=1, concurrency=1),
            repos={"accounts_repo": accounts, "runs_repo": runs},
            engines={"api_engine": engine},
            outputs=None,
        )

        result = await runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:10:00_UTC",
                search_query="overshoot-check",
                limit=100,
            )
        )

        assert engine.calls == 1
        assert result.stats.tweets_count == 120
        assert len(result.tweets) == 120
        assert result.stats.tasks_done == 1
        assert result.stats.tasks_failed == 0
        assert runs.finalized[-1]["status"] == "completed"

    asyncio.run(_run())


def test_runner_stops_cursor_pagination_after_empty_page_threshold():
    class _InfiniteEmptyPagesEngine:
        def __init__(self):
            self.calls = 0

        async def search_tweets(self, request):
            self.calls += 1
            return {
                "result": SearchResult(tweets=[]),
                "cursor": f"CURSOR-{self.calls}",
                "continue_with_cursor": True,
                "status_code": 200,
                "headers": {},
            }

    async def _run():
        accounts = _FakeAccountsRepo(["acct-a"])
        runs = _FakeRunsRepo()
        engine = _InfiniteEmptyPagesEngine()
        runner = Runner(
            config=_runner_config(n_splits=1, concurrency=1),
            repos={"accounts_repo": accounts, "runs_repo": runs},
            engines={"api_engine": engine},
            outputs=None,
        )

        result = await runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:10:00_UTC",
                search_query="empty-stop-check",
                max_empty_pages=1,
            )
        )

        assert engine.calls == 1
        assert result.stats.tweets_count == 0
        assert len(result.tweets) == 0
        assert result.stats.tasks_done == 1
        assert result.stats.tasks_failed == 0
        assert result.stats.retries == 0
        assert runs.finalized[-1]["status"] == "completed"

    asyncio.run(_run())


# ── Hardening tests (heartbeats, emergency release, session build) ─────


class _SlowSuccessEngine:
    async def search_tweets(self, request):
        await asyncio.sleep(0.06)
        return {
            "result": SearchResult(tweets=[TweetRecord(tweet_id="tweet-1", text="ok")]),
            "cursor": None,
            "status_code": 200,
            "headers": {},
        }


def test_runner_heartbeats_active_leases_while_worker_runs():
    class _HeartbeatAccountsRepo:
        def __init__(self):
            self.heartbeat_calls: list[dict] = []
            self.release_calls: list[dict] = []

        def acquire_leases(self, count, run_id, worker_id_prefix):
            return [{"id": 1, "username": "acct-a", "lease_id": "lease-a"}]

        def heartbeat(self, lease_id, extend_by_s):
            self.heartbeat_calls.append({"lease_id": lease_id, "extend_by_s": extend_by_s})
            return True

        def record_usage(self, lease_id, pages=0, tweets=0):
            return None

        def release(self, lease_id, fields_to_set, fields_to_inc=None):
            self.release_calls.append(
                {"lease_id": lease_id, "fields_to_set": dict(fields_to_set), "fields_to_inc": dict(fields_to_inc or {})}
            )
            return True

    async def _run():
        accounts_repo = _HeartbeatAccountsRepo()
        runner = Runner(
            config={
                "n_splits": 1,
                "concurrency": 1,
                "lease_ttl_s": 120,
                "lease_heartbeat_s": 0.01,
                "cooldown_jitter_s": 0,
            },
            repos={"accounts_repo": accounts_repo},
            engines={"api_engine": _SlowSuccessEngine()},
            outputs=None,
        )

        result = await runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:10:00_UTC",
                search_query="heartbeat",
            )
        )

        assert result.stats.tasks_done == 1
        assert len(accounts_repo.release_calls) == 1
        assert len(accounts_repo.heartbeat_calls) >= 1
        assert all(call["lease_id"] == "lease-a" for call in accounts_repo.heartbeat_calls)
        assert all(call["extend_by_s"] == 120 for call in accounts_repo.heartbeat_calls)

    asyncio.run(_run())


def test_runner_emergency_release_after_leasing_before_worker_handoff():
    class _EmergencyAccountsRepo:
        def __init__(self):
            self.release_calls: list[dict] = []

        def acquire_leases(self, count, run_id, worker_id_prefix):
            return [{"id": 1, "username": "acct-a", "lease_id": "lease-a"}]

        def release(self, lease_id, fields_to_set, fields_to_inc=None):
            self.release_calls.append(
                {"lease_id": lease_id, "fields_to_set": dict(fields_to_set), "fields_to_inc": dict(fields_to_inc or {})}
            )
            return True

    class _ExplodingQueue(InMemoryTaskQueue):
        async def enqueue(self, tasks):
            raise RuntimeError("queue enqueue failed")

    async def _run():
        accounts_repo = _EmergencyAccountsRepo()
        runner = Runner(
            config={"n_splits": 1, "concurrency": 1},
            repos={"accounts_repo": accounts_repo},
            engines={"api_engine": _SlowSuccessEngine()},
            outputs=None,
        )
        runner.queue_cls = _ExplodingQueue

        with pytest.raises(RuntimeError, match="queue enqueue failed"):
            await runner.run_search(
                SearchRequest(
                    since="2026-02-01_00:00:00_UTC",
                    until="2026-02-01_00:10:00_UTC",
                    search_query="release",
                )
            )

        assert len(accounts_repo.release_calls) == 1
        assert accounts_repo.release_calls[0]["lease_id"] == "lease-a"
        assert accounts_repo.release_calls[0]["fields_to_set"] == {}

    asyncio.run(_run())


@pytest.mark.parametrize(
    "raised, expected_status, expected_reason, expected_last_error",
    [
        (
            AccountSessionAuthError(code="missing_auth_material", reason="missing_csrf"),
            401,
            "auth_failed",
            401,
        ),
        (
            AccountSessionTransientError(code="session_factory_error", reason="RuntimeError"),
            1,
            "transient",
            599,
        ),
    ],
)
def test_runner_session_build_exception_classification_maps_to_release_fields(
    raised, expected_status, expected_reason, expected_last_error,
):
    class _SessionAccountsRepo:
        def __init__(self):
            self.release_calls: list[dict] = []

        def release(self, lease_id, fields_to_set, fields_to_inc=None):
            self.release_calls.append(
                {"lease_id": lease_id, "fields_to_set": dict(fields_to_set), "fields_to_inc": dict(fields_to_inc or {})}
            )
            return True

    class _FailingBuilder:
        def __init__(self, exc):
            self.exc = exc

        def build(self, account):
            raise self.exc

    async def _run():
        accounts_repo = _SessionAccountsRepo()
        runner = Runner(
            config={
                "cooldown_default_s": 60,
                "transient_cooldown_s": 30,
                "auth_cooldown_s": 3600,
                "cooldown_jitter_s": 0,
            },
            repos={"accounts_repo": accounts_repo},
            engines={"api_engine": _SlowSuccessEngine(), "account_session_builder": _FailingBuilder(raised)},
            outputs=None,
        )
        await runner._search_worker(
            worker_id="acct:0",
            account={"id": 9, "username": "acct-z", "lease_id": "lease-z"},
            queue=InMemoryTaskQueue(),
            stats=RunStats(),
            stats_lock=asyncio.Lock(),
            tweets_out=[],
            seen_tweet_ids=set(),
        )
        assert len(accounts_repo.release_calls) == 1
        fields = accounts_repo.release_calls[0]["fields_to_set"]
        assert fields["status"] == expected_status
        assert fields["cooldown_reason"] == expected_reason
        assert fields["last_error_code"] == expected_last_error

    asyncio.run(_run())


# ── Account session reuse test ─────────────────────────────────────────


class _CookieJar:
    def __init__(self):
        self.values: dict[str, str] = {}

    def set(self, name, value, domain=None):
        self.values[str(name)] = str(value)

    def get_dict(self):
        return dict(self.values)


class _AccountResponse:
    def __init__(self, payload):
        self.status_code = 200
        self.headers = {}
        self.text = "{}"
        self._payload = payload

    def json(self):
        return self._payload


class _AccountSession:
    def __init__(self, payload):
        self.headers: dict[str, str] = {}
        self.cookies = _CookieJar()
        self.payload = payload
        self.get_calls: list[dict] = []
        self.closed = False

    async def get(self, url, **kwargs):
        self.get_calls.append(
            {
                "url": url,
                "kwargs": dict(kwargs),
                "headers_snapshot": dict(self.headers),
                "cookies_snapshot": self.cookies.get_dict(),
            }
        )
        return _AccountResponse(self.payload)

    async def close(self):
        self.closed = True


class _SingleAccountRepo:
    def __init__(self, account):
        self._account = dict(account)
        self.release_calls: list[dict] = []
        self.usage_calls: list[dict] = []

    def acquire_leases(self, count, run_id, worker_id_prefix):
        return [dict(self._account)]

    def record_usage(self, lease_id, pages=0, tweets=0):
        self.usage_calls.append({"lease_id": lease_id, "pages": pages, "tweets": tweets})

    def release(self, lease_id, fields_to_set, fields_to_inc=None):
        self.release_calls.append(
            {"lease_id": lease_id, "fields_to_set": dict(fields_to_set), "fields_to_inc": dict(fields_to_inc or {})}
        )
        return True


def test_runner_reuses_authenticated_account_session_for_api_engine_calls():
    payload = {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {"instructions": []}
                }
            }
        }
    }
    account_session = _AccountSession(payload)
    builder = AccountSessionBuilder(
        session_factory=lambda: account_session,
        api_http_mode="async",
        default_bearer_token="bearer-default",
    )

    session_factory_calls = {"count": 0}

    def _unexpected_session_factory():
        session_factory_calls["count"] += 1
        raise AssertionError("ApiEngine session_factory should not be called when runner injects account session")

    manifest = ManifestModel.model_validate(
        {
            "version": "session-test",
            "query_ids": {"search_timeline": "qid"},
            "endpoints": {"search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline"},
            "features": {},
            "timeout_s": 5,
        }
    )

    class _SessionManifestProvider:
        async def get_manifest(self):
            return manifest

    api_engine = ApiEngine(
        config={"api_http_mode": "async"},
        accounts_repo=None,
        manifest_provider=_SessionManifestProvider(),
        session_factory=_unexpected_session_factory,
    )

    account = {
        "id": 7,
        "username": "acct-a",
        "lease_id": "lease-a",
        "auth_token": "auth-7",
        "csrf": "csrf-7",
        "cookies_json": {"auth_token": "auth-7", "ct0": "csrf-7"},
    }
    accounts_repo = _SingleAccountRepo(account)

    runner = Runner(
        config=SimpleNamespace(
            n_splits=2, concurrency=1, scheduler_min_interval_s=300,
            task_retry_base_s=0, task_retry_max_s=0,
            max_task_attempts=2, max_fallback_attempts=2, max_account_switches=1,
            requests_per_min=10_000, min_delay_s=0.0,
            cooldown_default_s=60, transient_cooldown_s=30, auth_cooldown_s=3600, cooldown_jitter_s=0,
        ),
        repos={"accounts_repo": accounts_repo},
        engines={"api_engine": api_engine, "account_session_builder": builder},
        outputs=None,
    )

    result = asyncio.run(
        runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:20:00_UTC",
                search_query="bitcoin",
            )
        )
    )

    assert result.stats.tasks_total == 2
    assert result.stats.tasks_done == 2
    assert result.stats.tasks_failed == 0
    assert session_factory_calls["count"] == 0
    assert len(account_session.get_calls) == 2
    assert account_session.closed is True
    assert ("async", "explicit") in api_engine._logged_http_mode_selection

    for call in account_session.get_calls:
        assert call["headers_snapshot"]["Authorization"] == "Bearer bearer-default"
        assert call["headers_snapshot"]["X-Csrf-Token"] == "csrf-7"
        assert call["headers_snapshot"]["X-Twitter-Auth-Type"] == "OAuth2Session"
        assert call["cookies_snapshot"]["auth_token"] == "auth-7"
        assert call["cookies_snapshot"]["ct0"] == "csrf-7"

    assert len(accounts_repo.release_calls) == 1
    assert accounts_repo.release_calls[0]["fields_to_set"]["status"] == 1


# ── Resume integration test ────────────────────────────────────────────


class _ResumeAccountsRepo:
    def acquire_leases(self, count, run_id, worker_id_prefix):
        return [{"username": "acct-a", "lease_id": "lease-a"}]

    def record_usage(self, lease_id, pages=0, tweets=0):
        return None

    def release(self, lease_id, fields_to_set, fields_to_inc=None):
        return True


class _ResumeRepo:
    def __init__(self):
        self.saved = []
        self.cleared = []

    def save_checkpoint(self, query_hash, cursor, since, until):
        self.saved.append({"query_hash": query_hash, "cursor": cursor, "since": since, "until": until})

    def clear_checkpoint(self, query_hash):
        self.cleared.append(query_hash)


class _ResumeEngine:
    def __init__(self):
        self.cursors = []

    async def search_tweets(self, request):
        if isinstance(request, dict):
            self.cursors.append(request.get("cursor"))
        else:
            self.cursors.append(getattr(request, "cursor", None))
        return {
            "result": SearchResult(tweets=[TweetRecord(tweet_id="tweet-1", text="ok")]),
            "cursor": "NEXT-CURSOR",
            "status_code": 200,
            "headers": {},
        }


def test_runner_uses_initial_cursor_and_writes_resume_checkpoint():
    async def _run():
        resume_repo = _ResumeRepo()
        engine = _ResumeEngine()
        runner = Runner(
            config=SimpleNamespace(
                n_splits=1, concurrency=1, scheduler_min_interval_s=300,
                task_retry_base_s=0, task_retry_max_s=0,
                max_task_attempts=2, max_fallback_attempts=2, max_account_switches=1,
                requests_per_min=10_000, min_delay_s=0.0,
                cooldown_default_s=60, transient_cooldown_s=30, auth_cooldown_s=3600,
                cooldown_jitter_s=0, priority=1, strict=False, proxy=None,
                proxy_check_on_lease=False, lease_ttl_s=120, lease_heartbeat_s=30.0,
                api_page_size=20, max_empty_pages=1, api_http_impersonate=None,
            ),
            repos={"accounts_repo": _ResumeAccountsRepo(), "resume_repo": resume_repo},
            engines={"api_engine": engine},
            outputs=None,
        )

        result = await runner.run_search(
            SearchRequest(
                since="2026-02-01",
                until="2026-02-02",
                search_query="bitcoin",
                resume=True,
                initial_cursor="START-CURSOR",
                query_hash="query-resume",
            )
        )

        assert result.stats.tasks_done == 1
        assert engine.cursors == ["START-CURSOR"]
        assert len(resume_repo.saved) == 1
        assert resume_repo.saved[0]["query_hash"] == "query-resume"
        assert resume_repo.saved[0]["cursor"] == "NEXT-CURSOR"
        assert resume_repo.saved[0]["since"] == "2026-02-01_00:00:00_UTC"
        assert resume_repo.saved[0]["until"] == "2026-02-02_23:59:59_UTC"
        assert resume_repo.cleared == ["query-resume"]

    asyncio.run(_run())
