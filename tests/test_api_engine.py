from __future__ import annotations

import asyncio
import json

import pytest

from Scweet.api_engine import ApiEngine, JSON_DECODE_STATUS, NETWORK_ERROR_STATUS
from Scweet.manifest import ManifestModel
from Scweet.models import FollowsRequest, ProfileTimelineRequest, SearchRequest


# ── Shared test helpers ────────────────────────────────────────────────


class _ManifestProvider:
    def __init__(self, manifest: ManifestModel):
        self.manifest = manifest

    async def get_manifest(self) -> ManifestModel:
        return self.manifest


class _Response:
    def __init__(self, status_code: int, payload=None, headers=None, text="", json_error: bool = False):
        self.status_code = status_code
        self._payload = payload
        self.headers = headers or {}
        self.text = text
        self._json_error = json_error

    def json(self):
        if self._json_error:
            raise ValueError("invalid json")
        return self._payload


class _Session:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.last_request = None
        self.closed = False

    async def get(self, url, **kwargs):
        self.last_request = {"url": url, **kwargs}
        if self.error is not None:
            raise self.error
        return self.response

    async def close(self):
        self.closed = True


class _SyncSession:
    def __init__(self, response=None, error: Exception | None = None):
        self.response = response
        self.error = error
        self.last_request = None
        self.closed = False

    def get(self, url, **kwargs):
        self.last_request = {"url": url, **kwargs}
        if self.error is not None:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


def _manifest() -> ManifestModel:
    return ManifestModel.model_validate(
        {
            "version": "test",
            "query_ids": {
                "search_timeline": "qid",
                "user_lookup_screen_name": "qid_user",
                "profile_timeline": "qid_profile",
                "following": "qid_following",
            },
            "endpoints": {
                "search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline",
                "user_lookup_screen_name": "https://x.com/i/api/graphql/{query_id}/UserByScreenName",
                "profile_timeline": "https://x.com/i/api/graphql/{query_id}/UserTweets",
                "following": "https://x.com/i/api/graphql/{query_id}/Following",
            },
            "features": {"a": True},
            "timeout_s": 7,
        }
    )


def _engine_for_response(response=None, error: Exception | None = None):
    session = _Session(response=response, error=error)
    engine = ApiEngine(
        config=None,
        accounts_repo=None,
        manifest_provider=_ManifestProvider(_manifest()),
        session_factory=lambda: session,
    )
    return engine, session


class _TxProvider:
    def __init__(self, tx_id: str):
        self.tx_id = tx_id
        self.calls: list[dict] = []

    def generate(self, *, method: str, path: str):
        self.calls.append({"method": method, "path": path})
        return self.tx_id


def _run_search(engine: ApiEngine):
    return asyncio.run(
        engine.search_tweets(
            SearchRequest(
                since="2025-01-01",
                until="2025-01-02",
                search_query="bitcoin",
            )
        )
    )


# ── Error handling tests ───────────────────────────────────────────────


def test_api_engine_maps_429_response():
    engine, session = _engine_for_response(_Response(status_code=429, payload=None, text="too many requests"))

    out = _run_search(engine)

    assert out["status_code"] == 429
    assert out["result"].tweets == []
    assert session.last_request["timeout"] == 7
    assert session.closed is True


def test_api_engine_adds_transaction_id_header_when_provider_available():
    tx = _TxProvider("tx-abc-123")
    session = _Session(response=_Response(status_code=429, payload=None))
    engine = ApiEngine(
        config=None,
        accounts_repo=None,
        manifest_provider=_ManifestProvider(_manifest()),
        session_factory=lambda: session,
        transaction_id_provider=tx,
    )

    out = _run_search(engine)

    assert out["status_code"] == 429
    assert tx.calls and tx.calls[0]["method"] == "GET"
    assert "/i/api/graphql/" in tx.calls[0]["path"]
    assert session.last_request["headers"]["X-Client-Transaction-Id"] == "tx-abc-123"


def test_api_engine_maps_auth_error_codes_and_404_path():
    engine_401, _ = _engine_for_response(
        _Response(status_code=200, payload={"errors": [{"message": "Authorization failed"}]})
    )
    out_401 = _run_search(engine_401)
    assert out_401["status_code"] == 401

    engine_403, _ = _engine_for_response(
        _Response(status_code=200, payload={"errors": [{"message": "forbidden by policy"}]})
    )
    out_403 = _run_search(engine_403)
    assert out_403["status_code"] == 403

    engine_404, _ = _engine_for_response(_Response(status_code=404, payload=None))
    out_404 = _run_search(engine_404)
    assert out_404["status_code"] == 404


def test_api_engine_handles_transient_network_and_5xx():
    engine_503, _ = _engine_for_response(_Response(status_code=503, payload=None))
    out_503 = _run_search(engine_503)
    assert out_503["status_code"] == 503

    engine_net, _ = _engine_for_response(error=RuntimeError("connection reset"))
    out_net = _run_search(engine_net)
    assert out_net["status_code"] == NETWORK_ERROR_STATUS


def test_api_engine_handles_json_decode_failure():
    engine, _ = _engine_for_response(_Response(status_code=200, payload=None, json_error=True, text="not-json"))

    out = _run_search(engine)

    assert out["status_code"] == JSON_DECODE_STATUS


def test_api_engine_auto_mode_prefers_async_session_path():
    session = _Session(response=_Response(status_code=429, payload=None))
    engine = ApiEngine(
        config={"api_http_mode": "auto"},
        accounts_repo=None,
        manifest_provider=_ManifestProvider(_manifest()),
        session_factory=lambda: session,
    )

    out = _run_search(engine)

    assert out["status_code"] == 429
    assert ("async", "auto") in engine._logged_http_mode_selection


def test_api_engine_explicit_async_mode_uses_non_blocking_path():
    session = _Session(response=_Response(status_code=429, payload=None))
    engine = ApiEngine(
        config={"api_http_mode": "async"},
        accounts_repo=None,
        manifest_provider=_ManifestProvider(_manifest()),
        session_factory=lambda: session,
    )

    out = _run_search(engine)

    assert out["status_code"] == 429
    assert ("async", "explicit") in engine._logged_http_mode_selection


def test_api_engine_auto_mode_sync_fallback_for_non_async_session():
    session = _SyncSession(response=_Response(status_code=429, payload=None))
    engine = ApiEngine(
        config={"api_http_mode": "auto"},
        accounts_repo=None,
        manifest_provider=_ManifestProvider(_manifest()),
        session_factory=lambda: session,
    )

    out = _run_search(engine)

    assert out["status_code"] == 429
    assert session.last_request is not None
    assert ("sync", "auto_fallback_non_async_session") in engine._logged_http_mode_selection


def test_api_engine_explicit_sync_mode_uses_sync_path():
    session = _SyncSession(response=_Response(status_code=429, payload=None))
    engine = ApiEngine(
        config={"api_http_mode": "sync"},
        accounts_repo=None,
        manifest_provider=_ManifestProvider(_manifest()),
        session_factory=lambda: session,
    )

    out = _run_search(engine)

    assert out["status_code"] == 429
    assert session.last_request is not None
    assert ("sync", "explicit") in engine._logged_http_mode_selection


def test_api_engine_does_not_swallow_cancelled_error():
    session = _Session(response=None, error=asyncio.CancelledError())
    engine = ApiEngine(
        config={"api_http_mode": "auto"},
        accounts_repo=None,
        manifest_provider=_ManifestProvider(_manifest()),
        session_factory=lambda: session,
    )

    with pytest.raises(asyncio.CancelledError):
        _run_search(engine)


def test_api_engine_parses_tweets_and_cursor_into_canonical_models():
    payload = {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [
                            {
                                "type": "TimelineAddEntries",
                                "entries": [
                                    {
                                        "entryId": "tweet-190001",
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {
                                                    "result": {
                                                        "rest_id": "190001",
                                                        "legacy": {
                                                            "id_str": "190001",
                                                            "created_at": "Wed Oct 10 20:19:24 +0000 2018",
                                                            "full_text": "hello world",
                                                            "reply_count": 5,
                                                            "favorite_count": 7,
                                                            "retweet_count": 3,
                                                            "extended_entities": {
                                                                "media": [
                                                                    {
                                                                        "media_url_https": "https://pbs.twimg.com/media/test.jpg"
                                                                    }
                                                                ]
                                                            },
                                                        },
                                                        "core": {
                                                            "user_results": {
                                                                "result": {
                                                                    "legacy": {
                                                                        "screen_name": "alice",
                                                                        "name": "Alice",
                                                                    }
                                                                }
                                                            }
                                                        },
                                                    }
                                                }
                                            }
                                        },
                                    },
                                    {
                                        "entryId": "cursor-bottom-0",
                                        "content": {"value": "CURSOR_NEXT"},
                                    },
                                ],
                            }
                        ]
                    }
                }
            }
        }
    }

    engine, _ = _engine_for_response(_Response(status_code=200, payload=payload))

    out = _run_search(engine)

    assert out["status_code"] == 200
    assert out["cursor"] == "CURSOR_NEXT"
    assert out["continue_with_cursor"] is True
    assert len(out["result"].tweets) == 1

    tweet = out["result"].tweets[0]
    assert tweet.tweet_id == "190001"
    assert tweet.user.screen_name == "alice"
    assert tweet.user.name == "Alice"
    assert tweet.text == "hello world"
    assert tweet.comments == 5
    assert tweet.likes == 7
    assert tweet.retweets == 3
    assert tweet.media.image_links == ["https://pbs.twimg.com/media/test.jpg"]
    assert tweet.tweet_url == "https://x.com/alice/status/190001"


def test_api_engine_uses_page_size_hint_and_ignores_request_limit_for_graphql_count():
    session = _Session(response=_Response(status_code=429, payload=None))
    engine = ApiEngine(
        config={"api_page_size": 55},
        accounts_repo=None,
        manifest_provider=_ManifestProvider(_manifest()),
        session_factory=lambda: session,
    )

    out = asyncio.run(
        engine.search_tweets(
            {
                "since": "2025-01-01",
                "until": "2025-01-02",
                "words": ["bitcoin"],
                "limit": 10_000,
                "_page_size": 80,
            }
        )
    )

    assert out["status_code"] == 429
    variables = json.loads(session.last_request["params"]["variables"])
    assert variables["count"] == 80

    session2 = _Session(response=_Response(status_code=429, payload=None))
    engine2 = ApiEngine(
        config={"api_page_size": 33},
        accounts_repo=None,
        manifest_provider=_ManifestProvider(_manifest()),
        session_factory=lambda: session2,
    )
    _run_search(engine2)
    variables2 = json.loads(session2.last_request["params"]["variables"])
    assert variables2["count"] == 33


def test_api_engine_builds_raw_query_from_structured_fields_without_duplicate_ops():
    session = _Session(response=_Response(status_code=429, payload=None))
    engine = ApiEngine(
        config={"api_page_size": 40},
        accounts_repo=None,
        manifest_provider=_ManifestProvider(_manifest()),
        session_factory=lambda: session,
    )

    out = asyncio.run(
        engine.search_tweets(
            {
                "since": "2025-01-01_00:00:00_UTC",
                "until": "2025-01-02_23:59:59_UTC",
                "search_query": "(openai) lang:en",
                "any_words": ["chatgpt", "gpt4"],
                "from_users": ["OpenAI"],
                "tweet_type": "exclude_replies",
                "has_links": True,
                "min_likes": 100,
            }
        )
    )

    assert out["status_code"] == 429
    variables = json.loads(session.last_request["params"]["variables"])
    raw_query = variables["rawQuery"]
    assert "(openai) lang:en" in raw_query
    assert "(chatgpt OR gpt4)" in raw_query
    assert "from:OpenAI" in raw_query
    assert "-filter:replies" in raw_query
    assert "filter:links" in raw_query
    assert "min_faves:100" in raw_query
    assert "since:2025-01-01_00:00:00" in raw_query
    assert "until:2025-01-02_23:59:59" in raw_query
    assert raw_query.count("lang:en") == 1


# ── Empty page stop tests ─────────────────────────────────────────────


class _AccountsRepo:
    async def acquire_leases(self, count: int, run_id=None, worker_id_prefix=None):
        _ = count, run_id, worker_id_prefix
        return [{"id": "1", "username": "acct-a", "lease_id": "lease-a"}]

    async def record_usage(self, lease_id: str, pages: int = 0, tweets: int = 0):
        _ = lease_id, pages, tweets
        return None

    async def release(self, lease_id: str, fields_to_set: dict | None = None, fields_to_inc: dict | None = None):
        _ = lease_id, fields_to_set, fields_to_inc
        return True


def test_profile_timeline_stops_after_consecutive_empty_pages():
    async def _run():
        engine = ApiEngine(
            config={
                "max_account_switches": 0,
                "requests_per_min": 10_000,
                "min_delay_s": 0.0,
                "lease_heartbeat_s": 0.0,
            },
            accounts_repo=_AccountsRepo(),
            manifest_provider=_ManifestProvider(_manifest()),
            session_factory=lambda: object(),
        )
        timeline_calls = 0

        async def _acquire_profile_session():
            return object(), {"id": "1", "username": "acct-a"}, "lease-a", None

        async def _close_profile_timeline_session(
            session=None, builder=None, lease_id=None, status_code=200, headers=None,
            use_cooldown=False, effective_status_code=None,
        ):
            return None

        async def _resolve_target_username(target):
            return target.get("username")

        async def _graphql_get(url, params, timeout_s, session=None, account_context=None):
            nonlocal timeline_calls
            if "UserByScreenName" in url:
                return {"data": {}}, 200, {}, ""
            timeline_calls += 1
            return {"data": {}}, 200, {}, ""

        engine._acquire_profile_session = _acquire_profile_session
        engine._close_profile_timeline_session = _close_profile_timeline_session
        engine._resolve_target_username = _resolve_target_username
        engine._graphql_get = _graphql_get
        engine._build_user_lookup_params = lambda username, manifest: {"u": username}
        engine._build_profile_timeline_params = (
            lambda user_id, cursor, manifest, runtime_hints=None: {"id": user_id, "cursor": cursor}
        )
        engine._extract_user_result = lambda payload: {"rest_id": "uid-1"}
        engine._extract_profile_tweets_and_cursor = (
            lambda payload: ([], f"CURSOR-{timeline_calls}")
        )

        out = await engine.get_profile_tweets(
            ProfileTimelineRequest(
                targets=[{"username": "OpenAI"}],
                max_pages_per_profile=10,
                max_empty_pages=2,
            )
        )

        assert timeline_calls == 2
        assert out["completed"] is True
        assert out["resume_cursors"] == {}
        assert out["limit_reached"] is False
        assert out["result"].stats.tasks_done == 1
        assert out["result"].stats.tasks_failed == 0

    asyncio.run(_run())


def test_follows_stops_after_consecutive_empty_pages():
    async def _run():
        engine = ApiEngine(
            config={
                "max_account_switches": 0,
                "requests_per_min": 10_000,
                "min_delay_s": 0.0,
                "lease_heartbeat_s": 0.0,
            },
            accounts_repo=_AccountsRepo(),
            manifest_provider=_ManifestProvider(_manifest()),
            session_factory=lambda: object(),
        )
        follows_calls = 0

        async def _acquire_follows_session():
            return object(), {"id": "1", "username": "acct-a"}, "lease-a", None

        async def _close_profile_timeline_session(
            session=None, builder=None, lease_id=None, status_code=200, headers=None,
            use_cooldown=False, effective_status_code=None,
        ):
            return None

        async def _resolve_target_username(target):
            return target.get("username")

        async def _graphql_get(url, params, timeout_s, session=None, account_context=None):
            nonlocal follows_calls
            if "UserByScreenName" in url:
                return {"data": {}}, 200, {}, ""
            follows_calls += 1
            return {"data": {}}, 200, {}, ""

        engine._acquire_follows_session = _acquire_follows_session
        engine._close_profile_timeline_session = _close_profile_timeline_session
        engine._resolve_target_username = _resolve_target_username
        engine._graphql_get = _graphql_get
        engine._build_user_lookup_params = lambda username, manifest: {"u": username}
        engine._build_follows_params = (
            lambda user_id, cursor, manifest, operation, runtime_hints=None: {"id": user_id, "cursor": cursor}
        )
        engine._extract_user_result = lambda payload: {"rest_id": "uid-1"}
        engine._extract_follows_users_and_cursor = (
            lambda payload: ([], f"CURSOR-{follows_calls}")
        )

        out = await engine.get_follows(
            FollowsRequest(
                targets=[{"username": "OpenAI"}],
                follow_type="following",
                max_pages_per_profile=10,
                max_empty_pages=2,
            )
        )

        assert follows_calls == 2
        assert out["completed"] is True
        assert out["resume_cursors"] == {}
        assert out["limit_reached"] is False
        assert out["status_code"] == 404
        assert out["meta"]["resolved_targets"] == 1
        assert out["meta"]["failed_targets"] == 0

    asyncio.run(_run())


def test_follows_default_max_pages_per_profile_is_unbounded():
    async def _run():
        engine = ApiEngine(
            config={
                "max_account_switches": 0,
                "requests_per_min": 10_000,
                "min_delay_s": 0.0,
                "lease_heartbeat_s": 0.0,
            },
            accounts_repo=_AccountsRepo(),
            manifest_provider=_ManifestProvider(_manifest()),
            session_factory=lambda: object(),
        )
        follows_calls = 0

        async def _acquire_follows_session():
            return object(), {"id": "1", "username": "acct-a"}, "lease-a", None

        async def _resolve_target_username(target):
            return target.get("username")

        async def _graphql_get(url, params, timeout_s, session=None, account_context=None):
            nonlocal follows_calls
            if "UserByScreenName" in url:
                return {"data": {}}, 200, {}, ""
            follows_calls += 1
            return {"data": {"page": follows_calls}}, 200, {}, ""

        def _extract_follows_users_and_cursor(payload):
            page = int(((payload or {}).get("data") or {}).get("page") or 0)
            if page <= 0:
                return [], None
            users = [{"rest_id": f"user-{page}", "legacy": {"screen_name": f"user_{page}"}}]
            next_cursor = f"CURSOR-{page}" if page < 35 else None
            return users, next_cursor

        engine._acquire_follows_session = _acquire_follows_session
        engine._resolve_target_username = _resolve_target_username
        engine._graphql_get = _graphql_get
        engine._build_user_lookup_params = lambda username, manifest: {"u": username}
        engine._build_follows_params = (
            lambda user_id, cursor, manifest, operation, runtime_hints=None: {"id": user_id, "cursor": cursor}
        )
        engine._extract_user_result = lambda payload: {"rest_id": "uid-1"}
        engine._extract_follows_users_and_cursor = _extract_follows_users_and_cursor

        out = await engine.get_follows(
            FollowsRequest(
                targets=[{"username": "OpenAI"}],
                follow_type="following",
            )
        )

        assert follows_calls == 35
        assert out["completed"] is True
        assert out["resume_cursors"] == {}
        assert out["limit_reached"] is False
        assert out["status_code"] == 200
        assert len(out["follows"]) == 35

    asyncio.run(_run())


def test_follows_user_id_target_skips_username_lookup():
    async def _run():
        engine = ApiEngine(
            config={
                "max_account_switches": 0,
                "requests_per_min": 10_000,
                "min_delay_s": 0.0,
                "lease_heartbeat_s": 0.0,
            },
            accounts_repo=_AccountsRepo(),
            manifest_provider=_ManifestProvider(_manifest()),
            session_factory=lambda: object(),
        )

        lookup_calls = 0
        follows_calls = 0
        seen_user_ids: list[str] = []

        async def _acquire_follows_session():
            return object(), {"id": "1", "username": "acct-a"}, "lease-a", None

        async def _resolve_target_username(target):
            return None

        async def _graphql_get(url, params, timeout_s, session=None, account_context=None):
            nonlocal lookup_calls, follows_calls
            if "UserByScreenName" in url:
                lookup_calls += 1
                return {"data": {}}, 200, {}, ""
            follows_calls += 1
            return {"data": {"page": 1}}, 200, {}, ""

        def _build_follows_params(user_id, cursor, manifest, operation, runtime_hints=None):
            seen_user_ids.append(str(user_id))
            return {"id": user_id}

        def _extract_follows_users_and_cursor(payload):
            users = [{"rest_id": "u1", "legacy": {"screen_name": "u1"}}]
            return users, None

        engine._acquire_follows_session = _acquire_follows_session
        engine._resolve_target_username = _resolve_target_username
        engine._graphql_get = _graphql_get
        engine._build_follows_params = _build_follows_params
        engine._extract_follows_users_and_cursor = _extract_follows_users_and_cursor

        out = await engine.get_follows(
            FollowsRequest(
                targets=[{"user_id": "44196397"}],
                follow_type="following",
                max_pages_per_profile=1,
            )
        )

        assert lookup_calls == 0
        assert follows_calls == 1
        assert seen_user_ids == ["44196397"]
        assert len(out["follows"]) == 1
        assert out["follows"][0]["target"]["user_id"] == "44196397"

    asyncio.run(_run())


# ── User result mapping tests ──────────────────────────────────────────


def _mapping_engine() -> ApiEngine:
    class _NoManifest:
        async def get_manifest(self):
            raise RuntimeError("manifest is not required for mapping tests")

    return ApiEngine(config=None, accounts_repo=None, manifest_provider=_NoManifest())


def _sample_user_result() -> dict:
    return {
        "rest_id": "908005339341221888",
        "avatar": {"image_url": "https://pbs.twimg.com/profile_images/example_normal.jpg"},
        "core": {
            "created_at": "Wed Sep 13 16:31:57 +0000 2017",
            "name": "Manolo J C R",
            "screen_name": "ManoloJCR",
        },
        "legacy": {
            "description": "Compendio de hobbies",
            "entities": {
                "url": {
                    "urls": [
                        {
                            "expanded_url": "https://example.com",
                            "url": "https://t.co/example",
                        }
                    ]
                }
            },
            "followers_count": 701,
            "friends_count": 1074,
            "statuses_count": 11315,
            "favourites_count": 17619,
            "media_count": 2720,
            "listed_count": 8,
            "profile_banner_url": "https://pbs.twimg.com/profile_banners/example",
        },
        "location": {"location": "Ribera Del Tajo"},
        "privacy": {"protected": True},
        "verification": {"verified": True},
        "is_blue_verified": False,
    }


def test_follow_record_mapping_uses_fallback_nodes_for_user_fields():
    engine = _mapping_engine()
    row = engine._map_user_result_to_follow_record(
        user_result=_sample_user_result(),
        target={"raw": "OpenAI", "source": "usernames", "username": "OpenAI", "profile_url": "https://x.com/OpenAI"},
        follow_type="followers",
    )

    assert row["user_id"] == "908005339341221888"
    assert row["username"] == "ManoloJCR"
    assert row["name"] == "Manolo J C R"
    assert row["created_at"] == "Wed Sep 13 16:31:57 +0000 2017"
    assert row["location"] == "Ribera Del Tajo"
    assert row["verified"] is True
    assert row["protected"] is True
    assert row["profile_image_url"] == "https://pbs.twimg.com/profile_images/example_normal.jpg"
    assert row["url"] == "https://example.com"


def test_profile_record_mapping_uses_same_fallback_nodes():
    engine = _mapping_engine()
    row = engine._map_user_result_to_profile_record(
        _sample_user_result(),
        target={"raw": "OpenAI", "source": "usernames"},
        username="fallback_username",
    )

    assert row["user_id"] == "908005339341221888"
    assert row["username"] == "ManoloJCR"
    assert row["name"] == "Manolo J C R"
    assert row["created_at"] == "Wed Sep 13 16:31:57 +0000 2017"
    assert row["location"] == "Ribera Del Tajo"
    assert row["verified"] is True
    assert row["protected"] is True
    assert row["profile_image_url"] == "https://pbs.twimg.com/profile_images/example_normal.jpg"
    assert row["url"] == "https://example.com"
