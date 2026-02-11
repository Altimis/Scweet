from __future__ import annotations

import logging
import re
from typing import Any, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_HANDLE_PATTERN = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_USER_ID_PATTERN = re.compile(r"^\d+$")

_PROFILE_HOSTS = {
    "x.com",
    "www.x.com",
    "m.x.com",
    "mobile.x.com",
    "twitter.com",
    "www.twitter.com",
    "m.twitter.com",
    "mobile.twitter.com",
}

_RESERVED_PATHS = {
    "home",
    "explore",
    "search",
    "notifications",
    "messages",
    "compose",
    "settings",
    "i",
    "login",
    "signup",
    "tos",
    "privacy",
    "about",
    "help",
    "intent",
    "share",
    "hashtag",
}


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _normalize_input_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, str):
        items = [values]
    elif isinstance(values, (list, tuple, set)):
        items = list(values)
    else:
        items = [values]

    out: list[str] = []
    for item in items:
        text = _as_str(item)
        if text:
            out.append(text)
    return out


def _parse_profile_url(value: str) -> tuple[Optional[dict[str, str]], Optional[str]]:
    raw = _as_str(value)
    if not raw:
        return None, "empty"

    candidate = raw
    if "://" not in candidate:
        candidate = f"https://{candidate}"

    parsed = urlparse(candidate)
    host = _as_str(parsed.netloc).lower()
    if host not in _PROFILE_HOSTS:
        return None, "unsupported_host"

    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return None, "missing_path"

    if len(path_parts) >= 3 and path_parts[0].lower() == "i" and path_parts[1].lower() == "user":
        user_id = _as_str(path_parts[2])
        if _USER_ID_PATTERN.fullmatch(user_id):
            return {
                "raw_url": raw,
                "user_id": user_id,
                "normalized_url": f"https://x.com/i/user/{user_id}",
            }, None
        return None, "invalid_user_id"

    if len(path_parts) != 1:
        return None, "non_profile_path"

    handle = _as_str(path_parts[0]).lstrip("@")
    if not handle:
        return None, "missing_handle"
    if handle.lower() in _RESERVED_PATHS:
        return None, "reserved_path"
    if not _HANDLE_PATTERN.fullmatch(handle):
        return None, "invalid_handle"

    return {
        "raw_url": raw,
        "username": handle,
        "normalized_url": f"https://x.com/{handle}",
    }, None


def _parse_user_value(value: str, source: str) -> tuple[Optional[dict[str, str]], Optional[str]]:
    raw = _as_str(value)
    if not raw:
        return None, "empty"

    if raw.startswith("@"):
        handle = raw[1:]
        if _HANDLE_PATTERN.fullmatch(handle):
            return {"raw": raw, "source": source, "username": handle}, None
        return None, "invalid_handle"

    if _USER_ID_PATTERN.fullmatch(raw):
        return {"raw": raw, "source": source, "user_id": raw}, None

    if _HANDLE_PATTERN.fullmatch(raw) and raw.lower() not in _RESERVED_PATHS:
        return {"raw": raw, "source": source, "username": raw}, None

    parsed_url, reason = _parse_profile_url(raw)
    if parsed_url:
        parsed_url["raw"] = raw
        parsed_url["source"] = source
        return parsed_url, None
    return None, reason or "invalid"


def normalize_user_targets(
    *,
    users: Any = None,
    handles: Any = None,
    usernames: Any = None,
    user_ids: Any = None,
    profile_urls: Any = None,
    context: str = "users",
) -> dict[str, Any]:
    raw_inputs: list[tuple[str, str]] = []
    raw_inputs.extend((item, "users") for item in _normalize_input_list(users))
    raw_inputs.extend((item, "handles") for item in _normalize_input_list(handles))
    raw_inputs.extend((item, "usernames") for item in _normalize_input_list(usernames))
    raw_inputs.extend((item, "user_ids") for item in _normalize_input_list(user_ids))
    raw_inputs.extend((item, "profile_urls") for item in _normalize_input_list(profile_urls))

    targets: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    for raw_value, source in raw_inputs:
        parsed, reason = _parse_user_value(raw_value, source)
        if not parsed:
            skipped.append({"raw": raw_value, "source": source, "reason": reason or "invalid"})
            continue

        user_id = _as_str(parsed.get("user_id"))
        username = _as_str(parsed.get("username"))
        if user_id:
            dedupe_key = f"id:{user_id}"
        elif username:
            dedupe_key = f"username:{username.lower()}"
        else:
            skipped.append({"raw": raw_value, "source": source, "reason": "unresolved"})
            continue

        if dedupe_key in seen:
            skipped.append({"raw": raw_value, "source": source, "reason": "duplicate"})
            continue

        seen.add(dedupe_key)
        target: dict[str, str] = {
            "raw": _as_str(parsed.get("raw") or raw_value),
            "source": source,
        }
        if user_id:
            target["user_id"] = user_id
        if username:
            target["username"] = username
        normalized_url = _as_str(parsed.get("normalized_url"))
        if normalized_url:
            target["profile_url"] = normalized_url
        targets.append(target)

    usernames_out = [target["username"] for target in targets if target.get("username")]
    user_ids_out = [target["user_id"] for target in targets if target.get("user_id")]
    profile_urls_out = [target["profile_url"] for target in targets if target.get("profile_url")]

    if raw_inputs:
        logger.info(
            "User targets normalized context=%s accepted=%s skipped=%s usernames=%s user_ids=%s",
            context,
            len(targets),
            len(skipped),
            len(usernames_out),
            len(user_ids_out),
        )
        for row in skipped:
            logger.debug(
                "User target skipped context=%s raw=%r source=%s reason=%s",
                context,
                row.get("raw"),
                row.get("source"),
                row.get("reason"),
            )

    return {
        "targets": targets,
        "skipped": skipped,
        "usernames": usernames_out,
        "user_ids": user_ids_out,
        "profile_urls": profile_urls_out,
    }


def normalize_profile_targets_explicit(
    *,
    usernames: Any = None,
    profile_urls: Any = None,
    context: str = "profiles",
) -> dict[str, Any]:
    """Normalize profile targets from explicit inputs only.

    Supported sources:
    - `usernames`: x handles (letters/digits/underscore, 1..15), optional `@` prefix
    - `profile_urls`: profile URL (`x.com/<handle>`)
    """

    targets: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    seen: set[str] = set()

    def _append_target(*, raw: str, source: str, username: Optional[str] = None, profile_url: Optional[str] = None) -> None:
        norm_username = _as_str(username).lstrip("@")
        norm_profile_url = _as_str(profile_url)

        dedupe_key: Optional[str] = f"username:{norm_username.lower()}" if norm_username else None
        if not dedupe_key:
            skipped.append({"raw": raw, "source": source, "reason": "unresolved"})
            return
        if dedupe_key in seen:
            skipped.append({"raw": raw, "source": source, "reason": "duplicate"})
            return
        seen.add(dedupe_key)

        row: dict[str, str] = {"raw": raw, "source": source}
        if norm_username:
            row["username"] = norm_username
        if norm_profile_url:
            row["profile_url"] = norm_profile_url
        targets.append(row)

    for raw_value in _normalize_input_list(usernames):
        value = _as_str(raw_value)
        normalized = value.lstrip("@")
        if not _HANDLE_PATTERN.fullmatch(normalized):
            skipped.append({"raw": raw_value, "source": "usernames", "reason": "invalid_username"})
            continue
        _append_target(raw=value, source="usernames", username=normalized)

    for raw_value in _normalize_input_list(profile_urls):
        parsed_url, reason = _parse_profile_url(raw_value)
        if not parsed_url:
            skipped.append({"raw": _as_str(raw_value), "source": "profile_urls", "reason": reason or "invalid_profile_url"})
            continue
        if _as_str(parsed_url.get("user_id")):
            skipped.append({"raw": _as_str(raw_value), "source": "profile_urls", "reason": "user_id_url_not_supported"})
            continue
        _append_target(
            raw=_as_str(raw_value),
            source="profile_urls",
            username=_as_str(parsed_url.get("username")) or None,
            profile_url=_as_str(parsed_url.get("normalized_url")) or None,
        )

    usernames_out = [target["username"] for target in targets if target.get("username")]
    profile_urls_out = [target["profile_url"] for target in targets if target.get("profile_url")]

    if usernames is not None or profile_urls is not None:
        logger.info(
            "Profile targets normalized context=%s accepted=%s skipped=%s usernames=%s",
            context,
            len(targets),
            len(skipped),
            len(usernames_out),
        )
        for row in skipped:
            logger.debug(
                "Profile target skipped context=%s raw=%r source=%s reason=%s",
                context,
                row.get("raw"),
                row.get("source"),
                row.get("reason"),
            )

    return {
        "targets": targets,
        "skipped": skipped,
        "usernames": usernames_out,
        "profile_urls": profile_urls_out,
    }
