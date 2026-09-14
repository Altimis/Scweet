"""Each new client method routes its request to the right runner method.

The failure mode: a method that builds the wrong request reaches the wrong
endpoint of X, and the caller receives rows of the wrong shape. These tests
mirror the `_client_with_runner` pattern of tests/test_client.py.
"""

from __future__ import annotations

import asyncio

import pytest

from Scweet import Scweet
from Scweet.config import ScweetConfig


class _CaptureRunner:
    def __init__(self):
        self.profile_timeline_calls = []
        self.profile_calls = []
        self.tweet_info_calls = []
        self.tweet_replies_calls = []
        self.reposters_calls = []
        self.user_ids_calls = []
        self.search_users_calls = []
        self.trending_calls = 0

    async def run_profile_tweets(self, request):
        self.profile_timeline_calls.append(request)
        from Scweet.models import SearchResult

        return {
            "result": SearchResult(tweets=[]),
            "resume_cursors": {},
            "completed": True,
            "limit_reached": False,
        }

    async def run_profiles(self, request):
        self.profile_calls.append(request)
        return {"items": [{"username": "OpenAI", "user_id": "1"}], "status_code": 200}

    async def run_tweet_info(self, request):
        self.tweet_info_calls.append(request)
        return {"items": [{"tweet_id": "1"}], "status_code": 200}

    async def run_tweet_replies(self, request):
        self.tweet_replies_calls.append(request)
        return {"items": [], "status_code": 200}

    async def run_reposters(self, request):
        self.reposters_calls.append(request)
        return {"items": [], "status_code": 200}

    async def run_users_by_ids(self, request):
        self.user_ids_calls.append(request)
        return {"items": [{"username": "elonmusk", "user_id": "44196397"}], "status_code": 200}

    async def run_search_users(self, request):
        self.search_users_calls.append(request)
        return {"items": [], "status_code": 200}

    async def run_trending(self):
        self.trending_calls += 1
        return {"items": [{"name": "a trend", "trend_id": "1"}], "status_code": 200}


def _client_with_runner(tmp_path):
    client = Scweet(
        db_path=str(tmp_path / "state.db"),
        config=ScweetConfig(max_empty_pages=4),
        provision=False,
    )
    capture = _CaptureRunner()
    client._runner = capture
    return client, capture


# ── The profile timeline operation routing ────────────────────────────


def test_profile_tweets_default_routes_to_the_old_operation(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(client.aget_profile_tweets(["OpenAI"]))
    assert capture.profile_timeline_calls[0].timeline_operation == "profile_timeline"


def test_profile_tweets_include_replies_routes_to_the_new_operation(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    asyncio.run(client.aget_profile_tweets(["OpenAI"], include_replies=True))
    assert (
        capture.profile_timeline_calls[0].timeline_operation
        == "profile_timeline_with_replies"
    )


def test_profile_media_routes_to_the_media_operation(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_profile_media(["OpenAI"]))
    assert result == []
    assert capture.profile_timeline_calls[0].timeline_operation == "profile_media"
    assert capture.profile_timeline_calls[0].max_empty_pages == 4


def test_profile_media_sync_delegates_to_async(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    assert client.get_profile_media(["OpenAI"]) == []
    assert len(capture.profile_timeline_calls) == 1


# ── tweet-info ─────────────────────────────────────────────────────────


def test_tweet_info_routes_to_the_runner(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_tweet_info(["11", "22"]))
    assert result == [{"tweet_id": "1"}]
    assert capture.tweet_info_calls[0].tweet_ids == ["11", "22"]
    assert capture.tweet_info_calls[0].raw_json is False


def test_tweet_info_sync_delegates_to_async(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    client.get_tweet_info(["11"], raw_json=True)
    assert capture.tweet_info_calls[0].raw_json is True


# ── tweet-replies ──────────────────────────────────────────────────────


def test_tweet_replies_routes_to_the_runner(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_tweet_replies("123", limit=7))
    assert result == []
    request = capture.tweet_replies_calls[0]
    assert request.tweet_id == "123"
    assert request.limit == 7
    assert request.max_empty_pages == 4


def test_tweet_replies_sync_delegates_to_async(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    client.get_tweet_replies("123", max_empty_pages=2)
    assert capture.tweet_replies_calls[0].max_empty_pages == 2


# ── reposters ──────────────────────────────────────────────────────────


def test_reposters_routes_to_the_runner(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_reposters("456", limit=5, raw_json=True))
    assert result == []
    request = capture.reposters_calls[0]
    assert request.tweet_id == "456"
    assert request.limit == 5
    assert request.raw_json is True


def test_reposters_sync_delegates_to_async(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    client.get_reposters("456")
    assert len(capture.reposters_calls) == 1


# ── user-info with ids ─────────────────────────────────────────────────


def test_user_info_ids_route_to_the_batch_operation(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_user_info(user_ids=["44196397"]))
    assert result == [{"username": "elonmusk", "user_id": "44196397"}]
    assert capture.user_ids_calls[0].user_ids == ["44196397"]
    assert capture.profile_calls == []


def test_user_info_combines_users_and_ids_in_the_input_order(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_user_info(["OpenAI"], user_ids=["44196397"]))
    assert [row.get("username") for row in result] == ["OpenAI", "elonmusk"]
    assert len(capture.profile_calls) == 1
    assert len(capture.user_ids_calls) == 1


def test_user_info_with_users_only_keeps_the_old_path(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.aget_user_info(["OpenAI"]))
    assert result == [{"username": "OpenAI", "user_id": "1"}]
    assert capture.user_ids_calls == []


# ── search-users / trending ────────────────────────────────────────────


def test_search_users_routes_to_the_runner(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = asyncio.run(client.asearch_users("python", limit=3))
    assert result == []
    request = capture.search_users_calls[0]
    assert request.query == "python"
    assert request.limit == 3
    assert request.max_empty_pages == 4


def test_search_users_sync_delegates_to_async(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    client.search_users("python")
    assert len(capture.search_users_calls) == 1


def test_trending_returns_the_items_of_the_runner(tmp_path):
    client, capture = _client_with_runner(tmp_path)
    result = client.get_trending()
    assert result == [{"name": "a trend", "trend_id": "1"}]
    assert capture.trending_calls == 1


# ── the CLI of the new operations ──────────────────────────────────────


def _parse(*argv: str):
    from Scweet.cli import build_parser

    return build_parser().parse_args(list(argv))


def test_parser_tweet_info_ids():
    args = _parse("tweet-info", "11", "22")
    assert args.tweet_ids == ["11", "22"]
    assert args.raw_json is False


def test_parser_tweet_replies():
    args = _parse("tweet-replies", "123", "--limit", "5", "--raw-json")
    assert args.tweet_id == "123"
    assert args.limit == 5
    assert args.raw_json is True


def test_parser_reposters():
    args = _parse("reposters", "456", "--limit", "9")
    assert args.tweet_id == "456"
    assert args.limit == 9


def test_parser_search_users():
    args = _parse("search-users", "python", "--limit", "3")
    assert args.query == "python"
    assert args.limit == 3


def test_parser_trending():
    args = _parse("trending", "--pretty")
    assert args.pretty is True


def test_parser_profile_media():
    args = _parse("profile-media", "elonmusk", "--limit", "10")
    assert args.users == ["elonmusk"]
    assert args.limit == 10


def test_parser_profile_tweets_include_replies_default_false():
    args = _parse("profile-tweets", "elonmusk")
    assert args.include_replies is False


def test_parser_profile_tweets_include_replies_flag():
    args = _parse("profile-tweets", "elonmusk", "--include-replies")
    assert args.include_replies is True


def test_parser_user_info_ids_and_users_combine():
    args = _parse("user-info", "elonmusk", "--ids", "44196397", "783214")
    assert args.users == ["elonmusk"]
    assert args.ids == ["44196397", "783214"]


def test_cmd_user_info_without_input_exits(monkeypatch, capsys):
    """A user-info call with no handle and no id has nothing to look up.
    The command must exit with an error and must not build a client."""
    import Scweet.cli as cli_mod

    def _fail_make_client(args):
        raise AssertionError("the command must not build a client")

    monkeypatch.setattr(cli_mod, "_make_client", _fail_make_client)
    args = _parse("user-info")
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.cmd_user_info(args)
    assert excinfo.value.code == 2
    assert "at least one USER or --ids" in capsys.readouterr().err


def test_cmd_user_info_forwards_ids(monkeypatch):
    import Scweet.cli as cli_mod

    calls = []

    class _FakeClient:
        def get_user_info(self, users, **kwargs):
            calls.append((users, kwargs))
            return []

    monkeypatch.setattr(cli_mod, "_make_client", lambda args: _FakeClient())
    args = _parse("user-info", "--ids", "44196397")
    cli_mod.cmd_user_info(args)
    assert calls[0][0] is None
    assert calls[0][1]["user_ids"] == ["44196397"]


def test_cmd_trending_prints_when_pretty(monkeypatch, capsys):
    import Scweet.cli as cli_mod

    class _FakeClient:
        def get_trending(self):
            return [{"name": "a trend", "trend_id": "1"}]

    monkeypatch.setattr(cli_mod, "_make_client", lambda args: _FakeClient())
    cli_mod.cmd_trending(_parse("trending", "--pretty"))
    out = capsys.readouterr().out
    assert "a trend" in out


def test_an_id_lookup_that_x_refuses_raises_and_never_returns_an_empty_list(tmp_path):
    """X answers 403 with an HTML page for the id lookup on some connections.

    The failure mode: the engine reports the refusal in status_code, the client
    returned the empty items list, and the caller read "these users do not
    exist" from a network block.
    """
    import asyncio

    import pytest

    from Scweet.exceptions import EngineError

    client, capture = _client_with_runner(tmp_path)

    async def _refused(request):
        return {"items": [], "status_code": 403, "meta": {}}

    capture.run_users_by_ids = _refused
    with pytest.raises(EngineError, match="403"):
        asyncio.run(client.aget_user_info(user_ids=["44196397"]))
