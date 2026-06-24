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
    )

    tx_id = provider.generate(method="GET", path="/i/api/graphql/qid/SearchTimeline")

    assert tx_id is None
    assert session.get_calls == []
    assert session.closed is True
