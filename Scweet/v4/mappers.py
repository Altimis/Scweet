from __future__ import annotations

import os
from typing import Any, Optional


LEGACY_CSV_HEADER = [
    "tweetId",
    "UserScreenName",
    "UserName",
    "Timestamp",
    "Text",
    "Embedded_text",
    "Emojis",
    "Comments",
    "Likes",
    "Retweets",
    "Image link",
    "Tweet URL",
]


def _is_dict_like(value: Any) -> bool:
    return isinstance(value, dict)


def _get(value: Any, key: str, default: Any = None) -> Any:
    if value is None:
        return default
    if _is_dict_like(value):
        return value.get(key, default)
    return getattr(value, key, default)


def _nested(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        current = _get(current, key, None)
        if current is None:
            return None
    return current


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


def _normalize_image_links(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return []


def map_tweet_to_legacy_dict(tweet) -> dict:
    tweet_id = _get(tweet, "tweet_id", None) or _get(tweet, "tweetId", "")

    user_screen_name = (
        _nested(tweet, "user", "screen_name")
        or _get(tweet, "handle", None)
        or _get(tweet, "UserScreenName", "")
    )
    user_name = (
        _nested(tweet, "user", "name")
        or _get(tweet, "username", None)
        or _get(tweet, "UserName", "")
    )
    timestamp = _get(tweet, "timestamp", None) or _get(tweet, "postdate", None) or _get(tweet, "Timestamp", "")
    text = _get(tweet, "text", None) or _get(tweet, "Text", "")
    embedded = _get(tweet, "embedded_text", None) or _get(tweet, "embedded", None) or _get(tweet, "Embedded_text", "")
    emojis = _get(tweet, "emojis", None) or _get(tweet, "Emojis", "")

    comments = _get(tweet, "comments", None)
    if comments is None:
        comments = _get(tweet, "reply_cnt", None)
    if comments is None:
        comments = _get(tweet, "Comments", 0)

    likes = _get(tweet, "likes", None)
    if likes is None:
        likes = _get(tweet, "like_cnt", None)
    if likes is None:
        likes = _get(tweet, "Likes", 0)

    retweets = _get(tweet, "retweets", None)
    if retweets is None:
        retweets = _get(tweet, "retweet_cnt", None)
    if retweets is None:
        retweets = _get(tweet, "Retweets", 0)

    image_links = _nested(tweet, "media", "image_links")
    if image_links is None:
        image_links = _get(tweet, "image_links", None)
    if image_links is None:
        image_links = _get(tweet, "Image link", "")
    image_link = " ".join(_normalize_image_links(image_links))

    tweet_url = _get(tweet, "tweet_url", None) or _get(tweet, "Tweet URL", "")

    return {
        "tweetId": str(tweet_id) if tweet_id is not None else "",
        "UserScreenName": str(user_screen_name) if user_screen_name is not None else "",
        "UserName": str(user_name) if user_name is not None else "",
        "Timestamp": str(timestamp) if timestamp is not None else "",
        "Text": str(text) if text is not None else "",
        "Embedded_text": str(embedded) if embedded is not None else "",
        "Emojis": str(emojis) if emojis is not None else "",
        "Comments": _safe_int(comments),
        "Likes": _safe_int(likes),
        "Retweets": _safe_int(retweets),
        "Image link": image_link,
        "Tweet URL": str(tweet_url) if tweet_url is not None else "",
    }


def map_tweet_to_legacy_csv_row(tweet) -> list:
    mapped = map_tweet_to_legacy_dict(tweet)
    return [mapped.get(key, "") for key in LEGACY_CSV_HEADER]


def build_legacy_csv_filename(
    save_dir: str,
    custom_csv_name: Optional[str],
    since: str,
    until: str,
    words=None,
    from_account=None,
    to_account=None,
    mention_account=None,
    hashtag=None,
) -> str:
    if custom_csv_name:
        return os.path.join(save_dir, str(custom_csv_name))

    normalized_words = words
    if isinstance(normalized_words, str):
        normalized_words = normalized_words.split("//")

    if isinstance(normalized_words, list) and normalized_words:
        fname_part = "_".join(str(item) for item in normalized_words if str(item))
        if not fname_part:
            fname_part = "tweets"
    elif from_account:
        fname_part = str(from_account)
    elif to_account:
        fname_part = str(to_account)
    elif mention_account:
        fname_part = str(mention_account)
    elif hashtag:
        fname_part = str(hashtag)
    else:
        fname_part = "tweets"

    return os.path.join(save_dir, f"{fname_part}_{since}_{until}.csv")
