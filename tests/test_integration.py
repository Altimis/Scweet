"""Integration tests — require real Twitter/X credentials.

Skipped by default. Run with:
    AUTH_TOKEN=xxx CT0=yyy pytest tests/test_integration.py -v

Or multiple accounts:
    COOKIES_JSON='[{"auth_token":"a","ct0":"b"}]' pytest tests/test_integration.py -v
"""
from __future__ import annotations

import json
import os

import pytest

from Scweet import Scweet, ScweetConfig


def _get_credentials():
    """Return init kwargs for Scweet from environment, or None if unavailable."""
    cookies_json = os.environ.get("COOKIES_JSON")
    if cookies_json:
        try:
            return {"cookies": json.loads(cookies_json)}
        except (json.JSONDecodeError, TypeError):
            pass

    auth_token = os.environ.get("AUTH_TOKEN")
    ct0 = os.environ.get("CT0")
    if auth_token and ct0:
        return {"cookies": {"auth_token": auth_token, "ct0": ct0}}
    if auth_token:
        return {"auth_token": auth_token}
    return None


_creds = _get_credentials()
_skip = pytest.mark.skipif(_creds is None, reason="No credentials in environment")

_YESTERDAY = "2026-03-19"
_TODAY = "2026-03-20"
_TEST_USER = "OpenAI"


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    db_path = str(tmp_path_factory.mktemp("integration") / "state.db")
    return Scweet(**_creds, db_path=db_path, config=ScweetConfig(manifest_scrape_on_init=True))


# ── Search ──────────────────────────────────────────────────────────────


@_skip
def test_search_returns_real_tweets(client):
    tweets = client.search("python", since=_YESTERDAY, until=_TODAY, limit=5)
    assert isinstance(tweets, list)
    assert len(tweets) > 0


@_skip
def test_search_result_has_expected_fields(client):
    tweets = client.search("python", since=_YESTERDAY, until=_TODAY, limit=3)
    assert len(tweets) > 0
    tweet = tweets[0]
    assert "tweet_id" in tweet
    assert "text" in tweet


@_skip
def test_search_with_structured_filters(client):
    tweets = client.search(
        since=_YESTERDAY,
        until=_TODAY,
        from_users=[_TEST_USER],
        limit=5,
    )
    assert isinstance(tweets, list)


@_skip
def test_search_with_save_creates_csv_and_json(client, tmp_path):
    cfg = client.config.model_copy(deep=True)
    cfg.save_dir = str(tmp_path)
    db_path = str(tmp_path / "state.db")
    s = Scweet(**_creds, db_path=db_path, config=cfg)
    tweets = s.search("python", since=_YESTERDAY, until=_TODAY, limit=3, save=True, save_format="both")
    if tweets:
        assert (tmp_path / "search.csv").exists()
        assert (tmp_path / "search.json").exists()


@_skip
def test_search_empty_results_graceful(client):
    result = client.search("xyzzy_gibberish_nonexistent_12345", since=_YESTERDAY, until=_TODAY, limit=3)
    assert isinstance(result, list)


# ── Profile Tweets ──────────────────────────────────────────────────────


@_skip
def test_profile_tweets_returns_results(client):
    tweets = client.get_profile_tweets([_TEST_USER], limit=5)
    assert isinstance(tweets, list)
    assert len(tweets) > 0


# ── User Info ───────────────────────────────────────────────────────────


@_skip
def test_get_user_info_returns_profile(client):
    profiles = client.get_user_info([_TEST_USER])
    assert isinstance(profiles, list)
    assert len(profiles) >= 1


# ── Followers / Following ──────────────────────────────────────────────


@_skip
def test_get_followers_returns_results(client):
    followers = client.get_followers([_TEST_USER], limit=5)
    assert isinstance(followers, list)
    assert len(followers) > 0


@_skip
def test_get_following_returns_results(client):
    following = client.get_following([_TEST_USER], limit=5)
    assert isinstance(following, list)
    assert len(following) > 0


# ── Multi-account & DB state ───────────────────────────────────────────


@_skip
def test_multi_account_cookies_init(tmp_path):
    cookies_json = os.environ.get("COOKIES_JSON")
    if not cookies_json:
        pytest.skip("COOKIES_JSON not set; need multi-account payload")
    cookies_list = json.loads(cookies_json)
    if not isinstance(cookies_list, list) or len(cookies_list) < 2:
        pytest.skip("Need at least 2 accounts in COOKIES_JSON")

    db_path = str(tmp_path / "multi.db")
    s = Scweet(cookies=cookies_list, db_path=db_path)
    assert s._accounts_repo.count_eligible() >= 2


@_skip
def test_db_shows_correct_state_after_search(client):
    client.search("python", since=_YESTERDAY, until=_TODAY, limit=3)
    summary = client.db.accounts_summary()
    assert summary["total"] >= 1


@_skip
def test_sync_wrapper_matches_async(client):
    import asyncio
    sync_result = client.search("python", since=_YESTERDAY, until=_TODAY, limit=3)
    async_result = asyncio.run(client.asearch("python", since=_YESTERDAY, until=_TODAY, limit=3))
    assert type(sync_result) is type(async_result) is list


# ── Error handling ─────────────────────────────────────────────────────


def test_bad_credentials_strict_raises(tmp_path):
    """Fake auth_token + strict=True should raise."""
    from Scweet.exceptions import AccountPoolExhausted
    db_path = str(tmp_path / "bad.db")
    s = Scweet(
        cookies={"auth_token": "fake_token_xxx", "ct0": "fake_ct0_xxx"},
        db_path=db_path,
        config=ScweetConfig(strict=True),
    )
    with pytest.raises((AccountPoolExhausted, Exception)):
        s.search("test", since=_YESTERDAY, until=_TODAY, limit=1)
