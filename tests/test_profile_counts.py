"""A profile row reports the real counts, and not zero.

The failure mode: X empties the `legacy` node of a user and sends the counts
in `relationship_counts`, `tweet_counts` and `action_counts`. The parser read
only `legacy`, so every profile row and every follower row reported 0
followers, 0 following and 0 tweets. Captured 2026-09-13.
"""

import json
from pathlib import Path

from Scweet.api_engine import ApiEngine

FIXTURES = Path(__file__).parent / "fixtures"


def _engine() -> ApiEngine:
    return ApiEngine(config={}, accounts_repo=None, manifest_provider=None)


def _profile_node() -> dict:
    payload = json.loads((FIXTURES / "user_info_elonmusk.json").read_text(encoding="utf-8"))
    return payload.get("raw") or payload


def test_a_profile_row_reports_the_counts_that_x_sends_outside_legacy():
    node = _profile_node()
    assert node.get("legacy") in ({}, None), "the captured shape has an empty legacy node"

    record = _engine()._map_user_result_to_profile_record(
        node, target={"raw": "elonmusk", "source": "username"}, username="elonmusk"
    )
    assert record["followers_count"] == 241659598
    assert record["following_count"] == 1406
    assert record["statuses_count"] == 108482
    assert record["media_count"] == 4717
    assert record["favourites_count"] == 247852


def test_a_profile_row_carries_its_banner_and_its_pinned_tweet():
    record = _engine()._map_user_result_to_profile_record(
        _profile_node(), target={"raw": "elonmusk", "source": "username"}, username="elonmusk"
    )
    assert record["profile_banner_url"] == (
        "https://pbs.twimg.com/profile_banners/44196397/1774145451"
    )
    assert record["pinned_tweet_ids"] == ["2098932438055469451"]
    # X sends the entities of the bio under profile_bio, not under legacy.
    assert record["description_urls"] == ["http://Terafab.AI"]


def test_a_follower_row_reports_the_counts_too():
    rows = json.loads((FIXTURES / "verified_followers_page.json").read_text(encoding="utf-8"))
    node = rows[0]["raw"]
    record = _engine()._map_user_result_to_follow_record(
        user_result=node,
        target={"raw": "elonmusk", "source": "username"},
        follow_type="verified_followers",
    )
    assert record["followers_count"] == 45
    assert record["following_count"] == 422
    assert record["statuses_count"] == 452


def test_the_old_legacy_shape_still_works():
    """A user of an older answer of X must keep working."""
    node = {
        "rest_id": "1",
        "legacy": {
            "screen_name": "someone",
            "followers_count": 7,
            "friends_count": 8,
            "statuses_count": 9,
            "favourites_count": 10,
            "media_count": 11,
            "listed_count": 12,
            "pinned_tweet_ids_str": ["55"],
        },
    }
    record = _engine()._map_user_result_to_profile_record(
        node, target={"raw": "someone", "source": "username"}, username="someone"
    )
    assert record["followers_count"] == 7
    assert record["following_count"] == 8
    assert record["statuses_count"] == 9
    assert record["favourites_count"] == 10
    assert record["media_count"] == 11
    assert record["pinned_tweet_ids"] == ["55"]


def test_a_real_zero_count_stays_zero():
    """A profile with 0 followers must not fall through to another node."""
    node = {
        "rest_id": "1",
        "legacy": {"screen_name": "quiet", "followers_count": 0},
        "relationship_counts": {"followers": 999},
    }
    record = _engine()._map_user_result_to_profile_record(
        node, target={"raw": "quiet", "source": "username"}, username="quiet"
    )
    assert record["followers_count"] == 0
