from __future__ import annotations

import re
from typing import Any, Optional


_TWEET_TYPE_VALUES = {
    "all",
    "originals_only",
    "replies_only",
    "retweets_only",
    "exclude_replies",
    "exclude_retweets",
}

_LIST_FIELDS = {
    "all_words",
    "any_words",
    "exact_phrases",
    "exclude_words",
    "hashtags_any",
    "hashtags_exclude",
    "from_users",
    "to_users",
    "mentioning_users",
}

_BOOL_FIELDS = {
    "verified_only",
    "blue_verified_only",
    "has_images",
    "has_videos",
    "has_links",
    "has_mentions",
    "has_hashtags",
}

_INT_FIELDS = {"min_likes", "min_replies", "min_retweets"}

_LEGACY_KEY_ALIASES = {
    # Current Scweet facade fields.
    "words": "any_words",
    "from_account": "from_users",
    "to_account": "to_users",
    "mention_account": "mentioning_users",
    "hashtag": "hashtags_any",
    "minlikes": "min_likes",
    "minreplies": "min_replies",
    "minretweets": "min_retweets",
    # Legacy actor-like aliases.
    "query": "search_query",
    "words_and": "all_words",
    "words_or": "any_words",
    "verified": "verified_only",
    "blue_verified": "blue_verified_only",
    "images": "has_images",
    "videos": "has_videos",
    "links": "has_links",
}

_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,15}$")


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_string_list(values: Any, *, split_double_slash: bool = False) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        if split_double_slash and "//" in values:
            items = values.split("//")
        else:
            items = [values]
    elif isinstance(values, (list, tuple, set)):
        items = list(values)
    else:
        items = [values]

    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = _as_str(item)
        if not text:
            continue
        if text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _normalize_handle_list(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in _normalize_string_list(values):
        handle = raw.lstrip("@").strip()
        if not handle:
            continue
        if not _HANDLE_PATTERN.fullmatch(handle):
            continue
        key = handle.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(handle)
    return out


def _normalize_hashtag(value: str) -> str:
    text = _as_str(value)
    if not text:
        return ""
    if text.startswith("#") or text.startswith("$"):
        return text
    return f"#{text}"


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    text = _as_str(value).lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off", ""}:
        return False
    return bool(value)


def _as_non_negative_int(value: Any, *, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except Exception:
        return default
    return max(0, parsed)


def _normalize_tweet_type(value: Any) -> str:
    text = _as_str(value).lower()
    if not text:
        return "all"
    if text in _TWEET_TYPE_VALUES:
        return text
    return "all"


def _apply_legacy_aliases(raw_input: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    coerced = dict(raw_input or {})
    warnings: list[str] = []
    for legacy_key, canonical_key in _LEGACY_KEY_ALIASES.items():
        if legacy_key not in raw_input:
            continue
        warnings.append(f"Input key '{legacy_key}' is deprecated; use '{canonical_key}'.")
        if canonical_key in raw_input:
            warnings.append(f"Ignoring deprecated '{legacy_key}' because '{canonical_key}' is already provided.")
            continue
        coerced[canonical_key] = raw_input.get(legacy_key)

    # Keep legacy booleans supported.
    has_legacy_replies = "replies" in raw_input
    has_legacy_retweets = "retweets" in raw_input
    if has_legacy_replies:
        warnings.append("Input key 'replies' is deprecated; use 'tweet_type'.")
    if has_legacy_retweets:
        warnings.append("Input key 'retweets' is deprecated; use 'tweet_type'.")
    if "tweet_type" not in raw_input and (has_legacy_replies or has_legacy_retweets):
        replies_enabled = _boolish(raw_input.get("replies")) if has_legacy_replies else False
        retweets_enabled = _boolish(raw_input.get("retweets")) if has_legacy_retweets else False
        mapped = "all"
        if replies_enabled and not retweets_enabled:
            mapped = "replies_only"
        elif retweets_enabled and not replies_enabled:
            mapped = "retweets_only"
        coerced["tweet_type"] = mapped

    if "filter_replies" in raw_input and "tweet_type" not in raw_input and _boolish(raw_input.get("filter_replies")):
        warnings.append("Input key 'filter_replies' is deprecated; use 'tweet_type=exclude_replies'.")
        coerced["tweet_type"] = "exclude_replies"

    return coerced, warnings


def normalize_search_input(raw_input: Optional[dict[str, Any]]) -> tuple[dict[str, Any], list[str], list[str]]:
    payload = dict(raw_input or {})
    coerced, warnings = _apply_legacy_aliases(payload)
    errors: list[str] = []

    out: dict[str, Any] = {
        "search_query": _as_str(coerced.get("search_query")),
        "all_words": [],
        "any_words": [],
        "exact_phrases": [],
        "exclude_words": [],
        "hashtags_any": [],
        "hashtags_exclude": [],
        "from_users": [],
        "to_users": [],
        "mentioning_users": [],
        "lang": _as_str(coerced.get("lang")),
        "tweet_type": _normalize_tweet_type(coerced.get("tweet_type")),
        "verified_only": False,
        "blue_verified_only": False,
        "has_images": False,
        "has_videos": False,
        "has_links": False,
        "has_mentions": False,
        "has_hashtags": False,
        "min_likes": 0,
        "min_replies": 0,
        "min_retweets": 0,
        "place": _as_str(coerced.get("place")),
        "geocode": _as_str(coerced.get("geocode")),
        "near": _as_str(coerced.get("near")),
        "within": _as_str(coerced.get("within")),
        "since": _as_str(coerced.get("since")),
        "until": _as_str(coerced.get("until")),
    }

    for field_name in _LIST_FIELDS:
        value = coerced.get(field_name)
        if field_name in {"from_users", "to_users", "mentioning_users"}:
            out[field_name] = _normalize_handle_list(value)
        elif field_name == "hashtags_any":
            out[field_name] = [tag for tag in (_normalize_hashtag(v) for v in _normalize_string_list(value)) if tag]
        elif field_name == "hashtags_exclude":
            out[field_name] = [tag for tag in (_normalize_hashtag(v) for v in _normalize_string_list(value)) if tag]
        else:
            split = field_name in {"all_words", "any_words"} and isinstance(value, str)
            out[field_name] = _normalize_string_list(value, split_double_slash=split)

    # Keep legacy Scweet "words" semantics: multiple terms are OR-ed.
    if not out["any_words"] and payload.get("words") is not None:
        out["any_words"] = _normalize_string_list(payload.get("words"), split_double_slash=True)

    for field_name in _BOOL_FIELDS:
        out[field_name] = _boolish(coerced.get(field_name, False))
    for field_name in _INT_FIELDS:
        out[field_name] = _as_non_negative_int(coerced.get(field_name), default=0)

    if _as_str(coerced.get("display_type")):
        out["display_type"] = _as_str(coerced.get("display_type"))
    if _as_str(coerced.get("search_sort")):
        out["search_sort"] = _as_str(coerced.get("search_sort"))

    tweet_type = out["tweet_type"]
    if tweet_type not in _TWEET_TYPE_VALUES:
        errors.append(
            "Invalid 'tweet_type'. Allowed values are: all, originals_only, replies_only, "
            "retweets_only, exclude_replies, exclude_retweets."
        )
        out["tweet_type"] = "all"

    return out, errors, warnings


def _format_query_term(text: str) -> str:
    value = _as_str(text)
    if not value:
        return ""
    if value.startswith('"') and value.endswith('"'):
        return value
    if any(ch.isspace() for ch in value):
        return f"\"{value}\""
    return value


def _query_time_token(ts: str | None) -> str:
    if not ts:
        return ""
    text = _as_str(ts)
    if text.endswith("_UTC"):
        return text[:-4]
    return text


def _query_has_operator(search_query: str, name: str) -> bool:
    pattern = rf"(?<![A-Za-z0-9_]){re.escape(name)}:"
    return re.search(pattern, search_query, flags=re.IGNORECASE) is not None


def _query_has_any_min_operator(search_query: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9_])min_[a-z_]+:", search_query, flags=re.IGNORECASE) is not None


def _query_has_any_filter_operator(search_query: str) -> bool:
    return re.search(r"(?<![A-Za-z0-9_])-?filter:[a-z_]+\b", search_query, flags=re.IGNORECASE) is not None


def _build_operator_group(operator_name: str, values: list[str]) -> Optional[str]:
    if not values:
        return None
    items = [f"{operator_name}:{value}" for value in values]
    if len(items) == 1:
        return items[0]
    return f"({' OR '.join(items)})"


def build_effective_search_query(query_dict: dict[str, Any]) -> str:
    search_query = _as_str(query_dict.get("search_query"))
    parts: list[str] = []
    if search_query:
        parts.append(search_query)

    all_words = [_format_query_term(item) for item in query_dict.get("all_words", []) if _format_query_term(item)]
    if all_words:
        parts.append(f"({' AND '.join(all_words)})")

    any_words = [_format_query_term(item) for item in query_dict.get("any_words", []) if _format_query_term(item)]
    if any_words:
        parts.append(f"({' OR '.join(any_words)})")

    exact_phrases = [_format_query_term(item) for item in query_dict.get("exact_phrases", []) if _format_query_term(item)]
    if exact_phrases:
        parts.append(f"({' AND '.join(exact_phrases)})")

    exclude_words = [_format_query_term(item) for item in query_dict.get("exclude_words", []) if _format_query_term(item)]
    for term in exclude_words:
        parts.append(f"-{term}")

    hashtags_any = [_normalize_hashtag(item) for item in query_dict.get("hashtags_any", []) if _normalize_hashtag(item)]
    if hashtags_any:
        parts.append(f"({' OR '.join(hashtags_any)})")

    hashtags_exclude = [_normalize_hashtag(item) for item in query_dict.get("hashtags_exclude", []) if _normalize_hashtag(item)]
    for tag in hashtags_exclude:
        parts.append(f"-{tag}")

    if not _query_has_operator(search_query, "from"):
        from_group = _build_operator_group("from", query_dict.get("from_users", []))
        if from_group:
            parts.append(from_group)

    if not _query_has_operator(search_query, "to"):
        to_group = _build_operator_group("to", query_dict.get("to_users", []))
        if to_group:
            parts.append(to_group)

    mentioning_users = query_dict.get("mentioning_users", [])
    if mentioning_users:
        mention_items = [f"@{user}" for user in mentioning_users]
        if len(mention_items) == 1:
            parts.append(mention_items[0])
        else:
            parts.append(f"({' OR '.join(mention_items)})")

    if query_dict.get("lang") and not _query_has_operator(search_query, "lang"):
        parts.append(f"lang:{query_dict['lang']}")

    if not _query_has_any_filter_operator(search_query):
        tweet_type_to_filters = {
            "originals_only": ["-filter:replies", "-filter:retweets"],
            "replies_only": ["filter:replies"],
            "retweets_only": ["filter:retweets"],
            "exclude_replies": ["-filter:replies"],
            "exclude_retweets": ["-filter:retweets"],
        }
        for token in tweet_type_to_filters.get(str(query_dict.get("tweet_type") or "all").strip().lower(), []):
            parts.append(token)
        for field_name, filter_name in [
            ("verified_only", "verified"),
            ("blue_verified_only", "blue_verified"),
            ("has_images", "images"),
            ("has_videos", "videos"),
            ("has_links", "links"),
            ("has_mentions", "mentions"),
            ("has_hashtags", "hashtags"),
        ]:
            if query_dict.get(field_name):
                parts.append(f"filter:{filter_name}")

    if not _query_has_any_min_operator(search_query):
        if int(query_dict.get("min_likes") or 0) > 0:
            parts.append(f"min_faves:{int(query_dict['min_likes'])}")
        if int(query_dict.get("min_replies") or 0) > 0:
            parts.append(f"min_replies:{int(query_dict['min_replies'])}")
        if int(query_dict.get("min_retweets") or 0) > 0:
            parts.append(f"min_retweets:{int(query_dict['min_retweets'])}")

    if query_dict.get("since") and not _query_has_operator(search_query, "since"):
        parts.append(f"since:{_query_time_token(query_dict['since'])}")
    if query_dict.get("until") and not _query_has_operator(search_query, "until"):
        parts.append(f"until:{_query_time_token(query_dict['until'])}")

    if not any(_query_has_operator(search_query, name) for name in ("place", "geocode", "near", "within")):
        if query_dict.get("place"):
            parts.append(f"place:{query_dict['place']}")
        elif query_dict.get("geocode"):
            parts.append(f"geocode:{query_dict['geocode']}")
        elif query_dict.get("near"):
            parts.append(f"near:{query_dict['near']}")
            if query_dict.get("within"):
                parts.append(f"within:{query_dict['within']}")
        elif query_dict.get("within"):
            parts.append(f"within:{query_dict['within']}")

    return " ".join(part for part in parts if part).strip()

