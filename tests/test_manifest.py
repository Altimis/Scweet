from __future__ import annotations

import asyncio

from Scweet.manifest import ManifestProvider, scrape_manifest_from_x, _extract_operation_features
from Scweet.repos import ManifestRepo

def test_manifest_provider_uses_local_fallback_when_no_remote_url(tmp_path):
    provider = ManifestProvider(
        db_path=str(tmp_path / "state.db"),
        manifest_url=None,
        ttl_s=120,
    )

    manifest = asyncio.run(provider.get_manifest())

    assert manifest.version
    assert manifest.fingerprint
    assert manifest.query_ids["search_timeline"]
    assert "search_timeline" in manifest.endpoints


def test_manifest_provider_remote_success_writes_cache(tmp_path, monkeypatch):
    remote_payload = {
        "version": "remote-v1",
        "query_ids": {"search_timeline": "remote-query-id"},
        "endpoints": {"search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline"},
        "operation_features": {
            "search_timeline": {"feature_remote": True},
            "user_by_screen_name": {"withAuxiliaryUserLabels": True},
        },
        "operation_field_toggles": {
            "user_by_screen_name": {"withPayments": False},
        },
        "features": {"feature_x": True},
    }

    import Scweet.manifest as manifest_mod

    def fake_fetch(self):
        assert self.manifest_url == "https://example.com/manifest.json"
        return remote_payload, "etag-v1"

    monkeypatch.setattr(manifest_mod.ManifestProvider, "_fetch_remote_manifest_sync", fake_fetch)

    db_path = str(tmp_path / "state.db")
    provider = ManifestProvider(db_path=db_path, manifest_url="https://example.com/manifest.json", ttl_s=300)
    manifest = asyncio.run(provider.get_manifest())

    assert manifest.version == "remote-v1"
    assert manifest.query_ids["search_timeline"] == "remote-query-id"
    assert manifest.features_for("search_timeline")["feature_remote"] is True
    assert manifest.features_for("search_timeline")["feature_x"] is True
    assert manifest.field_toggles_for("user_by_screen_name") == {"withPayments": False}

    cached = ManifestRepo(db_path).get_cached("https://example.com/manifest.json")
    assert cached is not None
    assert cached["etag"] == "etag-v1"
    assert cached["manifest"]["version"] == "remote-v1"


def test_manifest_provider_remote_failure_falls_back_to_cache_then_local(tmp_path, monkeypatch):
    db_path = str(tmp_path / "state.db")
    url = "https://example.com/manifest.json"

    cached_payload = {
        "version": "cached-v1",
        "query_ids": {"search_timeline": "cached-query"},
        "endpoints": {"search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline"},
        "operation_features": {"search_timeline": {"feature_cached": True}},
        "operation_field_toggles": {"user_tweets": {"withArticlePlainText": False}},
        "features": {"cached": True},
    }
    ManifestRepo(db_path).set_cached(url, cached_payload, ttl_s=300, etag="cached-etag")

    import Scweet.manifest as manifest_mod

    def failing_fetch(self):
        raise RuntimeError("network down")

    monkeypatch.setattr(manifest_mod.ManifestProvider, "_fetch_remote_manifest_sync", failing_fetch)

    provider = ManifestProvider(db_path=db_path, manifest_url=url, ttl_s=300)
    cached_manifest = asyncio.run(provider.get_manifest())
    assert cached_manifest.version == "cached-v1"

    # no cache in a fresh DB -> local fallback
    fresh_provider = ManifestProvider(
        db_path=str(tmp_path / "fresh.db"),
        manifest_url=url,
        ttl_s=300,
    )
    local_manifest = asyncio.run(fresh_provider.get_manifest())
    assert local_manifest.version.startswith("v4-default")


def test_manifest_provider_invalid_remote_payload_falls_back_without_crashing(tmp_path, monkeypatch):
    url = "https://example.com/manifest.json"
    db_path = str(tmp_path / "state.db")

    # Seed cache so invalid remote falls back to cached payload.
    ManifestRepo(db_path).set_cached(
        url,
        {
            "version": "cached-v2",
            "query_ids": {"search_timeline": "cached2"},
            "endpoints": {"search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline"},
            "operation_features": {"search_timeline": {"feature_cached_v2": True}},
            "operation_field_toggles": {"followers": {"withSafetyModeUserFields": True}},
            "features": {"cached": True},
        },
        ttl_s=300,
    )

    import Scweet.manifest as manifest_mod

    monkeypatch.setattr(
        manifest_mod.ManifestProvider,
        "_fetch_remote_manifest_sync",
        lambda self: ({"version": "bad"}, None),
    )

    provider = ManifestProvider(db_path=db_path, manifest_url=url, ttl_s=300)
    manifest = asyncio.run(provider.get_manifest())

    assert manifest.version == "cached-v2"


def test_manifest_model_operation_overrides_are_backward_compatible():
    base_payload = {
        "version": "compat-v1",
        "query_ids": {"search_timeline": "qid"},
        "endpoints": {"search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline"},
        "features": {"global_feature": True},
    }
    manifest_without_overrides = ManifestProvider(
        db_path=":memory:",
        manifest_url=None,
        ttl_s=120,
    )._coerce_manifest(base_payload)
    assert manifest_without_overrides is not None
    assert manifest_without_overrides.features_for("search_timeline") == {"global_feature": True}
    assert manifest_without_overrides.field_toggles_for("search_timeline") is None

    with_overrides = dict(base_payload)
    with_overrides["operation_features"] = {"search_timeline": {"op_feature": 1}}
    with_overrides["operation_field_toggles"] = {"search_timeline": {"withFoo": False}}
    manifest_with_overrides = ManifestProvider(
        db_path=":memory:",
        manifest_url=None,
        ttl_s=120,
    )._coerce_manifest(with_overrides)
    assert manifest_with_overrides is not None
    assert manifest_with_overrides.features_for("search_timeline") == {"global_feature": True, "op_feature": 1}
    assert manifest_with_overrides.field_toggles_for("search_timeline") == {"withFoo": False}


# ── scrape_manifest_from_x tests ─────────────────────────────────────


def test_scrape_manifest_from_x_with_mocked_responses(monkeypatch):
    """Test the scraping logic with fake X home page and main.js content."""

    fake_home = (
        '<html><script src="https://abs.twimg.com/responsive-web/client-web/main.abc123.js"></script></html>'
    )
    fake_js = (
        'e.exports={queryId:"FRESH_SEARCH_ID",operationName:"SearchTimeline",operationType:"query",'
        'metadata:{featureSwitches:["rweb_video_screen_enabled","new_feature_flag"],fieldToggles:[]}}'
        'e.exports={queryId:"FRESH_USER_ID",operationName:"UserByScreenName",operationType:"query",'
        'metadata:{featureSwitches:["rweb_video_screen_enabled"],fieldToggles:[]}}'
        'e.exports={queryId:"FRESH_TIMELINE_ID",operationName:"UserTweets",operationType:"query",'
        'metadata:{featureSwitches:[],fieldToggles:[]}}'
        'e.exports={queryId:"FRESH_FOLLOWERS_ID",operationName:"Followers",operationType:"query",'
        'metadata:{featureSwitches:[],fieldToggles:[]}}'
        'e.exports={queryId:"FRESH_FOLLOWING_ID",operationName:"Following",operationType:"query",'
        'metadata:{featureSwitches:[],fieldToggles:[]}}'
        'e.exports={queryId:"FRESH_VERIFIED_ID",operationName:"BlueVerifiedFollowers",operationType:"query",'
        'metadata:{featureSwitches:[],fieldToggles:[]}}'
    )

    class _FakeResponse:
        def __init__(self, text, status_code=200):
            self.text = text
            self.status_code = status_code

    class _FakeSession:
        def __init__(self, **kwargs):
            pass

        def get(self, url, **kwargs):
            if "main." in url:
                return _FakeResponse(fake_js)
            return _FakeResponse(fake_home)

        def close(self):
            pass

    import Scweet.manifest as manifest_mod
    original_import = __builtins__.__import__ if hasattr(__builtins__, '__import__') else __import__

    monkeypatch.setattr(
        manifest_mod,
        "CurlSession",
        _FakeSession,
        raising=False,
    )

    # Monkey-patch the import inside scrape_manifest_from_x
    def patched_scrape(**kwargs):
        import types
        fake_curl = types.ModuleType("curl_cffi.requests")
        fake_curl.Session = _FakeSession
        monkeypatch.setitem(__import__('sys').modules, "curl_cffi.requests", fake_curl)
        return scrape_manifest_from_x(**kwargs)

    result = patched_scrape()

    assert result["query_ids"]["search_timeline"] == "FRESH_SEARCH_ID"
    assert result["query_ids"]["user_lookup_screen_name"] == "FRESH_USER_ID"
    assert result["query_ids"]["profile_timeline"] == "FRESH_TIMELINE_ID"
    assert result["query_ids"]["followers"] == "FRESH_FOLLOWERS_ID"
    assert result["query_ids"]["following"] == "FRESH_FOLLOWING_ID"
    assert result["query_ids"]["verified_followers"] == "FRESH_VERIFIED_ID"
    assert result["version"] == "v5-live-scrape"
    assert "search_timeline" in result["endpoints"]


def test_extract_operation_features_parses_js_correctly():
    js_text = (
        'e.exports={queryId:"abc",operationName:"SearchTimeline",operationType:"query",'
        'metadata:{featureSwitches:["feat_a","feat_b"],fieldToggles:[]}}'
    )
    out = {}
    _extract_operation_features(js_text, "SearchTimeline", "search_timeline", out)
    assert "search_timeline" in out
    assert out["search_timeline"] == {"feat_a": False, "feat_b": False}


def test_scrape_from_x_sync_caches_result(tmp_path, monkeypatch):
    scraped = {
        "version": "v5-live-scrape",
        "query_ids": {"search_timeline": "live-id"},
        "endpoints": {"search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline"},
        "features": {"f": True},
    }

    import Scweet.manifest as manifest_mod
    monkeypatch.setattr(manifest_mod, "scrape_manifest_from_x", lambda **kw: scraped)

    db_path = str(tmp_path / "state.db")
    provider = ManifestProvider(db_path=db_path, manifest_url=None, ttl_s=300)

    result = provider.scrape_from_x_sync()
    assert result.query_ids["search_timeline"] == "live-id"

    # Second call should use cache (even though we replace the function)
    monkeypatch.setattr(manifest_mod, "scrape_manifest_from_x", lambda **kw: (_ for _ in ()).throw(RuntimeError("should not be called")))
    cached_result = provider.scrape_from_x_sync()
    assert cached_result.query_ids["search_timeline"] == "live-id"


def test_get_manifest_prefers_live_scrape_cache(tmp_path, monkeypatch):
    db_path = str(tmp_path / "state.db")

    # Seed the live-scrape cache
    live_payload = {
        "version": "v5-live",
        "query_ids": {"search_timeline": "live-qid"},
        "endpoints": {"search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline"},
        "features": {"f": True},
    }
    ManifestRepo(db_path).set_cached("x-live-scrape", live_payload, ttl_s=300)

    provider = ManifestProvider(db_path=db_path, manifest_url=None, ttl_s=300)
    manifest = asyncio.run(provider.get_manifest())
    assert manifest.query_ids["search_timeline"] == "live-qid"
