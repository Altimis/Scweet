from __future__ import annotations

import asyncio
import json

import pytest

from Scweet import Scweet as PreferredScweet
from Scweet.api_engine import ApiEngine
from Scweet.config import ScweetConfig
from Scweet.exceptions import AccountPoolExhausted, NetworkError, RunFailed
from Scweet.models import SearchResult, TweetRecord
from Scweet.repos import AccountsRepo


def _write(path, content: str) -> str:
    path.write_text(content, encoding="utf-8")
    return str(path)


def _write_json(path, payload) -> str:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(path)


def _seed_account(db_path: str) -> None:
    repo = AccountsRepo(db_path)
    repo.upsert_account(
        {
            "username": "seed",
            "auth_token": "tok-seed",
            "csrf": "ct0-seed",
            "cookies_json": {"auth_token": "tok-seed", "ct0": "ct0-seed"},
            "status": 1,
        }
    )


class _CaptureRunner:
    def __init__(self):
        self.search_calls = []
        self.profile_timeline_calls = []
        self.follows_calls = []
        self.profile_calls = []

    async def run_search(self, request):
        self.search_calls.append(request)
        return SearchResult(tweets=[])

    async def run_profile_tweets(self, request):
        self.profile_timeline_calls.append(request)
        return {
            "result": SearchResult(tweets=[]),
            "resume_cursors": {},
            "completed": True,
            "limit_reached": False,
        }

    async def run_follows(self, request):
        self.follows_calls.append(request)
        return {
            "follows": [],
            "resume_cursors": {},
            "completed": True,
            "limit_reached": False,
        }

    async def run_profiles(self, request):
        self.profile_calls.append(request)

        class _Result:
            items = []
        return _Result()


# ── Init / provisioning tests ─────────────────────────────────────────


def test_init_with_cookies_file(monkeypatch, tmp_path):
    db_path = str(tmp_path / "state.db")
    cookies_file = _write_json(
        tmp_path / "cookies.json",
        [{"username": "cookie_user", "cookies": {"auth_token": "tok-cookie", "ct0": "ct0-cookie"}}],
    )

    token_bootstrap_calls = []

    def fake_bootstrap_from_token(auth_token: str, timeout_s: int = 30, **kwargs):
        token_bootstrap_calls.append({"auth_token": auth_token, "timeout_s": timeout_s})
        return {"auth_token": auth_token, "ct0": f"ct0-{auth_token}"}

    import Scweet.auth as auth_mod
    monkeypatch.setattr(auth_mod, "bootstrap_cookies_from_auth_token", fake_bootstrap_from_token)

    client = PreferredScweet(cookies_file=cookies_file, db_path=db_path)

    assert client._accounts_repo.count_eligible() >= 1


def test_init_with_cookies_dict(tmp_path):
    db_path = str(tmp_path / "state.db")
    client = PreferredScweet(
        cookies={"auth_token": "tok-a", "ct0": "ct0-a"},
        db_path=db_path,
    )
    assert client._accounts_repo.count_eligible() == 1


def test_init_with_auth_token(monkeypatch, tmp_path):
    db_path = str(tmp_path / "state.db")

    def fake_bootstrap(auth_token: str, timeout_s: int = 30, **kwargs):
        return {"auth_token": auth_token, "ct0": f"ct0-{auth_token}"}

    import Scweet.auth as auth_mod
    monkeypatch.setattr(auth_mod, "bootstrap_cookies_from_auth_token", fake_bootstrap)

    client = PreferredScweet(auth_token="tok-only", db_path=db_path)
    assert client._accounts_repo.count_eligible() == 1


def test_init_provision_false(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("AUTH_TOKEN=tok-env\nCT0=ct0-env\n", encoding="utf-8")

    db_path = str(tmp_path / "state.db")
    client = PreferredScweet(
        db_path=db_path,
        env_path=str(env_path),
        cookies={"auth_token": "tok-cookie", "ct0": "ct0-cookie"},
        provision=False,
    )
    assert client._accounts_repo.count_eligible() == 0


def test_provisioning_imports_env_and_cookies_payload_on_init(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(["USERNAME=env_user", "AUTH_TOKEN=tok-env", "CT0=ct0-env", ""]),
        encoding="utf-8",
    )

    cookies_payload = {"auth_token": "tok-cookie", "ct0": "ct0-cookie", "guest_id": "guest-1"}
    db_path = str(tmp_path / "state.db")

    client = PreferredScweet(
        db_path=db_path,
        env_path=str(env_path),
        cookies=cookies_payload,
    )
    assert client._accounts_repo.count_eligible() == 2


# ── Search tests ───────────────────────────────────────────────────────


def test_search_via_api_engine(monkeypatch, tmp_path):
    db_path = str(tmp_path / "state.db")
    _seed_account(db_path)

    calls: list[object] = []

    async def fake_search(self, request):
        calls.append(request)
        return {
            "result": SearchResult(
                tweets=[
                    TweetRecord(
                        tweet_id="t-1",
                        raw={"rest_id": "t-1", "legacy": {"created_at": "2026-02-01T00:00:00.000Z", "full_text": "hi"}},
                    )
                ]
            ),
            "cursor": None,
            "status_code": 200,
            "headers": {},
        }

    monkeypatch.setattr(ApiEngine, "search_tweets", fake_search)

    client = PreferredScweet(db_path=db_path, provision=False)
    out = asyncio.run(
        client.asearch("openai", since="2026-02-01", until="2026-02-02")
    )
    assert isinstance(out, list)
    assert len(out) == 1
    assert len(calls) >= 1


def test_search_raises_when_no_accounts(tmp_path):
    db_path = str(tmp_path / "state.db")
    client = PreferredScweet(db_path=db_path, provision=False)
    with pytest.raises(AccountPoolExhausted):
        asyncio.run(
            client.asearch("x", since="2026-02-01", until="2026-02-02")
        )


def test_search_raises_on_network_error(monkeypatch, tmp_path):
    db_path = str(tmp_path / "state.db")
    _seed_account(db_path)

    async def fake_search(self, request):
        return {
            "result": SearchResult(),
            "cursor": None,
            "status_code": 599,
            "headers": {},
            "text_snippet": "network down",
        }

    monkeypatch.setattr(ApiEngine, "search_tweets", fake_search)

    client = PreferredScweet(
        db_path=db_path,
        config=ScweetConfig(n_splits=1, concurrency=1),
        provision=False,
    )
    with pytest.raises((NetworkError, RunFailed)):
        asyncio.run(
            client.asearch("x", since="2026-02-01", until="2026-02-02")
        )


def test_raises_run_failed_on_profile_tweets(tmp_path):
    db_path = str(tmp_path / "state.db")
    _seed_account(db_path)
    client = PreferredScweet(db_path=db_path, provision=False)

    class _FailRunner:
        async def run_profile_tweets(self, request):
            raise RunFailed("fail")

    client._runner = _FailRunner()
    with pytest.raises(RunFailed):
        client.get_profile_tweets(["x"])


def test_raises_on_follows(tmp_path):
    db_path = str(tmp_path / "state.db")
    _seed_account(db_path)
    client = PreferredScweet(db_path=db_path, provision=False)

    class _FailRunner:
        async def run_follows(self, request):
            raise NetworkError("no network")

    client._runner = _FailRunner()
    with pytest.raises(NetworkError):
        client.get_followers(["x"])


def test_raises_on_user_info(tmp_path):
    db_path = str(tmp_path / "state.db")
    _seed_account(db_path)
    client = PreferredScweet(db_path=db_path, provision=False)

    class _FailRunner:
        async def run_profiles(self, request):
            raise AccountPoolExhausted("no accounts")

    client._runner = _FailRunner()
    with pytest.raises(AccountPoolExhausted):
        client.get_user_info(["x"])


# ── Config routing tests ──────────────────────────────────────────────


def _client_with_runner(tmp_path):
    client = PreferredScweet(
        db_path=str(tmp_path / "state.db"),
        config=ScweetConfig(max_empty_pages=4),
        provision=False,
    )
    capture = _CaptureRunner()
    client._runner = capture
    return client, capture


def test_search_max_empty_pages_from_config(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(
        client.asearch("openai", since="2026-02-01", until="2026-02-02")
    )
    assert result == []
    assert len(capture.search_calls) == 1
    assert capture.search_calls[0].max_empty_pages == 4


def test_search_max_empty_pages_override(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(
        client.asearch("openai", since="2026-02-01", until="2026-02-02", max_empty_pages=2)
    )
    assert result == []
    assert len(capture.search_calls) == 1
    assert capture.search_calls[0].max_empty_pages == 2


def test_profile_tweets_routes_to_runner(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_profile_tweets(["OpenAI"]))
    assert result == []
    assert len(capture.profile_timeline_calls) == 1
    assert capture.profile_timeline_calls[0].max_empty_pages == 4


def test_followers_routes_to_runner(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_followers(["OpenAI"]))
    assert result == []
    assert len(capture.follows_calls) == 1
    assert capture.follows_calls[0].follow_type == "followers"


def test_following_routes_to_runner(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_following(["OpenAI"]))
    assert result == []
    assert len(capture.follows_calls) == 1
    assert capture.follows_calls[0].follow_type == "following"


def test_user_info_routes_to_runner(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_user_info(["OpenAI"]))
    assert result == []
    assert len(capture.profile_calls) == 1


def test_config_property(tmp_path):
    cfg = ScweetConfig(concurrency=7)
    client = PreferredScweet(db_path=str(tmp_path / "state.db"), config=cfg, provision=False)
    assert client.config.concurrency == 7


def test_db_property(tmp_path):
    client = PreferredScweet(db_path=str(tmp_path / "state.db"), provision=False)
    db = client.db
    summary = db.accounts_summary()
    assert summary["total"] == 0


# ── Sync wrapper tests ────────────────────────────────────────────────


def test_search_sync_delegates_to_async(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = client.search("test", since="2026-02-01", until="2026-02-02")
    assert result == []
    assert len(capture.search_calls) == 1


def test_get_profile_tweets_sync(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = client.get_profile_tweets(["OpenAI"])
    assert result == []
    assert len(capture.profile_timeline_calls) == 1


def test_get_followers_sync(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = client.get_followers(["OpenAI"])
    assert result == []
    assert len(capture.follows_calls) == 1
    assert capture.follows_calls[0].follow_type == "followers"


def test_get_following_sync(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = client.get_following(["OpenAI"])
    assert result == []
    assert len(capture.follows_calls) == 1
    assert capture.follows_calls[0].follow_type == "following"


def test_get_user_info_sync(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = client.get_user_info(["OpenAI"])
    assert result == []
    assert len(capture.profile_calls) == 1


# ── Structured search filter tests ────────────────────────────────────


def test_search_structured_filters_passed_to_request(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(
        client.asearch(
            since="2026-02-01",
            until="2026-02-02",
            from_users=["elonmusk"],
            has_images=True,
            min_likes=100,
        )
    )
    assert len(capture.search_calls) == 1
    req = capture.search_calls[0]
    assert req.from_users == ["elonmusk"]
    assert req.has_images is True
    assert req.min_likes == 100


def test_search_query_optional_with_filters(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(
        client.asearch(
            since="2026-02-01",
            until="2026-02-02",
            from_users=["OpenAI"],
        )
    )
    assert len(capture.search_calls) == 1
    req = capture.search_calls[0]
    assert req.search_query is None
    assert req.from_users == ["OpenAI"]


def test_search_all_filter_types(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(
        client.asearch(
            "base query",
            since="2026-02-01",
            until="2026-02-02",
            all_words=["python", "data"],
            any_words=["ml", "ai"],
            exact_phrases=["machine learning"],
            exclude_words=["spam"],
            hashtags_any=["#AI"],
            hashtags_exclude=["#ad"],
            from_users=["OpenAI"],
            to_users=["user1"],
            mentioning_users=["user2"],
            tweet_type="exclude_replies",
            verified_only=True,
            blue_verified_only=False,
            has_images=True,
            has_videos=False,
            has_links=True,
            has_mentions=False,
            has_hashtags=True,
            min_likes=50,
            min_replies=5,
            min_retweets=10,
            place="San Francisco",
            near="NYC",
            within="15mi",
        )
    )
    assert len(capture.search_calls) == 1
    req = capture.search_calls[0]
    assert req.search_query == "base query"
    assert req.all_words == ["python", "data"]
    assert req.any_words == ["ml", "ai"]
    assert req.exact_phrases == ["machine learning"]
    assert req.exclude_words == ["spam"]
    assert req.hashtags_any == ["#AI"]
    assert req.hashtags_exclude == ["#ad"]
    assert req.from_users == ["OpenAI"]
    assert req.to_users == ["user1"]
    assert req.mentioning_users == ["user2"]
    assert req.tweet_type == "exclude_replies"
    assert req.verified_only is True
    assert req.blue_verified_only is False
    assert req.has_images is True
    assert req.has_videos is False
    assert req.has_links is True
    assert req.has_mentions is False
    assert req.has_hashtags is True
    assert req.min_likes == 50
    assert req.min_replies == 5
    assert req.min_retweets == 10
    assert req.place == "San Francisco"
    assert req.near == "NYC"
    assert req.within == "15mi"


# ── New param routing tests ───────────────────────────────────────────


def test_profile_tweets_max_empty_pages_override(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(client.aget_profile_tweets(["OpenAI"], max_empty_pages=7))
    assert capture.profile_timeline_calls[0].max_empty_pages == 7


def test_profile_tweets_resume_flag(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(client.aget_profile_tweets(["OpenAI"], resume=True))
    assert capture.profile_timeline_calls[0].resume is True


def test_followers_max_empty_pages_override(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(client.aget_followers(["OpenAI"], max_empty_pages=3))
    assert capture.follows_calls[0].max_empty_pages == 3


def test_followers_resume_flag(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(client.aget_followers(["OpenAI"], resume=True))
    assert capture.follows_calls[0].resume is True


def test_followers_raw_json_flag(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(client.aget_followers(["OpenAI"], raw_json=True))
    assert capture.follows_calls[0].raw_json is True


def test_following_max_empty_pages_override(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(client.aget_following(["OpenAI"], max_empty_pages=5))
    assert capture.follows_calls[0].max_empty_pages == 5
