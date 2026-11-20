"""A save never mixes two kinds of row in one file, and the default name of a profile save stays the handle.

Measured 2026-11-20: `profile-tweets NASA`, `followers NASA` and `following NASA`, each with `--save`, wrote
to one file `outputs/NASA.csv`. Every save appends, so that file held 300 rows of three shapes under the
header of the tweets. The default name stays `NASA`, because scripts read it; only a save of another kind of
row goes to a file named after its operation.
"""

from __future__ import annotations

import csv
import json

from Scweet import Scweet, ScweetConfig


def _client(tmp_path, fmt="csv"):
    cfg = ScweetConfig(save_dir=str(tmp_path), save_format=fmt)
    return Scweet(db_path=str(tmp_path / "state.db"), config=cfg, provision=False)


def _save(s, rows, operation, fmt="csv"):
    s._save_output(rows, operation, fmt, save_name=Scweet._build_save_name(operation, users=["NASA"]))


_TWEETS = [{"tweet_id": "1", "text": "a post", "user": {"screen_name": "NASA", "name": "NASA"}}]
_FOLLOWERS = [{"user_id": "11", "username": "a_follower", "type": "followers"}]
_FOLLOWING = [{"user_id": "22", "username": "a_followed", "type": "following"}]


def _csv_rows(path):
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_the_default_name_of_a_profile_save_stays_the_handle():
    assert Scweet._build_save_name("followers", users=["NASA"]) == "NASA"
    assert Scweet._build_save_name("profile_tweets", users=["NASA"]) == "NASA"


def test_three_kinds_of_row_for_one_profile_go_to_three_files(tmp_path):
    s = _client(tmp_path)
    _save(s, _TWEETS, "profile_tweets")
    _save(s, _FOLLOWERS, "followers")
    _save(s, _FOLLOWING, "following")

    assert sorted(p.name for p in tmp_path.glob("*.csv")) == ["NASA.csv", "NASA_followers.csv", "NASA_following.csv"]
    assert [r["tweet_id"] for r in _csv_rows(tmp_path / "NASA.csv")] == ["1"]
    assert [r["type"] for r in _csv_rows(tmp_path / "NASA_followers.csv")] == ["followers"]
    assert [r["type"] for r in _csv_rows(tmp_path / "NASA_following.csv")] == ["following"]


def test_a_second_save_of_the_same_kind_still_appends_to_the_handle(tmp_path):
    s = _client(tmp_path)
    _save(s, _FOLLOWERS, "followers")
    _save(s, [{"user_id": "12", "username": "another", "type": "followers"}], "followers")

    assert sorted(p.name for p in tmp_path.glob("*.csv")) == ["NASA.csv"]
    assert [r["username"] for r in _csv_rows(tmp_path / "NASA.csv")] == ["a_follower", "another"]


def test_a_json_save_of_another_kind_goes_to_its_own_file(tmp_path):
    s = _client(tmp_path, fmt="json")
    _save(s, _FOLLOWERS, "followers", fmt="json")
    _save(s, _FOLLOWING, "following", fmt="json")

    assert sorted(p.name for p in tmp_path.glob("*.json")) == ["NASA.json", "NASA_following.json"]
    assert [r["type"] for r in json.loads((tmp_path / "NASA.json").read_text(encoding="utf-8"))] == ["followers"]
