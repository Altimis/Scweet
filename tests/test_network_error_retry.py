"""A request that fails in the network retries on the same account, from a new exit IP.

The failure mode, measured 2026-10-22 on a residential provider with `{session}` in the proxy URL: 25 of 30
fresh proxy sessions reached x.com and 5 timed out after 20 seconds. A session that failed once failed again
on its second request, 6 of 6, while 14 of 14 good sessions stayed good. Without a retry, the one user lookup
of a profile timeline answered 599, the target ended with 0 tweets, and the request still reported
`completed=True`. A new `{session}` token on the same session reaches a new exit IP and keeps the cookies.
"""

import asyncio
import json
from pathlib import Path

from Scweet.account_session import AccountSessionBuilder, repin_proxy_session
from Scweet.api_engine import ApiEngine

FIXTURES = Path(__file__).parent / "fixtures"
LOOKUP_PAYLOAD = json.loads((FIXTURES / "tweet_lookup_batch.json").read_text(encoding="utf-8"))
PROXY_TEMPLATE = "http://login_s_{session}_ttl_1h:pw@res.proxy.example:10000"
ACCOUNT = {"id": 1, "username": "alice", "cookies": {"auth_token": "a" * 40, "ct0": "c" * 32}}


class _Response:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload
        self.headers = {}
        self.text = json.dumps(payload) if payload is not None else ""

    def json(self):
        return self._payload


class _DeadExitSession:
    """Times out for its first `fail_first` requests, then answers 200."""

    def __init__(self):
        self.proxies = {}
        self.cookies = {}
        self.headers = {}
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        proxy_url = self.proxies.get("https", "")
        self.calls.append(proxy_url)
        if len(self.calls) <= self.fail_first:
            raise TimeoutError("curl: (28) Connection timed out after 20000 milliseconds")
        return _Response(200, payload=LOOKUP_PAYLOAD)

    async def close(self):
        pass


class _Provider:
    enabled = True

    def generate(self, *, method: str, path: str):
        return "txid"

    def refresh(self):
        return True


def _session(fail_first: int, proxy=PROXY_TEMPLATE) -> _DeadExitSession:
    def factory():
        s = _DeadExitSession()
        s.fail_first = fail_first
        return s

    session, _meta = AccountSessionBuilder(session_factory=factory, proxy=proxy).build(ACCOUNT)
    return session


def _get(session, retries: int):
    engine = ApiEngine(
        config={"network_error_retries": retries},
        accounts_repo=None,
        manifest_provider=None,
        session_factory=lambda: session,
        transaction_id_provider=_Provider(),
    )
    return asyncio.run(
        engine._graphql_get(
            url="https://x.com/i/api/graphql/x/UserByScreenName",
            params={},
            timeout_s=5,
            session=session,
            account_context={"id": 1, "username": "alice"},
        )
    )


def test_a_network_error_retries_from_a_new_exit_ip():
    session = _session(fail_first=1)
    data, status, _headers, _snippet = _get(session, retries=2)
    assert status == 200
    assert data is not None
    assert len(session.calls) == 2
    assert session.calls[0] != session.calls[1], "the retry must carry a new proxy session token"
    assert all("{session}" not in c for c in session.calls)


def test_the_retry_budget_bounds_a_proxy_that_stays_down():
    session = _session(fail_first=10)
    data, status, _headers, _snippet = _get(session, retries=2)
    assert status == 599
    assert data is None
    assert len(session.calls) == 3, "one request and two retries"


def test_without_the_retry_budget_the_network_error_stays():
    session = _session(fail_first=1)
    _data, status, _headers, _snippet = _get(session, retries=0)
    assert status == 599
    assert len(session.calls) == 1


def test_a_new_token_keeps_the_cookies_of_the_session():
    session = _session(fail_first=0)
    session.cookies["auth_token"] = "a" * 40
    before = session.proxies["https"]
    assert repin_proxy_session(session) is True
    assert session.proxies["https"] != before
    assert "alice" in session.proxies["https"]
    assert session.cookies["auth_token"] == "a" * 40


def test_a_proxy_without_the_placeholder_does_not_retry():
    """A static proxy has one exit. A retry reaches the same exit and adds a timeout for nothing."""
    session = _session(fail_first=1, proxy="http://user:pw@203.0.113.7:8000")
    data, status, _headers, _snippet = _get(session, retries=2)
    assert status == 599
    assert data is None
    assert len(session.calls) == 1


def test_a_proxy_without_the_placeholder_keeps_its_url():
    static = "http://user:pw@203.0.113.7:8000"
    session = _session(fail_first=0, proxy=static)
    before = dict(session.proxies)
    assert repin_proxy_session(session) is False
    assert session.proxies == before
