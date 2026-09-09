"""The proxy check sends the same URL as the account session.

A proxy URL may carry a `{session}` placeholder. The session builder replaces it with a token for each
account. The smoke check on lease read the raw configuration instead, so it sent the literal string
`{session}` as part of the proxy user name. A provider rejects that name: Apify answers HTTP 407, the
check fails for every account, and the run ends with `ProxyError` before it sends one request to X.
Measured 2026-09-09: 15 of 15 checks failed with 407 while the same URL with a filled token answered 200.
"""

from Scweet.account_session import fill_proxy_session_placeholder

PROXY_WITH_PLACEHOLDER = "http://groups-RESIDENTIAL,session-{session}:secret@proxy.example.com:8000"


class TestTheCheckFillsThePlaceholder:
    def test_a_string_proxy_keeps_no_literal_placeholder(self):
        filled = fill_proxy_session_placeholder(PROXY_WITH_PLACEHOLDER, {"username": "acct-one"})
        assert "{session}" not in filled
        assert "session-acctone" in filled

    def test_a_dict_proxy_shares_one_token_across_the_schemes(self):
        proxy = {"http": PROXY_WITH_PLACEHOLDER, "https": PROXY_WITH_PLACEHOLDER}
        filled = fill_proxy_session_placeholder(proxy, {"username": "acct-one"})
        assert "{session}" not in filled["http"]
        assert filled["http"] == filled["https"]

    def test_a_proxy_without_a_placeholder_passes_unchanged(self):
        plain = "http://user:pass@proxy.example.com:8000"
        assert fill_proxy_session_placeholder(plain, {"username": "acct-one"}) == plain

    def test_the_runner_check_path_imports_the_same_helper(self):
        from Scweet import runner

        assert runner.fill_proxy_session_placeholder is fill_proxy_session_placeholder
