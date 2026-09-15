"""A request never leaves without the transaction id, and a 404 never spends the pool.

The failure mode, measured 2026-09-14: the build of the transaction id failed
once at startup, the old code stamped the 6-hour TTL on that failure, every
request left without the x-client-transaction-id header, X answered 404 to
each one, and the cooldown branch spent one account for each 404 until the
run died. The fill was 0% with the defect and 102% without it, on the same
accounts and the same proxy.
"""

import asyncio
import json
from pathlib import Path

from Scweet.api_engine import ApiEngine
from Scweet.transaction import TransactionIdProvider

FIXTURES = Path(__file__).parent / "fixtures"
LOOKUP_PAYLOAD = json.loads((FIXTURES / "tweet_lookup_batch.json").read_text(encoding="utf-8"))


class _FlakyBuilder:
    """A generator source that fails a fixed count of times, then works."""

    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.calls <= self.failures:
            return None
        return _Generator()


class _Generator:
    def generate_transaction_id(self, *, method: str, path: str) -> str:
        return f"txid-{method}-{path}"


def _provider(failures: int, attempts: int = 3) -> TransactionIdProvider:
    provider = TransactionIdProvider(enabled=True, init_attempts=attempts, init_backoff_s=0.0)
    provider._deps_checked = True
    provider._deps_available = True
    provider._build_client_transaction = _FlakyBuilder(failures)
    return provider


def test_the_build_retries_and_one_failure_is_not_final():
    provider = _provider(failures=2, attempts=3)
    tx_id = provider.generate(method="GET", path="/i/api/graphql/x/SearchTimeline")
    assert tx_id == "txid-GET-/i/api/graphql/x/SearchTimeline"
    assert provider._build_client_transaction.calls == 3


def test_refresh_forces_a_rebuild_through_the_backoff_window():
    """A failed build sets a backoff, so a burst of workers does not each rebuild.
    The 404 path calls refresh(), which must ignore that backoff and rebuild now."""
    provider = _provider(failures=99, attempts=1)
    provider.init_backoff_s = 3600.0  # a long window, so generate() will not retry
    assert provider.generate(method="GET", path="/p") is None

    # The source recovers. A plain generate() waits out the backoff window.
    provider._build_client_transaction = _FlakyBuilder(failures=0)
    assert provider.generate(method="GET", path="/p") is None, "generate honours the backoff"

    # refresh() clears the backoff and rebuilds at once, as the 404 path needs.
    assert provider.refresh() is True
    assert provider.generate(method="GET", path="/p") is not None


def test_refresh_discards_the_generator_and_builds_a_new_one():
    provider = _provider(failures=0)
    assert provider.generate(method="GET", path="/p")
    old = provider._client_transaction
    assert provider.refresh() is True
    assert provider._client_transaction is not old


class _Response:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}
        self.text = text or (json.dumps(payload) if payload is not None else "")

    def json(self):
        return self._payload


class _HeaderGateSession:
    """Answers 404 to a request without the header, 200 with the fixture to one with it."""

    def __init__(self):
        self.calls: list[dict] = []

    async def get(self, url, **kwargs):
        headers = kwargs.get("headers") or {}
        self.calls.append({"url": url, "has_header": "X-Client-Transaction-Id" in headers})
        if "X-Client-Transaction-Id" not in headers:
            return _Response(404, text="")
        return _Response(200, payload=LOOKUP_PAYLOAD)

    async def close(self):
        pass


class _RecoveringProvider:
    """Broken until refresh() runs, then it generates."""

    def __init__(self):
        self.enabled = True
        self.refreshed = False

    def generate(self, *, method: str, path: str):
        return "txid-after-refresh" if self.refreshed else None

    def refresh(self):
        self.refreshed = True
        return True


def _engine(session, provider) -> ApiEngine:
    return ApiEngine(
        config={"request_404_retries": 1},
        accounts_repo=None,
        manifest_provider=None,
        session_factory=lambda: session,
        transaction_id_provider=provider,
    )


def test_a_404_rebuilds_the_id_and_retries_on_the_same_session():
    session = _HeaderGateSession()
    provider = _RecoveringProvider()
    engine = _engine(session, provider)

    async def run():
        return await engine._graphql_get(
            url="https://x.com/i/api/graphql/x/TweetResultsByRestIds",
            params={},
            timeout_s=5,
            session=session,
        )

    data, status, _headers, _snippet = asyncio.run(run())
    assert status == 200
    assert data is not None
    assert [c["has_header"] for c in session.calls] == [False, True], (
        "the first request lacked the header and answered 404; the retry carried it"
    )


def test_without_the_retry_budget_the_404_stays():
    session = _HeaderGateSession()
    provider = _RecoveringProvider()
    engine = ApiEngine(
        config={"request_404_retries": 0},
        accounts_repo=None,
        manifest_provider=None,
        session_factory=lambda: session,
        transaction_id_provider=provider,
    )

    async def run():
        return await engine._graphql_get(
            url="https://x.com/i/api/graphql/x/TweetResultsByRestIds",
            params={},
            timeout_s=5,
            session=session,
        )

    _data, status, _headers, _snippet = asyncio.run(run())
    assert status == 404
    assert len(session.calls) == 1
