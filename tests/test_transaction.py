from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

from Scweet.transaction import TransactionIdProvider

# Fake home page HTML that contains the ondemand.s chunk reference in the format
# that _extract_ondemand_url expects.
_HOME_HTML_WITH_ONDEMAND = (
    '<html><head></head><body>'
    '<script>var a={,123:"ondemand.s",456:"other"};var b={123:"abc123def456",456:"xyz"};</script>'
    '</body></html>'
)

_HOME_HTML_WITHOUT_ONDEMAND = "<html><head></head><body>login page</body></html>"


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text
        self.content = text.encode()


class _FakeSession:
    def __init__(self, *, home_html: str = _HOME_HTML_WITH_ONDEMAND):
        self.headers = {}
        self.closed = False
        self.get_calls: list[dict] = []
        self._home_html = home_html

    def request(self, method: str, url: str, **kwargs):
        return _FakeResponse(status_code=200, text=self._home_html)

    def get(self, url: str, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        return _FakeResponse(status_code=200, text="fake ondemand js")

    def close(self):
        self.closed = True


def test_transaction_provider_builds_client_transaction_from_migration_page(monkeypatch):
    from bs4 import BeautifulSoup

    mock_ct_instance = MagicMock()
    mock_ct_instance.generate_transaction_id.return_value = "tx-generated"
    mock_ct_class = MagicMock(return_value=mock_ct_instance)

    xct_mod = types.ModuleType("x_client_transaction")
    xct_mod.ClientTransaction = mock_ct_class
    utils_mod = types.ModuleType("x_client_transaction.utils")
    utils_mod.handle_x_migration = lambda session: BeautifulSoup(_HOME_HTML_WITH_ONDEMAND, "html.parser")

    monkeypatch.setitem(sys.modules, "x_client_transaction", xct_mod)
    monkeypatch.setitem(sys.modules, "x_client_transaction.utils", utils_mod)

    session = _FakeSession(home_html=_HOME_HTML_WITH_ONDEMAND)
    provider = TransactionIdProvider(
        session_factory=lambda: session,
        prefer_curl_cffi=False,
        refresh_ttl_s=900,
    )

    tx_id = provider.generate(method="GET", path="/i/api/graphql/qid/SearchTimeline")

    assert tx_id == "tx-generated"
    assert session.get_calls and "ondemand.s.abc123def456a.js" in session.get_calls[0]["url"]
    assert session.closed is True
    mock_ct_class.assert_called_once()


def test_transaction_provider_returns_none_when_ondemand_url_unavailable(monkeypatch):
    from bs4 import BeautifulSoup

    xct_mod = types.ModuleType("x_client_transaction")
    xct_mod.ClientTransaction = MagicMock()
    utils_mod = types.ModuleType("x_client_transaction.utils")
    utils_mod.handle_x_migration = lambda session: BeautifulSoup(_HOME_HTML_WITHOUT_ONDEMAND, "html.parser")

    monkeypatch.setitem(sys.modules, "x_client_transaction", xct_mod)
    monkeypatch.setitem(sys.modules, "x_client_transaction.utils", utils_mod)

    session = _FakeSession(home_html=_HOME_HTML_WITHOUT_ONDEMAND)
    provider = TransactionIdProvider(
        session_factory=lambda: session,
        prefer_curl_cffi=False,
        refresh_ttl_s=900,
        # One build attempt, so this test covers the ondemand fallback only. The
        # retry of a failed build has its own test in test_transaction_id_guard.py.
        init_attempts=1,
    )

    tx_id = provider.generate(method="GET", path="/i/api/graphql/qid/SearchTimeline")

    assert tx_id is None
    # The provider retries once against home_url, because handle_x_migration reads https://x.com, which
    # serves a shell with no ondemand marker. Here that page also lacks it, so the bootstrap still fails.
    assert [call["url"] for call in session.get_calls] == ["https://x.com/home"]
    assert session.closed is True


# ── X serves the marker only to an accepted cookie ─────────────────────

from pathlib import Path as _Path
import logging as _logging

from Scweet.http_utils import classify_x_page

_LOGIN_PAGE_URL = "https://x.com/i/jf/onboarding/web?redirect_after_login=%2Fhome&mode=login"
_LOGIN_PAGE_HTML = (_Path(__file__).parent / "fixtures" / "x_login_page.html").read_text(encoding="utf-8")


class _ListHandler(_logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _transaction_logs():
    handler = _ListHandler()
    logger = _logging.getLogger("Scweet.transaction")
    logger.addHandler(handler)
    logger.setLevel(_logging.DEBUG)
    return handler, logger


class _CookieAwareSession(_FakeSession):
    """X serves the full page to the accepted cookie and its login page to every other request."""

    def __init__(self, cookies, accepted_token: str):
        super().__init__(home_html=_HOME_HTML_WITHOUT_ONDEMAND)
        self.cookies = dict(cookies or {})
        self.accepted = self.cookies.get("auth_token") == accepted_token

    def get(self, url: str, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        if "ondemand.s" in url:
            return _FakeResponse(status_code=200, text="fake ondemand js")
        if self.accepted:
            return _FakeResponse(status_code=200, text=_HOME_HTML_WITH_ONDEMAND)
        response = _FakeResponse(status_code=200, text=_LOGIN_PAGE_HTML)
        response.url = _LOGIN_PAGE_URL
        return response


def _install_fake_x_client_transaction(monkeypatch):
    from bs4 import BeautifulSoup

    mock_ct_instance = MagicMock()
    mock_ct_instance.generate_transaction_id.return_value = "tx-generated"
    xct_mod = types.ModuleType("x_client_transaction")
    xct_mod.ClientTransaction = MagicMock(return_value=mock_ct_instance)
    utils_mod = types.ModuleType("x_client_transaction.utils")
    utils_mod.handle_x_migration = lambda session: BeautifulSoup(_HOME_HTML_WITHOUT_ONDEMAND, "html.parser")
    monkeypatch.setitem(sys.modules, "x_client_transaction", xct_mod)
    monkeypatch.setitem(sys.modules, "x_client_transaction.utils", utils_mod)


def test_the_provider_tries_the_next_account_when_x_rejects_the_first(monkeypatch):
    """A state file can hold a row with a revoked token next to a fresh one.

    The old code read one row, with no order and no check, and X answered its login page to it. No header
    was built, and every request of the fresh account answered 404. Reproduced 2026-09-28 with one state
    file, a revoked token and then a good one.
    """
    _install_fake_x_client_transaction(monkeypatch)
    sessions: list[_CookieAwareSession] = []
    provider = TransactionIdProvider(
        prefer_curl_cffi=False,
        init_attempts=1,
        cookie_sets=[
            {"username": "stale_row", "cookies": {"auth_token": "revoked", "ct0": "c1"}},
            {"username": "fresh_row", "cookies": {"auth_token": "accepted", "ct0": "c2"}},
        ],
    )

    def _factory():
        session = _CookieAwareSession(provider._cookies, accepted_token="accepted")
        sessions.append(session)
        return session

    provider.session_factory = _factory
    handler, logger = _transaction_logs()
    try:
        tx_id = provider.generate(method="GET", path="/i/api/graphql/qid/SearchTimeline")
    finally:
        logger.removeHandler(handler)

    assert tx_id == "tx-generated"
    assert [session.accepted for session in sessions] == [False, True]
    assert any("stale_row" in m and "trying the next account" in m for m in handler.messages), handler.messages
    assert all("revoked" not in m and "accepted" not in m for m in handler.messages), "a log never holds a token"


def test_a_bootstrap_that_x_rejects_everywhere_names_the_cause_and_the_action(monkeypatch):
    _install_fake_x_client_transaction(monkeypatch)
    provider = TransactionIdProvider(
        prefer_curl_cffi=False,
        init_attempts=1,
        cookie_sets=[{"username": "only_row", "cookies": {"auth_token": "revoked", "ct0": "c1"}}],
    )
    provider.session_factory = lambda: _CookieAwareSession(provider._cookies, accepted_token="other")
    handler, logger = _transaction_logs()
    try:
        assert provider.generate(method="GET", path="/i/api/graphql/qid/SearchTimeline") is None
    finally:
        logger.removeHandler(handler)
    final = [m for m in handler.messages if m.startswith("Transaction-id bootstrap failed: X answered")]
    assert final, handler.messages
    assert "login page" in final[-1] and "fresh auth_token" in final[-1]


def test_the_classification_reads_the_real_login_page():
    """The page that X serves to a rejected cookie, captured 2026-09-28: 16,852 bytes, no marker."""
    assert classify_x_page(_LOGIN_PAGE_HTML, _LOGIN_PAGE_URL) == "login"
    assert classify_x_page(_LOGIN_PAGE_HTML) == "login", "the title alone names the page when no URL is known"
    assert classify_x_page(_HOME_HTML_WITH_ONDEMAND) == "full"
    assert classify_x_page("<html><title>X. It’s what’s happening / X</title></html>", "https://x.com/") == "shell"
