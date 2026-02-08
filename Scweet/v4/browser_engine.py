from __future__ import annotations

import inspect
from typing import Any, Callable, Optional

from .models import FollowsRequest, ProfileRequest, SearchRequest, SearchResult, TweetMedia, TweetRecord, TweetUser


def _resolve(container: Any, *names: str) -> Any:
    if container is None:
        return None
    if isinstance(container, dict):
        for name in names:
            if name in container:
                return container[name]
        return None
    for name in names:
        if hasattr(container, name):
            return getattr(container, name)
    return None


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except Exception:
        return 0


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


class BrowserEngine:
    """Adapter over legacy browser runtime with canonical-ish v4 payloads."""

    def __init__(self, config, legacy_client_factory: Optional[Callable[..., Any]] = None):
        self.config = config
        self._legacy_client_factory = legacy_client_factory or self._default_legacy_client_factory
        self._client = self._legacy_client_factory(**self._build_legacy_client_kwargs(config))

    async def search_tweets(self, request):
        payload = self._coerce_search_request(request)
        kwargs = {
            "since": payload.since,
            "until": payload.until,
            "words": payload.words,
            "to_account": payload.to_account,
            "from_account": payload.from_account,
            "mention_account": payload.mention_account,
            "lang": payload.lang,
            "limit": payload.limit,
            "display_type": payload.display_type,
            "resume": payload.resume,
            "hashtag": payload.hashtag,
            "save_dir": payload.save_dir,
            "custom_csv_name": payload.custom_csv_name,
        }
        try:
            raw = await _maybe_await(self._client.ascrape(**kwargs))
            tweets = self._map_legacy_tweets(raw)
            return {
                "result": SearchResult(tweets=tweets),
                "cursor": None,
                "status_code": 200,
                "headers": {},
            }
        except Exception as exc:
            return {
                "result": SearchResult(),
                "cursor": None,
                "status_code": 500,
                "headers": {},
                "detail": str(exc),
            }

    async def get_profiles(self, request):
        payload = self._coerce_profile_request(request)
        try:
            profiles = await _maybe_await(
                self._client.aget_user_information(
                    handles=payload.handles,
                    login=payload.login,
                )
            )
            return {
                "profiles": profiles if isinstance(profiles, dict) else {},
                "status_code": 200,
            }
        except Exception as exc:
            return {
                "profiles": {},
                "status_code": 500,
                "detail": str(exc),
            }

    async def get_follows(self, request):
        payload = self._coerce_follows_request(request)
        try:
            follows = await _maybe_await(
                self._client.aget_follows(
                    handle=payload.handle,
                    type=payload.type,
                    login=payload.login,
                    stay_logged_in=payload.stay_logged_in,
                    sleep=payload.sleep,
                )
            )
            normalized = follows if isinstance(follows, list) else []
            return {
                "follows": normalized,
                "status_code": 200,
                "type": payload.type,
            }
        except Exception as exc:
            return {
                "follows": [],
                "status_code": 500,
                "type": payload.type,
                "detail": str(exc),
            }

    async def close(self):
        close_fn = getattr(self._client, "close", None)
        if close_fn is None:
            return None
        return await _maybe_await(close_fn())

    @staticmethod
    def _default_legacy_client_factory(**kwargs):
        from ..legacy_runtime import Scweet as LegacyScweet

        return LegacyScweet(**kwargs)

    @staticmethod
    def _config_value(config: Any, key: str, default: Any) -> Any:
        sections = [config]
        if isinstance(config, dict):
            sections.extend(config.get(name) for name in ("pool", "runtime", "accounts", "operations"))
        else:
            sections.extend(getattr(config, name, None) for name in ("pool", "runtime", "accounts", "operations"))
        for section in sections:
            if section is None:
                continue
            if isinstance(section, dict):
                if key in section and section[key] is not None:
                    return section[key]
            elif hasattr(section, key):
                value = getattr(section, key)
                if value is not None:
                    return value
        return default

    def _build_legacy_client_kwargs(self, config: Any) -> dict[str, Any]:
        return {
            "proxy": self._config_value(config, "proxy", None),
            "cookies": self._config_value(config, "cookies", None),
            "cookies_path": self._config_value(config, "cookies_path", None),
            "user_agent": self._config_value(config, "user_agent", None),
            "disable_images": bool(self._config_value(config, "disable_images", False)),
            "env_path": self._config_value(config, "env_path", None),
            "n_splits": int(self._config_value(config, "n_splits", 5)),
            "concurrency": int(self._config_value(config, "concurrency", 5)),
            "headless": bool(self._config_value(config, "headless", True)),
            "scroll_ratio": int(self._config_value(config, "scroll_ratio", 30)),
            "mode": "BROWSER",
            "code_callback": self._config_value(config, "code_callback", None),
        }

    @staticmethod
    def _coerce_search_request(request: Any) -> SearchRequest:
        if isinstance(request, SearchRequest):
            return request
        if isinstance(request, dict):
            return SearchRequest.model_validate(request)
        return SearchRequest.model_validate(request)

    @staticmethod
    def _coerce_profile_request(request: Any) -> ProfileRequest:
        if isinstance(request, ProfileRequest):
            return request
        if isinstance(request, dict):
            return ProfileRequest.model_validate(request)
        return ProfileRequest.model_validate(request)

    @staticmethod
    def _coerce_follows_request(request: Any) -> FollowsRequest:
        if isinstance(request, FollowsRequest):
            return request
        if isinstance(request, dict):
            return FollowsRequest.model_validate(request)
        return FollowsRequest.model_validate(request)

    def _map_legacy_tweets(self, raw: Any) -> list[TweetRecord]:
        if not isinstance(raw, dict):
            return []
        out: list[TweetRecord] = []
        for tweet_id, tweet_data in raw.items():
            if not isinstance(tweet_data, dict):
                continue

            handle = str(tweet_data.get("handle") or "").strip()
            if handle.startswith("@"):
                handle = handle[1:]
            username = tweet_data.get("username")
            image_links = tweet_data.get("image_links")
            if isinstance(image_links, str):
                image_links = [item for item in image_links.split() if item]
            if not isinstance(image_links, list):
                image_links = []

            out.append(
                TweetRecord(
                    tweet_id=str(tweet_id),
                    user=TweetUser(screen_name=handle or None, name=str(username) if username is not None else None),
                    timestamp=tweet_data.get("postdate"),
                    text=tweet_data.get("text"),
                    embedded_text=tweet_data.get("embedded"),
                    emojis=tweet_data.get("emojis"),
                    comments=_safe_int(tweet_data.get("reply_cnt")),
                    likes=_safe_int(tweet_data.get("like_cnt")),
                    retweets=_safe_int(tweet_data.get("retweet_cnt")),
                    media=TweetMedia(image_links=image_links),
                    tweet_url=tweet_data.get("tweet_url"),
                    raw=tweet_data,
                )
            )
        return out
