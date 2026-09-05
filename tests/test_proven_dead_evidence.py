"""An account leaves the pool for 30 days only on proven-dead evidence.

A 401 or 403 from a page of tweets is not proof. X sends it for a tweet that one account cannot read while the
credentials still work. The engine confirms with a self-lookup of the account's own handle. Only a self-lookup
that also fails gives the 30-day block; otherwise the account gets a short cooldown and returns in minutes.
"""

import asyncio
from types import SimpleNamespace

import pytest

from Scweet.api_engine import ApiEngine


class _FakeManifest:
    query_ids = {"user_lookup_screen_name": "q"}
    endpoints = {"user_lookup_screen_name": "https://x.com/i/api/graphql/{query_id}/UserByScreenName"}
    features = {}
    timeout_s = 20

    def features_for(self, _op):
        return {}


class _ManifestProvider:
    async def get_manifest(self):
        return _FakeManifest()


def _engine_with_lookup_status(status, data=None):
    engine = ApiEngine.__new__(ApiEngine)
    engine.manifest_provider = _ManifestProvider()

    async def _graphql_get(*, url, params, timeout_s, session=None, account_context=None):
        return (data if data is not None else {"data": {"user": {}}}), status, {}, ""

    engine._graphql_get = _graphql_get  # type: ignore[assignment]
    return engine


@pytest.mark.asyncio
class TestProbeAccountAlive:
    async def test_a_200_lookup_reports_alive(self):
        engine = _engine_with_lookup_status(200, data={"data": {"user": {"result": {}}}})
        assert await engine.probe_account_alive({"username": "alice"}) is True

    async def test_a_401_lookup_reports_dead(self):
        engine = _engine_with_lookup_status(401)
        assert await engine.probe_account_alive({"username": "alice"}) is False

    async def test_a_403_lookup_reports_dead(self):
        engine = _engine_with_lookup_status(403)
        assert await engine.probe_account_alive({"username": "alice"}) is False

    async def test_a_network_error_is_inconclusive(self):
        engine = ApiEngine.__new__(ApiEngine)
        engine.manifest_provider = _ManifestProvider()

        async def _raises(**_kwargs):
            raise RuntimeError("network down")

        engine._graphql_get = _raises  # type: ignore[assignment]
        assert await engine.probe_account_alive({"username": "alice"}) is None

    async def test_no_username_is_inconclusive(self):
        engine = _engine_with_lookup_status(200)
        assert await engine.probe_account_alive({"username": None}) is None


# ── The worker wiring: the probe result decides the cooldown ────────────────

import time

from Scweet.cooldown import compute_cooldown


def _cfg(**over):
    d = {"cooldown_default_s": 120, "transient_cooldown_s": 90, "auth_cooldown_s": 3600, "cooldown_jitter_s": 0}
    d.update(over)
    return SimpleNamespace(**d)


class TestTheProbeResultDecidesTheCooldown:
    """This mirrors the finally block of the worker: proven_dead comes from the probe."""

    def test_a_live_account_gets_a_short_cooldown(self):
        engine = _engine_with_lookup_status(200, data={"data": {"user": {"result": {}}}})
        alive = asyncio.run(engine.probe_account_alive({"username": "alice"}))
        proven_dead = alive is False
        _status, until, reason = compute_cooldown(401, None, _cfg(), proven_dead=proven_dead)
        assert reason == "auth_unconfirmed"
        assert until <= time.time() + 91

    def test_a_dead_account_gets_the_long_block(self):
        engine = _engine_with_lookup_status(401)
        alive = asyncio.run(engine.probe_account_alive({"username": "alice"}))
        proven_dead = alive is False
        _status, until, reason = compute_cooldown(401, None, _cfg(), proven_dead=proven_dead)
        assert reason == "auth_failed"
        assert until >= time.time() + 3599

    def test_an_inconclusive_probe_does_not_block(self):
        """A network error during the probe must not remove a possibly-healthy account for a month."""
        engine = ApiEngine.__new__(ApiEngine)
        engine.manifest_provider = _ManifestProvider()

        async def _raises(**_kwargs):
            raise RuntimeError("network down")

        engine._graphql_get = _raises  # type: ignore[assignment]
        alive = asyncio.run(engine.probe_account_alive({"username": "alice"}))
        proven_dead = alive is False  # None is False -> proven_dead is False
        _status, _until, reason = compute_cooldown(401, None, _cfg(), proven_dead=proven_dead)
        assert reason == "auth_unconfirmed"


# ── The worker wiring, end to end through Runner ────────────────────────────

from Scweet.models import SearchRequest
from Scweet.runner import Runner


class _RecordingRepo:
    def __init__(self):
        self.release_calls = []

    def acquire_leases(self, count, run_id, worker_id_prefix):
        return [{"username": "acct-a", "lease_id": "lease-a", "auth_token": "t", "csrf": "c"}]

    def record_usage(self, lease_id, pages=0, tweets=0):
        pass

    def release(self, lease_id, fields_to_set, fields_to_inc=None):
        self.release_calls.append(dict(fields_to_set))
        return True


class _SessionBuilder:
    """Returns a truthy session, so account_session is not None and the probe branch runs."""

    async def build(self, account):
        return object()


class _PageAuthEngine:
    """The first page returns 401. The probe result is configurable."""

    def __init__(self, alive):
        self._alive = alive
        self.probe_calls = 0

    async def search_tweets(self, request):
        from Scweet.models import SearchResult

        return {"result": SearchResult(), "cursor": None, "status_code": 401, "headers": {}}

    async def probe_account_alive(self, account, *, session=None):
        self.probe_calls += 1
        return self._alive


def _run_and_get_cooldown(alive):
    repo = _RecordingRepo()
    engine = _PageAuthEngine(alive)
    runner = Runner(
        config=SimpleNamespace(
            n_splits=1,
            concurrency=1,
            scheduler_min_interval_s=300,
            requests_per_min=10_000,
            min_delay_s=0.0,
            cooldown_default_s=120,
            transient_cooldown_s=90,
            auth_cooldown_s=3600,
            cooldown_jitter_s=0,
            proxy=None,
            max_task_attempts=1,
            max_fallback_attempts=1,
            max_account_switches=0,
        ),
        repos={"accounts_repo": repo},
        engines={"api_engine": engine, "account_session_builder": _SessionBuilder()},
        outputs=None,
    )
    async def _go():
        # A run where every page returns 401 raises at the run level. The worker's finally applies the
        # cooldown before that raise, so the recorded release still holds the decision under test.
        try:
            await runner.run_search(
                SearchRequest(
                    since="2026-02-01_00:00:00_UTC",
                    until="2026-02-01_00:10:00_UTC",
                    search_query="x",
                    limit=10,
                )
            )
        except Exception:
            pass

    asyncio.run(_go())
    reasons = [c.get("cooldown_reason") for c in repo.release_calls]
    return engine, reasons


class TestTheWorkerConfirmsBeforeBlocking:
    def test_a_page_401_with_a_live_account_gives_a_short_cooldown(self):
        engine, reasons = _run_and_get_cooldown(alive=True)
        assert engine.probe_calls >= 1, "the worker did not run the self-lookup probe"
        assert "auth_unconfirmed" in reasons
        assert "auth_failed" not in reasons

    def test_a_page_401_with_a_dead_account_gives_the_long_block(self):
        engine, reasons = _run_and_get_cooldown(alive=False)
        assert engine.probe_calls >= 1
        assert "auth_failed" in reasons
