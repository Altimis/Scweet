"""Each new read operation of 5.7.0 parses the real answer of X.

Each expected value below was read by hand from the captured fixture in
tests/fixtures/. Every fixture is a real capture of 2026-09-13. A parser
that expects a field which X renames returns an empty page, and an empty
page looks the same as the end of the results, so every test asserts a
real value and never only a shape.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from Scweet.api_engine import ApiEngine
from Scweet.manifest import (
    ManifestModel,
    _DEFAULT_MANIFEST,
    _fill_missing_operations,
)
from Scweet.models import TweetLookupRequest, TweetRepliesRequest, UserIdsRequest

FIXTURES = Path(__file__).parent / "fixtures"

FOCAL_TWEET_ID = "2098932438055469451"


def _engine() -> ApiEngine:
    return ApiEngine(config={}, accounts_repo=None, manifest_provider=None)


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _emptied(payload: dict) -> dict:
    """Remove the entries of every instruction of a captured page.

    This derives the empty page from the real envelope. An invented shape
    would not prove that the parser walks the real one.
    """

    def _walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("instructions"), list):
                for instruction in node["instructions"]:
                    if isinstance(instruction, dict):
                        instruction.pop("entry", None)
                        if isinstance(instruction.get("entries"), list):
                            instruction["entries"] = []
            for value in node.values():
                _walk(value)

    _walk(payload)
    return payload


# ── tweet_lookup (TweetResultsByRestIds) ───────────────────────────────


def test_tweet_lookup_parses_each_result_row():
    nodes = _engine()._extract_tweet_lookup_results(_fixture("tweet_lookup_batch.json"))
    assert len(nodes) == 2
    records = [_engine()._tweet_result_to_record(node) for node in nodes]
    assert records[0].tweet_id == "2090227249551483321"
    assert records[0].likes == 11
    assert records[0].views == 355
    assert records[1].tweet_id == "2090227137332855238"
    assert records[1].likes == 154
    assert records[1].views == 31757


def test_tweet_lookup_a_row_without_a_tweet_gives_no_row_and_no_error():
    """A deleted tweet answers a row without a usable result node."""
    payload = _fixture("tweet_lookup_batch.json")
    payload["data"]["tweetResult"][0].pop("result")
    nodes = _engine()._extract_tweet_lookup_results(payload)
    assert len(nodes) == 1
    assert nodes[0].get("rest_id") == "2090227137332855238"


def test_tweet_lookup_an_empty_list_gives_no_rows():
    payload = _fixture("tweet_lookup_batch.json")
    payload["data"]["tweetResult"] = []
    assert _engine()._extract_tweet_lookup_results(payload) == []


def test_get_tweet_info_splits_the_ids_into_batches_of_at_most_50():
    """X caps one TweetResultsByRestIds request at 50 ids. One oversized
    request refuses every id in it, so the engine must split."""
    engine = _engine()
    engine.manifest_provider = _ManifestProviderStub()
    calls: list[list[str]] = []

    async def fake_graphql_get(*, url, params, timeout_s, session, account_context):
        calls.append(json.loads(params["variables"])["tweetIds"])
        return {"data": {"tweetResult": []}}, 200, {}, ""

    engine._graphql_get = fake_graphql_get
    request = TweetLookupRequest(tweet_ids=[str(i) for i in range(120)])
    response = asyncio.run(engine.get_tweet_info(request))
    assert [len(batch) for batch in calls] == [50, 50, 20]
    assert response["status_code"] == 200


# ── tweet_detail (TweetDetail) ─────────────────────────────────────────


def test_tweet_replies_parse_every_reply_and_skip_the_focal_tweet():
    """The focal tweet is the input of the caller. A run that returns it
    as its own reply gives the caller a wrong row."""
    records, cursor = _engine()._extract_conversation_tweets_and_cursor(
        _fixture("tweet_detail_page.json"), focal_tweet_id=FOCAL_TWEET_ID
    )
    assert len(records) == 41
    assert FOCAL_TWEET_ID not in {record.tweet_id for record in records}
    first = records[0]
    assert first.tweet_id == "2098932881007759623"
    assert first.user.screen_name == "DFF6769"
    assert first.likes == 194
    assert first.in_reply_to_tweet_id == FOCAL_TWEET_ID


def test_tweet_replies_read_the_bottom_cursor():
    _, cursor = _engine()._extract_conversation_tweets_and_cursor(
        _fixture("tweet_detail_page.json"), focal_tweet_id=FOCAL_TWEET_ID
    )
    assert cursor is not None
    assert len(cursor) == 623
    assert cursor.startswith("DAAKCgABHSLbi0B__mMLAAIAAAGoRW1QQzZ3QUFBZlEvZ0dKTjB2R3AvQUFB")
    assert cursor.endswith("Qm90dG9tAAA")


def test_tweet_replies_empty_path():
    records, cursor = _engine()._extract_conversation_tweets_and_cursor(
        _emptied(_fixture("tweet_detail_page.json")), focal_tweet_id=FOCAL_TWEET_ID
    )
    assert records == []
    assert cursor is None


def test_get_tweet_replies_walks_the_bottom_cursor():
    """The first page ends on a Bottom cursor while replies remain. A run
    that stops there loses the rest of the conversation."""
    engine = _engine()
    engine.manifest_provider = _ManifestProviderStub()
    pages = [_fixture("tweet_detail_page.json"), _emptied(_fixture("tweet_detail_page.json"))]
    cursors: list = []

    async def fake_graphql_get(*, url, params, timeout_s, session, account_context):
        cursors.append(json.loads(params["variables"]).get("cursor"))
        return pages.pop(0), 200, {}, ""

    engine._graphql_get = fake_graphql_get
    request = TweetRepliesRequest(tweet_id=FOCAL_TWEET_ID, max_empty_pages=1)
    response = asyncio.run(engine.get_tweet_replies(request))
    assert len(response["items"]) == 41
    assert response["items"][0]["tweet_id"] == "2098932881007759623"
    assert cursors[0] is None
    assert cursors[1] is not None and cursors[1].endswith("Qm90dG9tAAA")


def test_tweet_detail_variables_carry_the_switches_that_the_probe_needed():
    manifest = ManifestModel.model_validate(_DEFAULT_MANIFEST)
    params = _engine()._build_tweet_detail_params(FOCAL_TWEET_ID, None, manifest)
    variables = json.loads(params["variables"])
    assert variables["focalTweetId"] == FOCAL_TWEET_ID
    assert variables["with_rux_injections"] is True
    assert variables["withV2Timeline"] is True
    toggles = json.loads(params["fieldToggles"])
    assert toggles == {"withArticleRichContentState": True, "withArticlePlainText": False}


# ── reposters (Retweeters) ─────────────────────────────────────────────


def test_reposters_parser_reads_the_users_and_the_bottom_cursor():
    nodes, cursor = _engine()._extract_reposters_users_and_cursor(
        _fixture("reposters_page.json")
    )
    assert len(nodes) == 20
    assert nodes[0]["rest_id"] == "208950453"
    assert cursor == "HBaAgIDKmqP/iTQAAA=="


def test_a_reposter_row_sets_the_type_reposters():
    """A caller that mixes follower rows and reposter rows separates them
    by the type field."""
    nodes, _ = _engine()._extract_reposters_users_and_cursor(_fixture("reposters_page.json"))
    record = _engine()._map_user_result_to_reposter_record(
        nodes[0], tweet_id="1876300934411194840"
    )
    assert record["type"] == "reposters"
    assert record["username"] == "JMC68344"
    assert record["followers_count"] == 487
    assert record["target"]["raw"] == "1876300934411194840"


def test_reposters_empty_path():
    nodes, cursor = _engine()._extract_reposters_users_and_cursor(
        _emptied(_fixture("reposters_page.json"))
    )
    assert nodes == []
    assert cursor is None


# ── user_lookup_rest_id (UserByRestId) ─────────────────────────────────


def test_user_lookup_by_rest_id_parses_the_profile():
    payload = _fixture("user_lookup_rest_id.json")
    node = _engine()._extract_user_result(payload)
    record = _engine()._map_user_result_to_profile_record(
        node, target={"raw": "44196397", "source": "user_ids"}, username=""
    )
    assert record["user_id"] == "44196397"
    assert record["username"] == "elonmusk"
    assert record["followers_count"] == 241658848
    assert record["following_count"] == 1406
    assert record["favourites_count"] == 248028
    assert record["profile_banner_url"] == (
        "https://pbs.twimg.com/profile_banners/44196397/1774145451"
    )


# ── user_lookup_batch (UsersByRestIds) ─────────────────────────────────


def test_user_lookup_batch_parses_each_user_row():
    nodes = _engine()._extract_user_batch_results(_fixture("user_lookup_batch.json"))
    assert len(nodes) == 2
    first = _engine()._map_user_result_to_profile_record(
        nodes[0], target={"raw": "44196397", "source": "user_ids"}, username=""
    )
    second = _engine()._map_user_result_to_profile_record(
        nodes[1], target={"raw": "783214", "source": "user_ids"}, username=""
    )
    assert first["username"] == "elonmusk"
    assert first["followers_count"] == 241658851
    assert second["user_id"] == "783214"
    assert second["username"] == "X"
    assert second["followers_count"] == 60744241


def test_user_lookup_batch_empty_path():
    payload = _fixture("user_lookup_batch.json")
    payload["data"]["users"] = []
    assert _engine()._extract_user_batch_results(payload) == []


def test_get_users_by_ids_splits_the_ids_into_batches_of_at_most_100():
    """X caps one UsersByRestIds request at 100 ids."""
    engine = _engine()
    engine.manifest_provider = _ManifestProviderStub()
    calls: list[list[str]] = []

    async def fake_graphql_get(*, url, params, timeout_s, session, account_context):
        calls.append(json.loads(params["variables"])["userIds"])
        return {"data": {"users": []}}, 200, {}, ""

    engine._graphql_get = fake_graphql_get
    request = UserIdsRequest(user_ids=[str(i) for i in range(250)])
    response = asyncio.run(engine.get_users_by_ids(request))
    assert [len(batch) for batch in calls] == [100, 100, 50]
    assert response["status_code"] == 200


def test_get_users_by_ids_keeps_the_input_order():
    """X can reorder the rows of a batch answer. The caller matches a row
    to its input by position, so the input order wins."""
    engine = _engine()
    engine.manifest_provider = _ManifestProviderStub()
    payload = _fixture("user_lookup_batch.json")

    async def fake_graphql_get(*, url, params, timeout_s, session, account_context):
        return payload, 200, {}, ""

    engine._graphql_get = fake_graphql_get
    # The fixture answers elonmusk (44196397) first. The request asks for X first.
    request = UserIdsRequest(user_ids=["783214", "44196397"])
    response = asyncio.run(engine.get_users_by_ids(request))
    assert [row["user_id"] for row in response["items"]] == ["783214", "44196397"]


# ── search_users (SearchTimeline with product People) ──────────────────


def test_search_users_parses_the_people_rows():
    nodes, cursor = _engine()._extract_search_users_and_cursor(
        _fixture("search_people_page.json")
    )
    assert len(nodes) == 20
    record = _engine()._map_user_result_to_search_user_record(nodes[0], query="python")
    assert record["type"] == "search_users"
    assert record["user_id"] == "743780794997547008"
    assert record["username"] == "PythonDvz"
    assert record["followers_count"] == 185833
    assert cursor is not None
    assert cursor.startswith("DAAFCgABHSLblP5__z8L")


def test_search_users_empty_path():
    nodes, cursor = _engine()._extract_search_users_and_cursor(
        _emptied(_fixture("search_people_page.json"))
    )
    assert nodes == []
    assert cursor is None


def test_search_users_variables_ask_for_the_people_product():
    manifest = ManifestModel.model_validate(_DEFAULT_MANIFEST)
    params = _engine()._build_search_users_params("python", None, manifest)
    variables = json.loads(params["variables"])
    assert variables["product"] == "People"
    assert variables["rawQuery"] == "python"


# ── explore_page (ExplorePage) ─────────────────────────────────────────


def test_trending_maps_the_name_the_context_and_the_trend_id():
    rows = _engine()._extract_trend_items(_fixture("explore_page.json"))
    assert len(rows) == 9
    first = rows[0]
    assert first["name"] == "Oasis Fans Await 2027 Tour Details Announcement Today"
    assert first["context"] == "1 day ago · Other · 12K posts"
    assert first["trend_id"] == "2098822744158740700"
    assert first["raw"]["itemType"] == "TimelineTrend"


def test_trending_empty_path():
    rows = _engine()._extract_trend_items(_emptied(_fixture("explore_page.json")))
    assert rows == []


# ── profile_media (UserMedia) ──────────────────────────────────────────


def test_profile_media_tweets_come_from_the_grid_module():
    """UserMedia sends the tweets inside a profile-grid module, not as
    plain tweet entries. A parser that reads only tweet entries returns an
    empty page for every media timeline."""
    records, cursor = _engine()._extract_profile_tweets_and_cursor(
        _fixture("profile_media_page.json")
    )
    assert len(records) == 13
    assert records[0].tweet_id == "2099295901529391177"
    assert records[0].likes == 17266
    assert records[0].user.screen_name == "elonmusk"
    assert cursor == "DAABCgABHSLbmKK___0KAAIc-oI9OBbR5ggAAwAAAAIAAA"


def test_get_profile_tweets_requests_the_operation_of_the_request():
    """The request names the timeline operation. A flow that ignores it
    sends every media request to UserTweets and returns the wrong rows."""
    engine = _engine()
    engine.manifest_provider = _ManifestProviderStub()
    urls: list[str] = []

    async def fake_acquire():
        return object(), {"id": "1", "username": "acct-a"}, None, None

    async def fake_graphql_get(*, url, params, timeout_s, session, account_context):
        if "/UserByScreenName" in url:
            return {"data": {"user": {"result": {"rest_id": "44196397"}}}}, 200, {}, ""
        urls.append(url)
        return {"data": {}}, 200, {}, ""

    engine._acquire_profile_session = fake_acquire
    engine._graphql_get = fake_graphql_get
    request = {
        "targets": [{"raw": "elonmusk", "username": "elonmusk"}],
        "max_empty_pages": 1,
        "timeline_operation": "profile_media",
    }
    asyncio.run(engine.get_profile_tweets(request))
    assert urls, "the engine sent no request"
    assert all("/UserMedia" in url for url in urls)


def test_profile_media_empty_path():
    records, cursor = _engine()._extract_profile_tweets_and_cursor(
        _emptied(_fixture("profile_media_page.json"))
    )
    assert records == []
    assert cursor is None


# ── profile_timeline_with_replies (UserTweetsAndReplies) ───────────────


def test_profile_with_replies_reads_the_conversation_modules_too():
    """UserTweetsAndReplies sends a reply inside a profile-conversation
    module. A parser that skips the modules loses every reply."""
    records, cursor = _engine()._extract_profile_tweets_and_cursor(
        _fixture("profile_with_replies_page.json")
    )
    assert len(records) == 32
    ids = {record.tweet_id for record in records}
    # A reply from a conversation module.
    assert "2099170946326143205" in ids
    # The pinned tweet of the profile.
    assert FOCAL_TWEET_ID in ids
    assert cursor == "DAAHCgABHSLbmsW__-sLAAIAAAATMjA5OTQ1MDU2NDY5ODQyMzczMggAAwAAAAIAAA"


# ── manifest ───────────────────────────────────────────────────────────

_NEW_OPERATIONS = {
    "tweet_lookup": ("VwY22EyG-lO-eT6Myg_F0A", "TweetResultsByRestIds"),
    "tweet_detail": ("FyR-GrebyjdkRoW1z6uCgQ", "TweetDetail"),
    "reposters": ("iH7h2J19n7Xd1swL4cNTNg", "Retweeters"),
    "user_lookup_rest_id": ("IdmRdjYxIGI39Hdwkwo5cQ", "UserByRestId"),
    "user_lookup_batch": ("BuQFwM7wpHl00cfHL-r0rA", "UsersByRestIds"),
    "explore_page": ("UgdDQQHSWlNm3LEht3PnLg", "ExplorePage"),
    "profile_media": ("atLYUUmER14HCLFnNUKJgA", "UserMedia"),
    "profile_timeline_with_replies": ("-4Ujf5pYzDdr_qY8qxgF9A", "UserTweetsAndReplies"),
}


def test_every_new_key_resolves_an_endpoint_url_from_the_default_manifest():
    manifest = ManifestModel.model_validate(_DEFAULT_MANIFEST)
    for key, (query_id, operation_name) in _NEW_OPERATIONS.items():
        assert manifest.query_ids[key] == query_id
        url = manifest.endpoints[key].format(query_id=manifest.query_ids[key])
        assert url == f"https://x.com/i/api/graphql/{query_id}/{operation_name}"


def test_the_engine_resolves_a_new_operation_url_without_the_manifest_key():
    """A cached manifest of an older version lacks the new keys. The
    engine must still resolve a working URL for them."""
    minimal = ManifestModel.model_validate(
        {
            "query_ids": {"search_timeline": "qid"},
            "endpoints": {
                "search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline"
            },
        }
    )
    engine = _engine()
    for key, (query_id, operation_name) in _NEW_OPERATIONS.items():
        url = engine._resolve_operation_url(minimal, key)
        assert url == f"https://x.com/i/api/graphql/{query_id}/{operation_name}"


def test_the_scrape_merge_keeps_the_default_id_for_an_operation_in_a_lazy_chunk():
    """Retweeters is absent from main.js because a lazy chunk holds it. A
    scrape that drops the key would turn every reposters request into a 404."""
    query_ids = {"search_timeline": "SCRAPED_ID"}
    endpoints = {"search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline"}
    _fill_missing_operations(query_ids, endpoints)
    assert query_ids["search_timeline"] == "SCRAPED_ID"
    assert query_ids["reposters"] == "iH7h2J19n7Xd1swL4cNTNg"
    assert endpoints["reposters"] == "https://x.com/i/api/graphql/{query_id}/Retweeters"


def test_a_live_scrape_without_retweeters_still_serves_the_reposters_endpoint(monkeypatch):
    """The scrape reads main.js only. Retweeters lives in a lazy chunk, so
    the scrape never finds it, and the scraped manifest must keep the
    bundled id for it."""
    import sys
    import types

    from Scweet.manifest import scrape_manifest_from_x

    fake_home = (
        '<html><script src="https://abs.twimg.com/responsive-web/client-web/main.abc.js">'
        "</script></html>"
    )
    fake_js = (
        'e.exports={queryId:"FRESH_SEARCH_ID",operationName:"SearchTimeline",'
        'operationType:"query",metadata:{featureSwitches:[],fieldToggles:[]}}'
    )

    class _FakeResponse:
        def __init__(self, text):
            self.text = text
            self.status_code = 200

    class _FakeSession:
        def __init__(self, **kwargs):
            pass

        def get(self, url, **kwargs):
            return _FakeResponse(fake_js if "main." in url else fake_home)

        def close(self):
            pass

    fake_curl = types.ModuleType("curl_cffi.requests")
    fake_curl.Session = _FakeSession
    monkeypatch.setitem(sys.modules, "curl_cffi.requests", fake_curl)

    result = scrape_manifest_from_x()
    assert result["query_ids"]["search_timeline"] == "FRESH_SEARCH_ID"
    assert result["query_ids"]["reposters"] == "iH7h2J19n7Xd1swL4cNTNg"
    assert result["endpoints"]["reposters"] == (
        "https://x.com/i/api/graphql/{query_id}/Retweeters"
    )


def test_the_user_lookup_operations_carry_their_feature_switches():
    manifest = ManifestModel.model_validate(_DEFAULT_MANIFEST)
    rest_id_features = manifest.features_for("user_lookup_rest_id")
    batch_features = manifest.features_for("user_lookup_batch")
    shared = [
        "hidden_profile_subscriptions_enabled",
        "subscriptions_verification_info_verified_since_enabled",
        "subscriptions_verification_info_is_identity_verified_enabled",
        "responsive_web_twitter_article_notes_tab_enabled",
        "subscriptions_feature_can_gift_premium",
        "highlights_tweets_tab_ui_enabled",
    ]
    for name in shared:
        assert rest_id_features[name] is True
        assert batch_features[name] is True
    # Only UserByRestId needs this one.
    assert rest_id_features["hidden_profile_likes_enabled"] is True
    assert "hidden_profile_likes_enabled" not in batch_features


class _ManifestProviderStub:
    async def get_manifest(self):
        return ManifestModel.model_validate(_DEFAULT_MANIFEST)
