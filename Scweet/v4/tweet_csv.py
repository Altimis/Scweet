from __future__ import annotations

import re
from dataclasses import dataclass
from html import unescape
from typing import Any, Optional


SUMMARY_CSV_HEADER: list[str] = [
    "tweet_id",
    "tweet_url",
    "created_at",
    "text",
    "lang",
    "source",
    "source_url",
    "views",
    "views_state",
    "replies",
    "retweets",
    "likes",
    "quotes",
    "bookmarks",
    "conversation_id",
    "possibly_sensitive",
    "is_quote_status",
    "in_reply_to_tweet_id",
    "in_reply_to_user_id",
    "in_reply_to_handle",
    "quoted_tweet_id",
    "author_id",
    "author_handle",
    "author_name",
    "author_followers",
    "author_following",
    "author_verified",
    "author_blue_verified",
    "hashtags",
    "mentions",
    "urls",
    "media_count",
    "media_types",
    "media_preview_urls",
    "media_expanded_urls",
    "video_urls",
]


_TAG_RE = re.compile(r"<[^>]+>")
_HREF_RE = re.compile(r'href="([^"]+)"')


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        text = _as_str(value)
        if text is None:
            return None
        try:
            return int(text.replace(",", ""))
        except Exception:
            return None


def _as_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _get(obj: Any, *path: str) -> Any:
    cur = obj
    for key in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _unwrap_tweet(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    maybe = value.get("tweet")
    if isinstance(maybe, dict):
        return maybe
    return value


def _strip_html(value: str) -> str:
    return unescape(_TAG_RE.sub("", value)).strip()


def _parse_source(value: Any) -> tuple[Optional[str], Optional[str]]:
    raw = _as_str(value)
    if raw is None:
        return None, None
    href = None
    match = _HREF_RE.search(raw)
    if match:
        href = match.group(1).strip() or None
    label = _strip_html(raw) or None
    return label, href


def _uniq_join(items: list[str]) -> Optional[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = _as_str(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    if not out:
        return None
    return ",".join(out)


def _extract_hashtags(tweet: dict[str, Any]) -> list[str]:
    hashtags = _get(tweet, "note_tweet", "note_tweet_results", "result", "entity_set", "hashtags")
    if not isinstance(hashtags, list) or not hashtags:
        hashtags = _get(tweet, "legacy", "entities", "hashtags")
    out: list[str] = []
    if isinstance(hashtags, list):
        for item in hashtags:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                text = _as_str(item.get("text") or item.get("tag") or item.get("hashtag"))
                if text:
                    out.append(text.lstrip("#"))
    return out


def _extract_mentions(tweet: dict[str, Any]) -> list[str]:
    mentions = _get(tweet, "note_tweet", "note_tweet_results", "result", "entity_set", "user_mentions")
    if not isinstance(mentions, list) or not mentions:
        mentions = _get(tweet, "legacy", "entities", "user_mentions")
    out: list[str] = []
    if isinstance(mentions, list):
        for item in mentions:
            if isinstance(item, str):
                out.append(item.lstrip("@"))
            elif isinstance(item, dict):
                sn = _as_str(item.get("screen_name") or item.get("screenName") or item.get("handle"))
                if sn:
                    out.append(sn.lstrip("@"))
    return out


def _extract_urls(tweet: dict[str, Any]) -> list[str]:
    urls = _get(tweet, "note_tweet", "note_tweet_results", "result", "entity_set", "urls")
    if not isinstance(urls, list) or not urls:
        urls = _get(tweet, "legacy", "entities", "urls")
    out: list[str] = []
    if isinstance(urls, list):
        for item in urls:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                url = _as_str(item.get("expanded_url") or item.get("expandedUrl") or item.get("url"))
                if url:
                    out.append(url)
    return out


def _extract_media(tweet: dict[str, Any]) -> tuple[list[str], list[str], list[str], list[str]]:
    media = _get(tweet, "legacy", "extended_entities", "media")
    if not isinstance(media, list) or not media:
        media = _get(tweet, "legacy", "entities", "media")
    types: list[str] = []
    preview_urls: list[str] = []
    expanded_urls: list[str] = []
    video_urls: list[str] = []

    if not isinstance(media, list):
        return types, preview_urls, expanded_urls, video_urls

    for item in media:
        if not isinstance(item, dict):
            continue
        media_type = _as_str(item.get("type"))
        if media_type:
            types.append(media_type)
        preview = _as_str(item.get("media_url_https") or item.get("media_url"))
        if preview:
            preview_urls.append(preview)
        expanded = _as_str(item.get("expanded_url") or item.get("url"))
        if expanded:
            expanded_urls.append(expanded)

        variants = _get(item, "video_info", "variants")
        if isinstance(variants, list) and variants:
            best_mp4 = None
            best_bitrate = -1
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                if _as_str(variant.get("content_type")) != "video/mp4":
                    continue
                url = _as_str(variant.get("url"))
                if not url:
                    continue
                bitrate = _as_int(variant.get("bitrate")) or 0
                if bitrate > best_bitrate:
                    best_bitrate = bitrate
                    best_mp4 = url
            if best_mp4:
                video_urls.append(best_mp4)

    return types, preview_urls, expanded_urls, video_urls


@dataclass(frozen=True)
class TweetCsvRows:
    summary: dict[str, Any]
    compat: dict[str, Any]


def tweet_to_csv_rows(raw_tweet: Any) -> TweetCsvRows:
    """Map a raw GraphQL tweet object to:

    - summary: stable, user-friendly columns for CSV output
    - compat: same data plus aliases used by older CSV schemas (v3 header + flattened keys)
    """

    tweet = _unwrap_tweet(raw_tweet)

    tweet_id = _as_str(_get(tweet, "rest_id") or _get(tweet, "legacy", "id_str"))
    legacy = _get(tweet, "legacy") if isinstance(_get(tweet, "legacy"), dict) else {}

    created_at = _as_str(_get(legacy, "created_at"))
    note_text = _as_str(_get(tweet, "note_tweet", "note_tweet_results", "result", "text"))
    text = note_text or _as_str(_get(legacy, "full_text"))
    lang = _as_str(_get(legacy, "lang"))

    source_label, source_url = _parse_source(_get(tweet, "source"))

    views = _as_int(_get(tweet, "views", "count"))
    views_state = _as_str(_get(tweet, "views", "state"))

    replies = _as_int(_get(legacy, "reply_count"))
    retweets = _as_int(_get(legacy, "retweet_count"))
    likes = _as_int(_get(legacy, "favorite_count"))
    quotes = _as_int(_get(legacy, "quote_count"))
    bookmarks = _as_int(_get(legacy, "bookmark_count"))

    conversation_id = _as_str(_get(legacy, "conversation_id_str"))
    possibly_sensitive = _as_bool(_get(legacy, "possibly_sensitive"))
    is_quote_status = _as_bool(_get(legacy, "is_quote_status"))

    in_reply_to_tweet_id = _as_str(_get(legacy, "in_reply_to_status_id_str"))
    in_reply_to_user_id = _as_str(_get(legacy, "in_reply_to_user_id_str"))
    in_reply_to_handle = _as_str(_get(legacy, "in_reply_to_screen_name"))
    quoted_tweet_id = _as_str(_get(legacy, "quoted_status_id_str"))

    user_result = _get(tweet, "core", "user_results", "result")
    user_result = user_result if isinstance(user_result, dict) else {}
    author_id = _as_str(_get(user_result, "rest_id"))
    author_handle = _as_str(_get(user_result, "core", "screen_name") or _get(user_result, "legacy", "screen_name"))
    author_name = _as_str(_get(user_result, "core", "name") or _get(user_result, "legacy", "name"))
    author_followers = _as_int(_get(user_result, "legacy", "followers_count"))
    author_following = _as_int(_get(user_result, "legacy", "friends_count"))
    author_verified = _as_bool(_get(user_result, "verification", "verified"))
    author_blue_verified = _as_bool(_get(user_result, "is_blue_verified"))

    tweet_url = None
    if tweet_id and author_handle:
        tweet_url = f"https://x.com/{author_handle}/status/{tweet_id}"

    hashtags_list = _extract_hashtags(tweet)
    mentions_list = _extract_mentions(tweet)
    urls_list = _extract_urls(tweet)

    media_types_list, preview_urls, expanded_urls, video_urls = _extract_media(tweet)
    media_count = max(len(media_types_list), len(preview_urls), len(expanded_urls), len(video_urls)) or None

    summary: dict[str, Any] = {
        "tweet_id": tweet_id,
        "tweet_url": tweet_url,
        "created_at": created_at,
        "text": text,
        "lang": lang,
        "source": source_label,
        "source_url": source_url,
        "views": views,
        "views_state": views_state,
        "replies": replies,
        "retweets": retweets,
        "likes": likes,
        "quotes": quotes,
        "bookmarks": bookmarks,
        "conversation_id": conversation_id,
        "possibly_sensitive": possibly_sensitive,
        "is_quote_status": is_quote_status,
        "in_reply_to_tweet_id": in_reply_to_tweet_id,
        "in_reply_to_user_id": in_reply_to_user_id,
        "in_reply_to_handle": in_reply_to_handle,
        "quoted_tweet_id": quoted_tweet_id,
        "author_id": author_id,
        "author_handle": author_handle,
        "author_name": author_name,
        "author_followers": author_followers,
        "author_following": author_following,
        "author_verified": author_verified,
        "author_blue_verified": author_blue_verified,
        "hashtags": _uniq_join(hashtags_list),
        "mentions": _uniq_join(mentions_list),
        "urls": _uniq_join(urls_list),
        "media_count": media_count,
        "media_types": _uniq_join(media_types_list),
        "media_preview_urls": _uniq_join(preview_urls),
        "media_expanded_urls": _uniq_join(expanded_urls),
        "video_urls": _uniq_join(video_urls),
    }

    # Alias keys to allow appending to older CSV schemas (v3 fixed header + prior flattened output).
    compat = dict(summary)
    if tweet_id is not None:
        compat["rest_id"] = tweet_id
        compat["tweetId"] = tweet_id
    if created_at is not None:
        compat["legacy.created_at"] = created_at
        compat["Timestamp"] = created_at
    if text is not None:
        compat["legacy.full_text"] = text
        compat["Text"] = text
    if lang is not None:
        compat["legacy.lang"] = lang
    if author_handle is not None:
        compat["core.user_results.result.legacy.screen_name"] = author_handle
        compat["UserScreenName"] = author_handle
    if author_name is not None:
        compat["core.user_results.result.legacy.name"] = author_name
        compat["UserName"] = author_name
    if tweet_url is not None:
        compat["Tweet URL"] = tweet_url
    if replies is not None:
        compat["legacy.reply_count"] = replies
        compat["Comments"] = replies
    if retweets is not None:
        compat["legacy.retweet_count"] = retweets
        compat["Retweets"] = retweets
    if likes is not None:
        compat["legacy.favorite_count"] = likes
        compat["Likes"] = likes
    if quotes is not None:
        compat["legacy.quote_count"] = quotes
    if bookmarks is not None:
        compat["legacy.bookmark_count"] = bookmarks
    if views is not None:
        compat["views.count"] = views

    # Best-effort legacy "Image link" column.
    if summary.get("media_preview_urls"):
        compat["Image link"] = summary.get("media_preview_urls")

    return TweetCsvRows(summary=summary, compat=compat)
