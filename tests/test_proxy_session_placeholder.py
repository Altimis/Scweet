"""A proxy URL with `{session}` gives each account session its own proxy session.

A rotating proxy provider pins one exit IP to the session name inside the proxy URL. With one static URL,
every account shares one exit IP. When that exit IP dies, a retry of a failed request reaches the same dead
exit, so the retry fails too, and the run loses the task. With the placeholder, each account keeps its own
exit IP for the life of one session, and a session that is built again gets a new one, so a retry runs on a
different exit.
"""

from types import SimpleNamespace

from Scweet.account_session import AccountSessionBuilder
from Scweet.config import ScweetConfig

AUTH = {"auth_token": "a" * 40, "ct0": "c" * 32}
PROXY_TEMPLATE = "http://groups-X,session-{session}:pw@proxy.example.com:8000"


def _account(name):
    return {"id": 1, "username": name, "cookies": dict(AUTH)}


class _FakeSession:
    def __init__(self):
        self.proxies = {}
        self.cookies = {}
        self.headers = {}


def _build(builder, name):
    session, _meta = builder.build(_account(name))
    return session.proxies.get("http", "")


def _builder():
    return AccountSessionBuilder(session_factory=_FakeSession, proxy=PROXY_TEMPLATE)


class TestTheSessionPlaceholder:
    def test_two_accounts_get_two_proxy_sessions(self):
        builder = _builder()
        url_a = _build(builder, "alice")
        url_b = _build(builder, "bob")
        assert "{session}" not in url_a and "{session}" not in url_b
        assert "alice" in url_a and "bob" in url_b
        assert url_a != url_b, "each account must get its own proxy session"

    def test_a_rebuilt_session_gets_a_new_proxy_session(self):
        """The retry path. A rebuilt session must reach a different exit IP, so the token must change."""
        builder = _builder()
        first = _build(builder, "alice")
        second = _build(builder, "alice")
        assert first != second, "a session built again must get a new session token"

    def test_a_proxy_without_the_placeholder_passes_unchanged(self):
        builder = AccountSessionBuilder(session_factory=_FakeSession, proxy="http://u:p@proxy.example.com:8000")
        url = _build(builder, "alice")
        assert url == "http://u:p@proxy.example.com:8000"

    def test_the_config_accepts_a_placeholder_url(self):
        # The pydantic validator must not reject the braces, or nobody can configure the feature.
        cfg = ScweetConfig(proxy=PROXY_TEMPLATE)
        assert "{session}" in str(cfg.proxy)
