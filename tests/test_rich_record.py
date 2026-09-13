"""The parser reads the rich fields that X already sends.

Each expected value below was read by hand from the captured fixture in
tests/fixtures/. The data was always present in the raw payload; before
5.6.0 the record dropped it.
"""

import json
from pathlib import Path

from Scweet.api_engine import ApiEngine

FIXTURES = Path(__file__).parent / "fixtures"


def _engine() -> ApiEngine:
    return ApiEngine(config={}, accounts_repo=None, manifest_provider=None)


def _search_envelope(node: dict) -> dict:
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
                                            "itemContent": {"tweet_results": {"result": node}}
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


def _record(name: str):
    node = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))["raw"]
    tweets, _ = _engine()._extract_tweets_and_cursor(_search_envelope(node))
    assert len(tweets) == 1, name
    return tweets[0]


def test_a_plain_tweet_carries_its_counts_and_language():
    record = _record("tweet_plain")
    assert record.tweet_id == "2090227249551483321"
    assert record.views == 355
    assert record.quotes == 0
    assert record.bookmarks == 1
    assert record.lang == "ko"
    assert record.is_quote is False
    assert record.is_retweet is False
    assert record.quoted_tweet is None
    assert record.retweeted_tweet is None
    assert record.in_reply_to_tweet_id is None


def test_a_quote_carries_the_quoted_tweet_as_a_record():
    record = _record("tweet_quote")
    assert record.views == 31752
    assert record.quotes == 1
    assert record.bookmarks == 16
    assert record.lang == "en"
    assert record.is_quote is True
    assert record.quoted_tweet is not None
    assert record.quoted_tweet.tweet_id == "2072430884343697811"
    assert record.quoted_tweet.user.screen_name == "astronomer_zero"
    # embedded_text reads legacy.full_text, which X truncates for a long tweet
    # and ends with a t.co link. The nested record reads the note_tweet text,
    # so it holds the complete text. embedded_text keeps its old value.
    assert record.embedded_text.endswith("https://t.co/FZXwgPmjp2")
    assert record.quoted_tweet.text.startswith(record.embedded_text[:200])
    assert len(record.quoted_tweet.text) > len(record.embedded_text)
    # One level of depth only: a nested record never nests again.
    assert record.quoted_tweet.quoted_tweet is None
    assert record.quoted_tweet.retweeted_tweet is None
    # The raw of the parent already holds the nested node.
    assert record.quoted_tweet.raw is None


def test_a_retweet_carries_the_source_tweet_as_a_record():
    record = _record("tweet_retweet")
    assert record.views == 619581
    assert record.is_retweet is True
    assert record.retweeted_tweet is not None
    assert record.retweeted_tweet.tweet_id == "2099045366197109039"
    assert record.retweeted_tweet.user.screen_name == "adamcarolla"
    assert record.embedded_text == record.retweeted_tweet.text
    assert record.mentions == ["adamcarolla"]


def test_a_reply_names_the_tweet_and_the_user_it_answers():
    record = _record("tweet_reply")
    assert record.in_reply_to_tweet_id == "2090196102808998123"
    assert record.in_reply_to_user == "Ozarka69"
    assert record.mentions == ["Ozarka69"]
    assert record.is_retweet is False


def test_an_animated_gif_carries_a_downloadable_link():
    record = _record("tweet_video")
    assert record.media.video_links, "the fixture holds one video variant"
    assert ".mp4" in record.media.video_links[0]


def test_a_native_video_carries_the_highest_bitrate_mp4():
    record = _record("tweet_native_video")
    assert record.tweet_id == "2090226912228757961"
    assert len(record.media.video_links) == 1
    link = record.media.video_links[0]
    # The fixture holds 4 mp4 variants and one m3u8 playlist. A playlist is a
    # stream index and not a file a user can save, so the parser rejects it.
    assert ".m3u8" not in link
    # A real URL of X carries a query, so the path holds the extension.
    assert ".mp4" in link
    # 10368000 is the highest bitrate in the fixture; it names 1920x1080.
    assert "1920x1080" in link


def test_a_media_with_only_a_playlist_variant_gives_no_video_link():
    """X sends only an m3u8 variant for a live broadcast.

    The variant object below is the real playlist variant of the captured
    fixture. The mp4 variants are removed, which is the shape of a broadcast.
    A playlist is a stream index, so the record reports no video link and the
    raw payload keeps the playlist for a caller that wants it.
    """
    node = json.loads((FIXTURES / "tweet_native_video.json").read_text(encoding="utf-8"))["raw"]
    inner = node.get("tweet", node)
    media = inner["legacy"]["extended_entities"]["media"][0]
    playlist = [
        v for v in media["video_info"]["variants"] if v.get("content_type") != "video/mp4"
    ]
    assert playlist, "the fixture holds one real playlist variant"
    media["video_info"]["variants"] = playlist

    tweets, _ = _engine()._extract_tweets_and_cursor(_search_envelope(node))
    assert tweets[0].media.video_links == []
    assert tweets[0].media.image_links, "the thumbnail of the media stays"


def test_the_entity_lists_default_to_empty_and_never_to_none():
    record = _record("tweet_plain")
    assert record.hashtags == []
    assert record.urls == []
    assert record.mentions == []
    assert record.media.video_links == []


def test_a_record_with_no_optional_data_reports_none_and_not_zero():
    engine = _engine()
    # A node with no views block: the count is unknown, and 0 would be a lie.
    node = {"rest_id": "1", "legacy": {"id_str": "1", "full_text": "x"}}
    tweets, _ = engine._extract_tweets_and_cursor(_search_envelope(node))
    assert tweets[0].views is None
    assert tweets[0].lang is None
    assert tweets[0].likes == 0
