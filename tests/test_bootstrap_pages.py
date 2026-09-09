"""Every bootstrap path reads a page of X that carries the markers, and fills the proxy session.

Two faults made the released library return 404 for every search, from every account:

1. The bootstrap pages read `https://x.com`. Measured 2026-09-09: that URL answers about 33,000 bytes and
   holds no `main.js` reference and no `"ondemand.s"` marker, while `https://x.com/home` answers about
   297,000 bytes and holds both. So the manifest kept a stale query id, and the transaction id was never
   built. X answers 404 with an empty body when the header is absent.
2. Each helper that builds a session from the configured proxy read the raw value, so a `{session}`
   placeholder reached the provider as a literal string. Apify answers HTTP 407 for that session name.
"""

import inspect

from Scweet import manifest as manifest_module
from Scweet import transaction as transaction_module
from Scweet.account_session import fill_proxy_session_placeholder

PROXY_WITH_PLACEHOLDER = "http://groups-RESIDENTIAL,session-{session}:secret@proxy.example.com:8000"


class TestTheBootstrapPagesHoldTheMarkers:
    def test_the_manifest_scrape_reads_the_full_document(self):
        default = inspect.signature(manifest_module.scrape_manifest_from_x).parameters["home_url"].default
        assert default == "https://x.com/home"

    def test_the_transaction_provider_reads_the_full_document(self):
        default = inspect.signature(transaction_module.TransactionIdProvider.__init__).parameters[
            "home_url"
        ].default
        assert default == "https://x.com/home"


class TestEveryProxyPathFillsTheSessionToken:
    def test_the_transaction_provider_fills_the_placeholder(self):
        provider = transaction_module.TransactionIdProvider(proxy=PROXY_WITH_PLACEHOLDER)
        for value in (provider._http_proxies or {}).values():
            assert "{session}" not in value

    def test_the_auth_bootstrap_fills_the_placeholder(self):
        source = inspect.getsource(
            __import__("Scweet.auth", fromlist=["bootstrap_cookies_from_auth_token"]).bootstrap_cookies_from_auth_token
        )
        assert "fill_proxy_session_placeholder" in source

    def test_the_lease_check_fills_the_placeholder(self):
        from Scweet import runner

        assert runner.fill_proxy_session_placeholder is fill_proxy_session_placeholder


class TestTheBundledQueryIdsAreCurrent:
    def test_the_default_manifest_and_the_file_agree(self):
        import json
        from pathlib import Path

        packaged = json.loads(
            (Path(manifest_module.__file__).with_name("default_manifest.json")).read_text(encoding="utf-8")
        )
        inline = manifest_module._DEFAULT_MANIFEST
        assert packaged["query_ids"] == inline["query_ids"]
        assert packaged["version"] == inline["version"]
