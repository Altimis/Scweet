from __future__ import annotations
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError, model_validator

from .repos import ManifestRepo
from .exceptions import ManifestError
from .async_tools import call_in_thread

logger = logging.getLogger(__name__)

# Maps X operationName → our internal manifest key.
_OPERATION_NAME_TO_KEY = {
    "SearchTimeline": "search_timeline",
    "UserByScreenName": "user_lookup_screen_name",
    "UserTweets": "profile_timeline",
    "Followers": "followers",
    "Following": "following",
    "BlueVerifiedFollowers": "verified_followers",
    "TweetResultsByRestIds": "tweet_lookup",
    "TweetDetail": "tweet_detail",
    "Retweeters": "reposters",
    "UserByRestId": "user_lookup_rest_id",
    "UsersByRestIds": "user_lookup_batch",
    "ExplorePage": "explore_page",
    "UserMedia": "profile_media",
    "UserTweetsAndReplies": "profile_timeline_with_replies",
}

# Endpoint URL templates keyed by manifest key.
_ENDPOINT_TEMPLATES = {
    "search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline",
    "user_lookup_screen_name": "https://x.com/i/api/graphql/{query_id}/UserByScreenName",
    "profile_timeline": "https://x.com/i/api/graphql/{query_id}/UserTweets",
    "followers": "https://x.com/i/api/graphql/{query_id}/Followers",
    "following": "https://x.com/i/api/graphql/{query_id}/Following",
    "verified_followers": "https://x.com/i/api/graphql/{query_id}/BlueVerifiedFollowers",
    "tweet_lookup": "https://x.com/i/api/graphql/{query_id}/TweetResultsByRestIds",
    "tweet_detail": "https://x.com/i/api/graphql/{query_id}/TweetDetail",
    "reposters": "https://x.com/i/api/graphql/{query_id}/Retweeters",
    "user_lookup_rest_id": "https://x.com/i/api/graphql/{query_id}/UserByRestId",
    "user_lookup_batch": "https://x.com/i/api/graphql/{query_id}/UsersByRestIds",
    "explore_page": "https://x.com/i/api/graphql/{query_id}/ExplorePage",
    "profile_media": "https://x.com/i/api/graphql/{query_id}/UserMedia",
    "profile_timeline_with_replies": "https://x.com/i/api/graphql/{query_id}/UserTweetsAndReplies",
}

_DEFAULT_MANIFEST = {
    "version": "v5-default-1",
    "query_ids": {
        "search_timeline": "KPSo2_UWdOMpPJwjhfT1Qg",
        "user_lookup_screen_name": "KybxDj9RrADIITXlGG8kpw",
        "profile_timeline": "OeFjWKHutsuyWXZGmLr02A",
        "followers": "sF7aRC2fRq7OGOOp_qHntA",
        "following": "4EQGMEhtdVw8NeVBDQHESQ",
        "verified_followers": "UmyQcnz4ojpneJPQeMlPeg",
        # The eight ids below were read from the live bundle of X on 2026-09-13.
        "tweet_lookup": "VwY22EyG-lO-eT6Myg_F0A",
        "tweet_detail": "FyR-GrebyjdkRoW1z6uCgQ",
        "reposters": "iH7h2J19n7Xd1swL4cNTNg",
        "user_lookup_rest_id": "IdmRdjYxIGI39Hdwkwo5cQ",
        "user_lookup_batch": "BuQFwM7wpHl00cfHL-r0rA",
        "explore_page": "UgdDQQHSWlNm3LEht3PnLg",
        "profile_media": "atLYUUmER14HCLFnNUKJgA",
        "profile_timeline_with_replies": "-4Ujf5pYzDdr_qY8qxgF9A",
    },
    "endpoints": {
        "search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline",
        "user_lookup_screen_name": "https://x.com/i/api/graphql/{query_id}/UserByScreenName",
        "profile_timeline": "https://x.com/i/api/graphql/{query_id}/UserTweets",
        "followers": "https://x.com/i/api/graphql/{query_id}/Followers",
        "following": "https://x.com/i/api/graphql/{query_id}/Following",
        "verified_followers": "https://x.com/i/api/graphql/{query_id}/BlueVerifiedFollowers",
        "tweet_lookup": "https://x.com/i/api/graphql/{query_id}/TweetResultsByRestIds",
        "tweet_detail": "https://x.com/i/api/graphql/{query_id}/TweetDetail",
        "reposters": "https://x.com/i/api/graphql/{query_id}/Retweeters",
        "user_lookup_rest_id": "https://x.com/i/api/graphql/{query_id}/UserByRestId",
        "user_lookup_batch": "https://x.com/i/api/graphql/{query_id}/UsersByRestIds",
        "explore_page": "https://x.com/i/api/graphql/{query_id}/ExplorePage",
        "profile_media": "https://x.com/i/api/graphql/{query_id}/UserMedia",
        "profile_timeline_with_replies": "https://x.com/i/api/graphql/{query_id}/UserTweetsAndReplies",
    },
    "operation_features": {
        "user_lookup_screen_name": {
            "hidden_profile_subscriptions_enabled": True,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
        },
        # UserByRestId refuses a request without these switches (verified live 2026-09-13).
        "user_lookup_rest_id": {
            "hidden_profile_subscriptions_enabled": True,
            "hidden_profile_likes_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
            "highlights_tweets_tab_ui_enabled": True,
        },
        # UsersByRestIds needs the same switches except hidden_profile_likes_enabled.
        "user_lookup_batch": {
            "hidden_profile_subscriptions_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
            "highlights_tweets_tab_ui_enabled": True,
        },
    },
    "operation_field_toggles": {
        "user_lookup_screen_name": {
            "withPayments": False,
            "withAuxiliaryUserLabels": True,
        },
        "profile_timeline": {
            "withArticlePlainText": False,
        },
        "tweet_detail": {
            "withArticleRichContentState": True,
            "withArticlePlainText": False,
        },
    },
    "features": {
        "rweb_video_screen_enabled": False,
        "profile_label_improvements_pcf_label_in_post_enabled": True,
        "responsive_web_profile_redirect_enabled": False,
        "rweb_tipjar_consumption_enabled": False,
        "verified_phone_label_enabled": False,
        "creator_subscriptions_tweet_preview_api_enabled": True,
        "responsive_web_graphql_timeline_navigation_enabled": True,
        "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
        "premium_content_api_read_enabled": False,
        "communities_web_enable_tweet_community_results_fetch": True,
        "c9s_tweet_anatomy_moderator_badge_enabled": True,
        "responsive_web_grok_analyze_button_fetch_trends_enabled": False,
        "responsive_web_grok_analyze_post_followups_enabled": True,
        "responsive_web_jetfuel_frame": True,
        "responsive_web_grok_share_attachment_enabled": True,
        "responsive_web_grok_annotations_enabled": False,
        "articles_preview_enabled": True,
        "responsive_web_edit_tweet_api_enabled": True,
        "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
        "view_counts_everywhere_api_enabled": True,
        "longform_notetweets_consumption_enabled": True,
        "responsive_web_twitter_article_tweet_consumption_enabled": True,
        "tweet_awards_web_tipping_enabled": False,
        "responsive_web_grok_show_grok_translated_post": False,
        "responsive_web_grok_analysis_button_from_backend": True,
        "post_ctas_fetch_enabled": True,
        "creator_subscriptions_quote_tweet_preview_enabled": False,
        "freedom_of_speech_not_reach_fetch_enabled": True,
        "standardized_nudges_misinfo": True,
        "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
        "longform_notetweets_rich_text_read_enabled": True,
        "longform_notetweets_inline_media_enabled": True,
        "responsive_web_grok_image_annotation_enabled": True,
        "responsive_web_grok_imagine_annotation_enabled": True,
        "responsive_web_grok_community_note_auto_translation_is_enabled": False,
        "responsive_web_enhance_cards_enabled": False,
    },
}


class ManifestModel(BaseModel):
    version: str = "v5-default-1"
    fingerprint: Optional[str] = None
    query_ids: dict[str, str] = Field(default_factory=dict)
    endpoints: dict[str, str] = Field(default_factory=dict)
    # Optional per-operation overrides (op -> dict). Useful as X introduces operation-specific toggles.
    operation_features: dict[str, dict[str, Any]] = Field(default_factory=dict)
    operation_field_toggles: dict[str, dict[str, Any]] = Field(default_factory=dict)
    features: dict[str, Any] = Field(default_factory=dict)
    timeout_s: int = 20

    def features_for(self, operation: str) -> dict[str, Any]:
        """Return the effective `features` dict for a given operation key."""

        out = dict(self.features or {})
        override = self.operation_features.get(str(operation or "").strip()) or {}
        if isinstance(override, dict) and override:
            out.update(override)
        return out

    def field_toggles_for(self, operation: str) -> Optional[dict[str, Any]]:
        """Return the `fieldToggles` dict for a given operation key (or None)."""

        override = self.operation_field_toggles.get(str(operation or "").strip())
        if not isinstance(override, dict) or not override:
            return None
        return dict(override)

    @model_validator(mode="after")
    def _validate_required_fields(self):
        if "search_timeline" not in self.query_ids:
            raise ValueError("manifest requires query_ids.search_timeline")
        if "search_timeline" not in self.endpoints:
            raise ValueError("manifest requires endpoints.search_timeline")

        if not self.fingerprint:
            payload = {
                "version": self.version,
                "query_ids": self.query_ids,
                "endpoints": self.endpoints,
                "operation_features": self.operation_features,
                "operation_field_toggles": self.operation_field_toggles,
                "features": self.features,
            }
            self.fingerprint = hashlib.sha1(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest()
        return self


class ManifestProvider:
    def __init__(self, db_path: str, manifest_url: Optional[str], ttl_s: int):
        self.db_path = db_path
        self.manifest_url = manifest_url
        self.ttl_s = max(int(ttl_s), 1)
        self.repo = ManifestRepo(db_path)
        self.local_manifest_path = Path(__file__).with_name("default_manifest.json")

    def _coerce_manifest(self, payload: Optional[dict[str, Any]]) -> Optional[ManifestModel]:
        if not isinstance(payload, dict):
            return None
        try:
            return ManifestModel.model_validate(payload)
        except ValidationError:
            return None

    def _load_local_manifest(self) -> ManifestModel:
        file_payload: Optional[dict[str, Any]] = None
        if self.local_manifest_path.exists():
            try:
                file_payload = json.loads(self.local_manifest_path.read_text(encoding="utf-8"))
            except Exception:
                file_payload = None

        manifest = self._coerce_manifest(file_payload)
        if manifest is not None:
            return manifest

        # Always keep a built-in fallback so this provider is fail-open.
        fallback = self._coerce_manifest(_DEFAULT_MANIFEST)
        assert fallback is not None
        return fallback

    def _fetch_remote_manifest_sync(self) -> Tuple[Optional[dict[str, Any]], Optional[str]]:
        if not self.manifest_url:
            return None, None

        try:
            from curl_cffi.requests import Session as CurlSession
        except Exception as exc:
            raise RuntimeError("curl_cffi is required to fetch remote manifest") from exc

        session = None
        try:
            session = CurlSession()
            response = session.get(self.manifest_url, timeout=10, allow_redirects=True)
            if int(getattr(response, "status_code", 0) or 0) != 200:
                raise RuntimeError(f"manifest fetch failed with status={getattr(response, 'status_code', None)}")

            payload = response.json()
            etag = None
            headers = getattr(response, "headers", None)
            if isinstance(headers, dict):
                etag = headers.get("ETag") or headers.get("etag")
            return payload, etag
        finally:
            if session is not None and hasattr(session, "close"):
                try:
                    session.close()
                except Exception:
                    pass

    def refresh_sync(self, *, strict: bool = False) -> ManifestModel:
        """Force a remote manifest fetch and update the cache (when manifest_url is set).

        Intended for `update_manifest=True` at client init. If refresh fails:
        - strict=True -> raises ManifestError
        - strict=False -> logs a warning and returns cached/local manifest
        """

        local_manifest = self._load_local_manifest()
        if not self.manifest_url:
            return local_manifest

        try:
            payload, remote_etag = self._fetch_remote_manifest_sync()
            remote_manifest = self._coerce_manifest(payload)
            if remote_manifest is None:
                raise ManifestError("manifest refresh returned invalid payload")

            self.repo.set_cached(
                self.manifest_url,
                remote_manifest.model_dump(mode="json"),
                ttl_s=self.ttl_s,
                etag=remote_etag,
            )
            return remote_manifest
        except Exception as exc:
            detail = f"Manifest refresh failed url={self.manifest_url} detail={exc}"
            if strict:
                raise ManifestError(detail) from exc
            logger.warning("%s", detail)

            cached_manifest = self.repo.get_cached(self.manifest_url, allow_expired=True)
            if cached_manifest and isinstance(cached_manifest.get("manifest"), dict):
                parsed_cached = self._coerce_manifest(cached_manifest["manifest"])
                if parsed_cached is not None:
                    return parsed_cached
            return local_manifest

    def get_manifest_sync(self) -> ManifestModel:
        """The manifest as the engine reads it now, with no network call."""
        live_cached = self.repo.get_cached("x-live-scrape")
        if live_cached and isinstance(live_cached.get("manifest"), dict):
            parsed = self._coerce_manifest(live_cached["manifest"])
            if parsed is not None:
                return parsed
        return self._load_local_manifest()

    async def get_manifest(self) -> ManifestModel:
        local_manifest = self._load_local_manifest()

        # Check live-scrape cache first (populated by scrape_from_x_sync).
        live_cached = self.repo.get_cached("x-live-scrape")
        if live_cached and isinstance(live_cached.get("manifest"), dict):
            parsed = self._coerce_manifest(live_cached["manifest"])
            if parsed is not None:
                return parsed

        if not self.manifest_url:
            return local_manifest

        cached_manifest = self.repo.get_cached(self.manifest_url)
        if cached_manifest and isinstance(cached_manifest.get("manifest"), dict):
            parsed_cached = self._coerce_manifest(cached_manifest["manifest"])
            if parsed_cached is not None:
                return parsed_cached

        remote_manifest: Optional[ManifestModel] = None
        remote_etag: Optional[str] = None

        try:
            payload, remote_etag = await call_in_thread(self._fetch_remote_manifest_sync)
            remote_manifest = self._coerce_manifest(payload)
        except Exception:
            remote_manifest = None

        if remote_manifest is not None:
            self.repo.set_cached(
                self.manifest_url,
                remote_manifest.model_dump(mode="json"),
                ttl_s=self.ttl_s,
                etag=remote_etag,
            )
            return remote_manifest

        stale_cached = self.repo.get_cached(self.manifest_url, allow_expired=True)
        if stale_cached and isinstance(stale_cached.get("manifest"), dict):
            parsed_cached = self._coerce_manifest(stale_cached["manifest"])
            if parsed_cached is not None:
                return parsed_cached

        return local_manifest

    # ── Live manifest scraping from X ───────────────────────────────────

    def scrape_from_x_sync(self, *, strict: bool = False, force: bool = False) -> ManifestModel:
        """Fetch X's main.js bundle and extract fresh query IDs + features.

        Results are cached in the DB (same TTL as remote manifests).
        Falls back to local manifest on failure unless strict=True.
        A user-triggered refresh passes force=True, so it never answers from the cache.
        """

        local_manifest = self._load_local_manifest()

        # Check cache first
        cache_key = "x-live-scrape"
        cached = None if force else self.repo.get_cached(cache_key)
        if cached and isinstance(cached.get("manifest"), dict):
            parsed = self._coerce_manifest(cached["manifest"])
            if parsed is not None:
                logger.info("Using cached live manifest (age within TTL)")
                return parsed

        try:
            scraped = scrape_manifest_from_x()
            manifest = self._coerce_manifest(scraped)
            if manifest is None:
                raise ManifestError("scraped manifest is invalid")

            self.repo.set_cached(cache_key, manifest.model_dump(mode="json"), ttl_s=self.ttl_s)
            logger.info(
                "Live manifest scraped successfully query_ids=%s",
                list(manifest.query_ids.keys()),
            )
            return manifest
        except Exception as exc:
            detail = f"Live manifest scrape failed: {exc}"
            if strict:
                raise ManifestError(detail) from exc
            logger.warning("%s; falling back to local manifest", detail)

            # Try stale cache
            stale = self.repo.get_cached(cache_key, allow_expired=True)
            if stale and isinstance(stale.get("manifest"), dict):
                parsed = self._coerce_manifest(stale["manifest"])
                if parsed is not None:
                    return parsed
            return local_manifest


def scrape_manifest_from_x(
    *,
    # Not "https://x.com": that URL answers a 32 KB shell that carries no bundle reference. The /home
    # path serves the full document, and it needs no cookie.
    home_url: str = "https://x.com/home",
    impersonate: str = "chrome",
    timeout: int = 15,
    chunk_fetch_max: int = 30,
) -> dict[str, Any]:
    """Scrape X's main.js to extract fresh query IDs and per-operation features.

    Returns a dict compatible with ManifestModel.
    """

    try:
        from curl_cffi.requests import Session as CurlSession
    except ImportError as exc:
        raise RuntimeError("curl_cffi is required for live manifest scraping") from exc

    session = CurlSession(impersonate=impersonate)
    try:
        # Step 1: Fetch X home page to find the main JS bundle URL.
        resp = session.get(home_url, timeout=timeout, allow_redirects=True)
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            raise ManifestError(f"Failed to fetch {home_url}: status={resp.status_code}")

        main_js_urls = re.findall(
            r"https://abs\.twimg\.com/responsive-web/client-web/main\.[^\"']+\.js",
            resp.text,
        )
        if not main_js_urls:
            raise ManifestError("Could not find main.js bundle URL in X home page")

        # Step 2: Fetch the main JS bundle.
        js_resp = session.get(main_js_urls[0], timeout=20, allow_redirects=True)
        if int(getattr(js_resp, "status_code", 0) or 0) != 200:
            raise ManifestError(f"Failed to fetch main.js: status={js_resp.status_code}")
        js_text = js_resp.text

        # Step 3: Extract query IDs and features for each operation.
        query_ids: dict[str, str] = {}
        endpoints: dict[str, str] = {}
        operation_features: dict[str, dict[str, bool]] = {}

        for op_name, manifest_key in _OPERATION_NAME_TO_KEY.items():
            qid_pattern = r'queryId:"([^"]+)",operationName:"' + re.escape(op_name) + r'"'
            qid_match = re.search(qid_pattern, js_text)
            if qid_match:
                query_ids[manifest_key] = qid_match.group(1)
                if manifest_key in _ENDPOINT_TEMPLATES:
                    endpoints[manifest_key] = _ENDPOINT_TEMPLATES[manifest_key]

            # Extract per-operation featureSwitches.
            _extract_operation_features(js_text, op_name, manifest_key, operation_features)

        if "search_timeline" not in query_ids:
            raise ManifestError("Failed to extract SearchTimeline query ID from main.js")

        # A lazy chunk of X holds some operations, for example Retweeters, so
        # main.js lacks their ids. The page embeds the chunk maps; sweep them.
        missing_ops = {
            op_name: manifest_key
            for op_name, manifest_key in _OPERATION_NAME_TO_KEY.items()
            if manifest_key not in query_ids
        }
        if missing_ops:
            _scrape_missing_from_chunks(
                session,
                resp.text,
                missing_ops,
                query_ids,
                endpoints,
                timeout=timeout,
                max_fetches=chunk_fetch_max,
            )

        _fill_missing_operations(query_ids, endpoints)

        # Step 4: Build the union of all feature switches (for the global features dict).
        # Use the local default as the base, then add any new features we discovered.
        base_features = dict(_DEFAULT_MANIFEST.get("features", {}))
        for op_features in operation_features.values():
            for key in op_features:
                if key not in base_features:
                    base_features[key] = False

        result = {
            "version": "v5-live-scrape",
            "query_ids": query_ids,
            "endpoints": endpoints,
            "features": base_features,
            "operation_features": _DEFAULT_MANIFEST.get("operation_features", {}),
            "operation_field_toggles": _DEFAULT_MANIFEST.get("operation_field_toggles", {}),
        }

        logger.info(
            "Scraped %d query IDs from X main.js: %s",
            len(query_ids),
            {k: v[:8] + "..." for k, v in query_ids.items()},
        )
        return result

    finally:
        try:
            session.close()
        except Exception:
            pass


def _extract_chunk_script_entries(page_text: str) -> list[tuple[str, str]]:
    """The chunk names and hashes that the page of X embeds.

    The page holds two maps keyed by chunk id: the hash map, whose values are
    exactly 7 or 16 lowercase hex digits, and the name map, whose values are
    the readable chunk names. A chunk resolves to
    https://abs.twimg.com/responsive-web/client-web/{name}.{hash}a.js
    """

    hash_map = {
        m.group(1): m.group(2)
        for m in re.finditer(r'(\d+):"([0-9a-f]{7}|[0-9a-f]{16})"', page_text)
    }
    name_map: dict[str, str] = {}
    for m in re.finditer(r'(\d+):"([^"]+)"', page_text):
        value = m.group(2)
        if not re.fullmatch(r"[0-9a-f]{7}|[0-9a-f]{16}", value):
            name_map[m.group(1)] = value
    return [(name_map.get(cid, cid), h) for cid, h in hash_map.items()]


# The sweep reads chunks with these names first, so the early exit fires soon.
# Measured 2026-09-13: Retweeters sits in bundle.TweetEditHistory, found after
# 9 fetches with this order against 964 chunks without it.
_CHUNK_PRIORITY = re.compile(r"retweet|repost|edit|engage|activity|tweet|conversation", re.I)

_CHUNK_BASE_URL = "https://abs.twimg.com/responsive-web/client-web"


def _scrape_missing_from_chunks(
    session: Any,
    page_text: str,
    missing_ops: dict[str, str],
    query_ids: dict[str, str],
    endpoints: dict[str, str],
    *,
    timeout: int,
    max_fetches: int,
) -> None:
    """Find the ids of the operations that main.js lacks inside the lazy chunks."""

    entries = _extract_chunk_script_entries(page_text)
    entries.sort(key=lambda e: (0 if _CHUNK_PRIORITY.search(e[0]) else 1, e[0]))

    fetched = 0
    for name, chunk_hash in entries:
        if not missing_ops or fetched >= max_fetches:
            break
        try:
            resp = session.get(f"{_CHUNK_BASE_URL}/{name}.{chunk_hash}a.js", timeout=timeout)
        except Exception:
            continue
        if int(getattr(resp, "status_code", 0) or 0) != 200:
            continue
        fetched += 1
        text = resp.text
        for op_name in list(missing_ops):
            match = re.search(r'queryId:"([^"]+)",operationName:"' + re.escape(op_name) + r'"', text)
            if match:
                manifest_key = missing_ops.pop(op_name)
                query_ids[manifest_key] = match.group(1)
                endpoints.setdefault(
                    manifest_key,
                    _ENDPOINT_TEMPLATES.get(manifest_key)
                    or _DEFAULT_MANIFEST["endpoints"].get(manifest_key, ""),
                )
    if missing_ops:
        logger.info(
            "The chunk sweep did not find %s within %d fetches; the bundled ids stay",
            sorted(missing_ops),
            max_fetches,
        )


def _fill_missing_operations(query_ids: dict[str, str], endpoints: dict[str, str]) -> None:
    """Keep the bundled default id for an operation that the scrape did not find.

    A lazy chunk of X holds some operations, for example Retweeters, so main.js
    lacks their ids. Without this merge a live scrape would drop those endpoints.
    """

    for key, default_id in _DEFAULT_MANIFEST["query_ids"].items():
        if key in query_ids:
            continue
        query_ids[key] = default_id
        endpoints.setdefault(key, _ENDPOINT_TEMPLATES.get(key) or _DEFAULT_MANIFEST["endpoints"][key])


def _extract_operation_features(
    js_text: str,
    op_name: str,
    manifest_key: str,
    out: dict[str, dict[str, bool]],
) -> None:
    """Extract featureSwitches for a specific operation from the JS bundle."""

    # Pattern: operationName:"SearchTimeline",...,featureSwitches:[...]
    for match in re.finditer(re.escape(f'"{op_name}"'), js_text):
        idx = match.start()
        chunk = js_text[max(0, idx - 100) : min(len(js_text), idx + 3000)]
        fs_start = chunk.find("featureSwitches:[")
        if fs_start < 0:
            continue
        content_start = fs_start + len("featureSwitches:[")
        depth = 1
        pos = content_start
        while pos < len(chunk) and depth > 0:
            if chunk[pos] == "[":
                depth += 1
            elif chunk[pos] == "]":
                depth -= 1
            pos += 1
        raw = chunk[content_start : pos - 1]
        features = re.findall(r'"([^"]+)"', raw)
        if features:
            out[manifest_key] = {f: False for f in features}
            return
