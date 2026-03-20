from __future__ import annotations

import sys
import types

from bs4 import BeautifulSoup

from Scweet.transaction import TransactionIdProvider


class _FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text


class _FakeSession:
    def __init__(self):
        self.headers = {}
        self.closed = False
        self.get_calls: list[dict] = []

    def get(self, url: str, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        return _FakeResponse(status_code=200, text="<html><body>ondemand</body></html>")

    def close(self):
        self.closed = True


def _install_fake_x_client_transaction(monkeypatch, *, ondemand_url: str | None):
    state: dict = {}

    xct_mod = types.ModuleType("x_client_transaction")
    utils_mod = types.ModuleType("x_client_transaction.utils")

    class _ClientTransaction:
        def __init__(self, *, home_page_response, ondemand_file_response):
            state["home_page_type"] = type(home_page_response).__name__
            state["ondemand_file_type"] = type(ondemand_file_response).__name__

        def generate_transaction_id(self, *, method: str, path: str):
            state["generated"] = {"method": method, "path": path}
            return "tx-generated"

    def _handle_x_migration(session):
        state["migration_called"] = True
        state["migration_session_type"] = type(session).__name__
        return BeautifulSoup("<html><head></head><body>home</body></html>", "html.parser")

    def _get_ondemand_file_url(*, response):
        state["ondemand_input_type"] = type(response).__name__
        return ondemand_url

    xct_mod.ClientTransaction = _ClientTransaction
    utils_mod.handle_x_migration = _handle_x_migration
    utils_mod.get_ondemand_file_url = _get_ondemand_file_url

    monkeypatch.setitem(sys.modules, "x_client_transaction", xct_mod)
    monkeypatch.setitem(sys.modules, "x_client_transaction.utils", utils_mod)
    return state


def test_transaction_provider_builds_client_transaction_from_migration_page(monkeypatch):
    state = _install_fake_x_client_transaction(monkeypatch, ondemand_url="https://x.com/ondemand.s.abc123.js")
    session = _FakeSession()
    provider = TransactionIdProvider(
        session_factory=lambda: session,
        prefer_curl_cffi=False,
        refresh_ttl_s=900,
    )

    tx_id = provider.generate(method="GET", path="/i/api/graphql/qid/SearchTimeline")

    assert tx_id == "tx-generated"
    assert state["migration_called"] is True
    assert state["ondemand_input_type"] == "BeautifulSoup"
    assert state["home_page_type"] == "BeautifulSoup"
    assert state["generated"]["method"] == "GET"
    assert state["generated"]["path"] == "/i/api/graphql/qid/SearchTimeline"
    assert session.get_calls and session.get_calls[0]["url"] == "https://x.com/ondemand.s.abc123.js"
    assert session.closed is True


def test_transaction_provider_returns_none_when_ondemand_url_unavailable(monkeypatch):
    state = _install_fake_x_client_transaction(monkeypatch, ondemand_url=None)
    session = _FakeSession()
    provider = TransactionIdProvider(
        session_factory=lambda: session,
        prefer_curl_cffi=False,
        refresh_ttl_s=900,
    )

    tx_id = provider.generate(method="GET", path="/i/api/graphql/qid/SearchTimeline")

    assert tx_id is None
    assert state["migration_called"] is True
    assert state["ondemand_input_type"] == "BeautifulSoup"
    assert session.get_calls == []
    assert session.closed is True
