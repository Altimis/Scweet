"""The original fields of TweetRecord stay identical across parser changes.

The failure mode: a parser change silently alters a field that an existing
user's script reads. The golden file holds the original fields as the parser
of 5.5.1 produced them from real captured responses. A difference here is a
compatibility break, not a test to update casually.
"""

import json
from pathlib import Path

from Scweet.api_engine import ApiEngine

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN = FIXTURES / "golden_records.json"
TWEET_FIXTURES = ["tweet_plain", "tweet_quote", "tweet_reply", "tweet_retweet", "tweet_video"]


def _engine() -> ApiEngine:
    return ApiEngine(config={}, accounts_repo=None, manifest_provider=None)


def search_envelope(node: dict) -> dict:
    tweet_id = node.get("rest_id") or "0"
    return {
        "data": {
            "search_by_raw_query": {
                "search_timeline": {
                    "timeline": {
                        "instructions": [
                            {
                                "entries": [
                                    {
                                        "entryId": f"tweet-{tweet_id}",
                                        "content": {
                                            "itemContent": {
                                                "tweet_results": {"result": node}
                                            }
                                        },
                                    }
                                ]
                            }
                        ]
                    }
                }
            }
        }
    }


def profile_envelope(node: dict) -> dict:
    tweet_id = node.get("rest_id") or "0"
    return {
        "data": {
            "user": {
                "result": {
                    "timeline": {
                        "timeline": {
                            "instructions": [
                                {
                                    "entries": [
                                        {
                                            "entryId": f"tweet-{tweet_id}",
                                            "content": {
                                                "itemContent": {
                                                    "tweet_results": {"result": node}
                                                }
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    }
                }
            }
        }
    }


def load_node(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["raw"]


def original_fields(record) -> dict:
    dump = record.model_dump()
    return {
        "tweet_id": dump["tweet_id"],
        "user": {"screen_name": dump["user"]["screen_name"], "name": dump["user"]["name"]},
        "timestamp": dump["timestamp"],
        "text": dump["text"],
        "embedded_text": dump["embedded_text"],
        "emojis": dump["emojis"],
        "comments": dump["comments"],
        "likes": dump["likes"],
        "retweets": dump["retweets"],
        "media_image_links": dump["media"]["image_links"],
        "tweet_url": dump["tweet_url"],
    }


def test_search_path_matches_the_golden_records():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    engine = _engine()
    for name in TWEET_FIXTURES:
        node = load_node(name)
        tweets, _ = engine._extract_tweets_and_cursor(search_envelope(node))
        assert len(tweets) == 1, name
        assert tweets[0].raw == node, f"{name}: raw must pass through untouched"
        assert original_fields(tweets[0]) == golden[name], name


def test_profile_path_matches_the_golden_records():
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    engine = _engine()
    for name in TWEET_FIXTURES:
        node = load_node(name)
        tweets, _ = engine._extract_profile_tweets_and_cursor(profile_envelope(node))
        assert len(tweets) == 1, name
        assert original_fields(tweets[0]) == golden[name], name
