from __future__ import annotations

import asyncio

import pytest

from Scweet.account_session import AccountSessionBuilder
from Scweet.exceptions import AccountSessionAuthError, AccountSessionTransientError


class _FakeCookieJar:
    def __init__(self):
        self._values: dict[str, str] = {}

    def set(self, name, value, domain=None):
        _ = domain
        self._values[str(name)] = str(value)

    def get_dict(self):
        return dict(self._values)


class _FakeSession:
    def __init__(self):
        self.headers: dict[str, str] = {}
        self.cookies = _FakeCookieJar()
        self.closed = False

    def close(self):
        self.closed = True


class _FakeAsyncSession:
    def __init__(self):
        self.headers: dict[str, str] = {}
        self.cookies = _FakeCookieJar()
        self.closed = False

    async def get(self, url, **kwargs):
        _ = url, kwargs
        return None

    async def close(self):
        self.closed = True


class _FakeProxySession(_FakeSession):
    def __init__(self):
        super().__init__()
        self.proxies: dict[str, str] = {}
        self.trust_env = True


def test_account_session_builder_applies_required_headers_and_cookies():
    fake_session = _FakeSession()
    builder = AccountSessionBuilder(
        session_factory=lambda: fake_session,
        default_bearer_token="bearer-default",
    )

    session, metadata = builder.build(
        {
            "id": 11,
            "username": "acct-a",
            "auth_token": "auth-11",
            "csrf": "csrf-11",
            "cookies_json": [{"name": "lang", "value": "en"}],
        }
    )

    assert session is fake_session
    assert metadata["username"] == "acct-a"
    assert metadata["account_id"] == 11
    assert metadata["has_auth_token"] is True
    assert metadata["has_csrf"] is True
    assert metadata["has_bearer"] is True
    assert metadata["cookie_count"] >= 2
    assert metadata["session_mode"] == "sync"

    assert session.headers["Authorization"] == "Bearer bearer-default"
    assert session.headers["X-Csrf-Token"] == "csrf-11"
    assert session.headers["X-Twitter-Auth-Type"] == "OAuth2Session"
    assert session.headers["X-Twitter-Active-User"] == "yes"
    assert session.headers["X-Twitter-Client-Language"] == "en"
    assert "Mozilla/5.0" in session.headers["User-Agent"]
    assert session.headers["Referer"] == "https://x.com/"

    cookies = session.cookies.get_dict()
    assert cookies["auth_token"] == "auth-11"
    assert cookies["ct0"] == "csrf-11"
    assert cookies["lang"] == "en"

    asyncio.run(builder.close(session))
    assert fake_session.closed is True


def test_account_session_builder_applies_per_account_proxy_override():
    fake_session = _FakeProxySession()
    builder = AccountSessionBuilder(
        session_factory=lambda: fake_session,
        default_bearer_token="bearer-default",
        proxy={"host": "global.proxy", "port": 1111},
    )

    session, _metadata = builder.build(
        {
            "id": 13,
            "username": "acct-proxy",
            "auth_token": "auth-13",
            "csrf": "csrf-13",
            "cookies_json": {"auth_token": "auth-13", "ct0": "csrf-13"},
            "proxy_json": {"host": "acct.proxy", "port": 2222},
        }
    )

    assert session.proxies["http"] == "http://acct.proxy:2222"
    assert session.proxies["https"] == "http://acct.proxy:2222"
    assert session.trust_env is False


def test_account_session_builder_supports_async_session_and_preserves_auth_material():
    fake_session = _FakeAsyncSession()
    builder = AccountSessionBuilder(
        session_factory=lambda: fake_session,
        api_http_mode="async",
        default_bearer_token="bearer-default",
    )

    session, metadata = builder.build(
        {
            "id": 12,
            "username": "acct-async",
            "auth_token": "auth-12",
            "csrf": "csrf-12",
            "cookies_json": {"lang": "en"},
        }
    )

    assert session is fake_session
    assert metadata["account_id"] == 12
    assert metadata["username"] == "acct-async"
    assert metadata["cookie_count"] >= 2
    assert metadata["session_mode"] == "async"

    assert session.headers["Authorization"] == "Bearer bearer-default"
    assert session.headers["X-Csrf-Token"] == "csrf-12"
    assert session.headers["X-Twitter-Auth-Type"] == "OAuth2Session"
    assert session.headers["X-Twitter-Active-User"] == "yes"
    assert session.headers["X-Twitter-Client-Language"] == "en"
    assert session.headers["Referer"] == "https://x.com/"

    cookies = session.cookies.get_dict()
    assert cookies["auth_token"] == "auth-12"
    assert cookies["ct0"] == "csrf-12"
    assert cookies["lang"] == "en"

    asyncio.run(builder.close(session))
    assert fake_session.closed is True


def test_account_session_builder_rejects_missing_auth_material():
    builder = AccountSessionBuilder(
        session_factory=lambda: _FakeSession(),
        default_bearer_token="bearer-default",
    )

    with pytest.raises(AccountSessionAuthError) as excinfo:
        builder.build({"username": "acct-a", "auth_token": "auth-1"})

    assert excinfo.value.code == "missing_auth_material"
    assert excinfo.value.reason == "missing_csrf"
    assert excinfo.value.status_code == 401


def test_account_session_builder_classifies_session_factory_error_as_transient():
    def _raise():
        raise RuntimeError("boom")

    builder = AccountSessionBuilder(
        session_factory=_raise,
        default_bearer_token="bearer-default",
    )

    with pytest.raises(AccountSessionTransientError) as excinfo:
        builder.build(
            {
                "username": "acct-a",
                "auth_token": "auth-1",
                "csrf": "csrf-1",
                "cookies_json": {"auth_token": "auth-1", "ct0": "csrf-1"},
            }
        )

    assert excinfo.value.code == "session_factory_error"
    assert excinfo.value.reason == "RuntimeError"
    assert excinfo.value.status_code == 599
