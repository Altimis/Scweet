from __future__ import annotations
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError, model_validator

from .repos import ManifestRepo
from .exceptions import ManifestError
from .async_tools import call_in_thread

logger = logging.getLogger(__name__)

_DEFAULT_MANIFEST = {
    "version": "v4-default-1",
    "query_ids": {
        "search_timeline": "f_A-Gyo204PRxixpkrchJg",
        "user_lookup_screen_name": "-oaLodhGbbnzJBACb1kk2Q",
    },
    "endpoints": {
        "search_timeline": "https://x.com/i/api/graphql/{query_id}/SearchTimeline",
        "user_lookup_screen_name": "https://x.com/i/api/graphql/{query_id}/UserByScreenName",
    },
    "operation_features": {
        "user_lookup_screen_name": {
            "hidden_profile_subscriptions_enabled": True,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_notes_tab_enabled": True,
            "subscriptions_feature_can_gift_premium": True,
        }
    },
    "operation_field_toggles": {
        "user_lookup_screen_name": {
            "withPayments": False,
            "withAuxiliaryUserLabels": True,
        }
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
    version: str = "v4-default-1"
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

    async def get_manifest(self) -> ManifestModel:
        local_manifest = self._load_local_manifest()

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
