from __future__ import annotations

import asyncio

from Scweet import Scweet as PreferredScweet
from Scweet.config import ScweetConfig
from Scweet.models import SearchResult
from Scweet.query import build_effective_search_query, normalize_search_input


class _FakeRunner:
    def __init__(self):
        self.search_calls = []

    async def run_search(self, request):
        self.search_calls.append(request)
        return SearchResult(tweets=[])


def test_query_normalizer_maps_legacy_keys_and_builds_expected_query():
    normalized, errors, warnings = normalize_search_input(
        {
            "since": "2026-02-01_00:00:00_UTC",
            "until": "2026-02-01_23:59:59_UTC",
            "words": "bitcoin//ethereum",
            "from_account": "@alice",
            "hashtag": "btc",
            "filter_replies": True,
            "minlikes": "10",
        }
    )

    assert errors == []
    assert normalized["any_words"] == ["bitcoin", "ethereum"]
    assert normalized["from_users"] == ["alice"]
    assert normalized["hashtags_any"] == ["#btc"]
    assert normalized["tweet_type"] == "exclude_replies"
    assert normalized["min_likes"] == 10
    assert any("deprecated" in msg for msg in warnings)

    query = build_effective_search_query(normalized)
    assert "(bitcoin OR ethereum)" in query
    assert "from:alice" in query
    assert "(#btc)" in query
    assert "-filter:replies" in query
    assert "min_faves:10" in query
    assert "since:2026-02-01_00:00:00" in query
    assert "until:2026-02-01_23:59:59" in query


def test_query_builder_respects_existing_operators_in_search_query():
    query = build_effective_search_query(
        {
            "search_query": "from:jack lang:en -filter:replies min_faves:5 since:2026-02-01 until:2026-02-02",
            "from_users": ["alice"],
            "lang": "en",
            "tweet_type": "exclude_replies",
            "min_likes": 100,
            "since": "2026-02-01_00:00:00_UTC",
            "until": "2026-02-02_23:59:59_UTC",
        }
    )
    assert query.count("from:") == 1
    assert query.count("lang:en") == 1
    assert query.count("-filter:replies") == 1
    assert query.count("min_faves:") == 1
    assert query.count("since:") == 1
    assert query.count("until:") == 1


def test_asearch_builds_search_request_with_query_string(tmp_path):
    client = PreferredScweet(
        db_path=str(tmp_path / "state.db"),
        provision=False,
    )
    fake_runner = _FakeRunner()
    client._runner = fake_runner

    out = asyncio.run(
        client.asearch(
            "openai",
            since="2026-02-01",
            until="2026-02-02",
        )
    )
    assert out == []
    assert len(fake_runner.search_calls) == 1
    request = fake_runner.search_calls[0]
    assert request.search_query == "openai"
