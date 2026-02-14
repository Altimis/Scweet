from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
import uuid
from typing import Any, Optional, Tuple
from urllib.parse import urlparse

from .account_session import AccountSessionBuilder
from .cooldown import (
    compute_cooldown,
    effective_status_with_rate_limit_headers,
    parse_rate_limit_remaining,
    parse_rate_limit_reset,
)
from .limiter import TokenBucketLimiter
from .models import FollowsRequest, ProfileRequest, ProfileTimelineRequest, RunStats, SearchRequest, SearchResult, TweetMedia, TweetRecord, TweetUser
from .query import build_effective_search_query, normalize_search_input

JSON_DECODE_STATUS = 598
NETWORK_ERROR_STATUS = 599
HTTP_MODE_AUTO = "auto"
HTTP_MODE_ASYNC = "async"
HTTP_MODE_SYNC = "sync"
DEFAULT_USER_LOOKUP_QUERY_ID = "-oaLodhGbbnzJBACb1kk2Q"
DEFAULT_USER_LOOKUP_ENDPOINT = "https://x.com/i/api/graphql/{query_id}/UserByScreenName"
DEFAULT_PROFILE_TIMELINE_QUERY_ID = "a3SQAz_VP9k8VWDr9bMcXQ"
DEFAULT_PROFILE_TIMELINE_ENDPOINT = "https://x.com/i/api/graphql/{query_id}/UserTweets"
DEFAULT_FOLLOWERS_QUERY_ID = "efNzdTpE-mkUcLARCd3RPQ"
DEFAULT_FOLLOWERS_ENDPOINT = "https://x.com/i/api/graphql/{query_id}/Followers"
DEFAULT_FOLLOWING_QUERY_ID = "M3LO-sJg6BCWdEliN_C2fQ"
DEFAULT_FOLLOWING_ENDPOINT = "https://x.com/i/api/graphql/{query_id}/Following"
DEFAULT_VERIFIED_FOLLOWERS_QUERY_ID = "YGl_IyrL0bFU7KHxQoSRVg"
DEFAULT_VERIFIED_FOLLOWERS_ENDPOINT = "https://x.com/i/api/graphql/{query_id}/BlueVerifiedFollowers"
USER_LOOKUP_OPERATION = "user_lookup_screen_name"
PROFILE_TIMELINE_OPERATION = "profile_timeline"
FOLLOWERS_OPERATION = "followers"
FOLLOWING_OPERATION = "following"
VERIFIED_FOLLOWERS_OPERATION = "verified_followers"

# Followers/following endpoints are strict about feature keys and can reject
# requests when expected booleans are omitted.
DEFAULT_FOLLOWS_FEATURES: dict[str, bool] = {
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
    "responsive_web_grok_annotations_enabled": True,
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
    # Common required flags frequently rejected when missing:
    "tweetypie_unmention_optimization_enabled": True,
    "responsive_web_twitter_blue_verified_badge_is_enabled": True,
    "vibe_api_enabled": False,
    "responsive_web_graphql_exclude_directive_enabled": True,
    "longform_notetweets_richtext_consumption_enabled": True,
}
logger = logging.getLogger(__name__)


def _iter_config_sections(config: Any):
    yield config
    section_names = ("pool", "runtime", "engine", "storage", "accounts", "operations", "resume", "output", "manifest")
    if isinstance(config, dict):
        for name in section_names:
            yield config.get(name)
        return
    for name in section_names:
        yield getattr(config, name, None)


def _config_value(config: Any, key: str, default: Any) -> Any:
    for section in _iter_config_sections(config):
        if section is None:
            continue
        if isinstance(section, dict):
            if key in section and section[key] is not None:
                return section[key]
            continue
        if hasattr(section, key):
            value = getattr(section, key)
            if value is not None:
                return value
    return default


class ApiEngine:
    def __init__(
        self,
        config,
        accounts_repo,
        manifest_provider,
        session_factory=None,
        transaction_id_provider=None,
    ):
        self.config = config
        self.accounts_repo = accounts_repo
        self.manifest_provider = manifest_provider
        configured_mode_raw = _config_value(config, "api_http_mode", HTTP_MODE_AUTO)
        configured_mode_value = getattr(configured_mode_raw, "value", configured_mode_raw)
        configured_mode = str(configured_mode_value or HTTP_MODE_AUTO).strip().lower()
        if configured_mode not in {HTTP_MODE_AUTO, HTTP_MODE_ASYNC, HTTP_MODE_SYNC}:
            configured_mode = HTTP_MODE_AUTO
        self.http_mode = configured_mode
        self.session_factory = session_factory or self._build_default_session_factory(self.http_mode)
        self.transaction_id_provider = transaction_id_provider
        self._logged_http_mode_selection: set[tuple[str, str]] = set()

    def _build_default_session_factory(self, http_mode: str):
        if http_mode != HTTP_MODE_SYNC:
            try:
                from curl_cffi.requests import AsyncSession as CurlAsyncSession

                return CurlAsyncSession
            except Exception:
                if http_mode == HTTP_MODE_ASYNC:
                    logger.info(
                        "API HTTP mode=%s but async session is unavailable; falling back to sync session",
                        HTTP_MODE_ASYNC,
                    )
                else:
                    logger.info("API HTTP auto mode could not resolve async session; falling back to sync session")

        try:
            from curl_cffi.requests import Session as CurlSession

            return CurlSession
        except Exception:
            raise RuntimeError("curl_cffi is required for API HTTP requests") from None

    async def search_tweets(self, request):
        provided_session, account_context, runtime_hints = self._extract_runtime_context(request)
        search_request = self._coerce_search_request(request)
        manifest = await self.manifest_provider.get_manifest()
        url = self._resolve_search_url(manifest)
        params = self._build_graphql_params(search_request, search_request.cursor, manifest, runtime_hints=runtime_hints)

        data, status_code, headers, text_snippet = await self._graphql_get(
            url=url,
            params=params,
            timeout_s=manifest.timeout_s,
            session=provided_session,
            account_context=account_context,
        )

        if status_code != 200 or data is None:
            return {
                "result": SearchResult(),
                "cursor": None,
                "status_code": status_code,
                "headers": headers,
                "text_snippet": text_snippet,
            }

        tweets, cursor = self._extract_tweets_and_cursor(data)
        return {
            "result": SearchResult(tweets=tweets),
            "cursor": cursor,
            "continue_with_cursor": bool(cursor),
            "status_code": status_code,
            "headers": headers,
            "text_snippet": text_snippet,
        }

    async def get_profiles(self, request, on_profiles_batch: Optional[Any] = None):
        profile_request = self._coerce_profile_request(request)
        provided_session, account_context, _runtime_hints = self._extract_runtime_context(request)
        manifest = await self.manifest_provider.get_manifest()
        targets = self._collect_profile_targets(profile_request)
        if not targets:
            logger.info("Profiles request received no valid targets")
            return {
                "items": [],
                "status_code": 400,
                "detail": "No valid targets provided",
                "meta": {"requested": 0, "resolved": 0, "failed": 0, "skipped": []},
            }

        active_session = provided_session
        leased_account: Optional[dict[str, Any]] = account_context
        lease_id: Optional[str] = None
        builder: Optional[AccountSessionBuilder] = None
        owns_session = provided_session is None

        if active_session is None:
            active_session, leased_account, lease_id, builder = await self._acquire_profile_session()
            if active_session is None:
                logger.warning("Profiles request failed: no eligible account could be leased")
                return {
                    "items": [],
                    "status_code": 503,
                    "detail": "No eligible account available",
                    "meta": {"requested": len(targets), "resolved": 0, "failed": len(targets), "skipped": []},
                }

        logger.info(
            "Profiles request started targets=%s account=%s",
            len(targets),
            self._account_label(leased_account),
        )
        items: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        last_error_status: Optional[int] = None

        try:
            for idx, target in enumerate(targets):
                resolved_username = await self._resolve_target_username(
                    target=target,
                )
                if not resolved_username:
                    skipped_row = {
                        "index": idx,
                        "input": target.get("raw") or target.get("username"),
                        "reason": "unresolved_username",
                    }
                    skipped.append(skipped_row)
                    logger.debug("Profiles target skipped index=%s reason=%s target=%r", idx, "unresolved_username", target)
                    continue

                url = self._resolve_user_lookup_url(manifest)
                params = self._build_user_lookup_params(resolved_username, manifest)
                data, status_code, headers, text_snippet = await self._graphql_get(
                    url=url,
                    params=params,
                    timeout_s=manifest.timeout_s,
                    session=active_session,
                    account_context=leased_account,
                )
                if status_code != 200 or data is None:
                    last_error_status = status_code
                    errors.append(
                        {
                            "index": idx,
                            "input": target.get("raw") or resolved_username,
                            "username": resolved_username,
                            "status_code": status_code,
                            "snippet": text_snippet,
                            "headers": headers,
                        }
                    )
                    logger.debug(
                        "Profiles lookup failed index=%s username=%s status=%s",
                        idx,
                        resolved_username,
                        status_code,
                    )
                    continue

                user_result = self._extract_user_result(data)
                if not isinstance(user_result, dict) or not user_result:
                    last_error_status = 404
                    errors.append(
                        {
                            "index": idx,
                            "input": target.get("raw") or resolved_username,
                            "username": resolved_username,
                            "status_code": 404,
                            "reason": "user_not_found",
                        }
                    )
                    logger.debug("Profiles lookup returned no user for username=%s", resolved_username)
                    continue

                profile_record = self._map_user_result_to_profile_record(user_result, target=target, username=resolved_username)
                items.append(profile_record)
                if on_profiles_batch is not None:
                    try:
                        await self._maybe_await(on_profiles_batch([profile_record]))
                    except Exception as exc:
                        logger.warning(
                            "Profiles streaming callback failed username=%s detail=%s",
                            resolved_username,
                            str(exc),
                        )

            resolved_count = len(items)
            failed_count = len(errors)
            skipped_count = len(skipped)
            if resolved_count > 0:
                status_code = 200
            elif last_error_status is not None:
                status_code = int(last_error_status)
            else:
                status_code = 404

            logger.info(
                "Profiles request finished requested=%s resolved=%s failed=%s skipped=%s account=%s",
                len(targets),
                resolved_count,
                failed_count,
                skipped_count,
                self._account_label(leased_account),
            )
            return {
                "items": items,
                "status_code": status_code,
                "meta": {
                    "requested": len(targets),
                    "resolved": resolved_count,
                    "failed": failed_count,
                    "skipped": skipped,
                    "errors": errors,
                },
            }
        finally:
            if owns_session and active_session is not None:
                if builder is not None and hasattr(builder, "close"):
                    await self._maybe_await(builder.close(active_session))
                else:
                    await self._close_session(active_session)
            if lease_id and self.accounts_repo is not None and hasattr(self.accounts_repo, "release"):
                release_set = {}
                release_inc = {"daily_requests": max(1, len(targets))}
                await self._maybe_await(self.accounts_repo.release(lease_id, fields_to_set=release_set, fields_to_inc=release_inc))

    async def get_profile_tweets(self, request, on_tweets_page: Optional[Any] = None):
        timeline_request = self._coerce_profile_timeline_request(request)
        manifest = await self.manifest_provider.get_manifest()
        targets = self._collect_profile_timeline_targets(timeline_request)
        if not targets:
            logger.info("Profile timeline request received no valid targets")
            return {
                "result": SearchResult(),
                "resume_cursors": {},
                "completed": True,
                "limit_reached": False,
            }

        global_limit = self._coerce_positive_int(timeline_request.limit)
        per_profile_limit = self._coerce_positive_int(timeline_request.per_profile_limit)
        max_pages_per_profile = self._coerce_positive_int(timeline_request.max_pages_per_profile)
        if max_pages_per_profile is None:
            max_pages_per_profile = float("inf")
        max_empty_pages = self._coerce_positive_int(timeline_request.max_empty_pages)
        if max_empty_pages is None:
            max_empty_pages = self._coerce_positive_int(_config_value(self.config, "max_empty_pages", 1)) or 1
        cursor_handoff = bool(timeline_request.cursor_handoff)
        allow_anonymous = bool(timeline_request.allow_anonymous)
        if allow_anonymous:
            cursor_handoff = False
        configured_switches_raw = _config_value(self.config, "max_account_switches", 2)
        try:
            configured_switches = max(0, int(configured_switches_raw))
        except Exception:
            configured_switches = 2
        if timeline_request.max_account_switches is None:
            max_account_switches = configured_switches
        else:
            try:
                max_account_switches = max(0, int(timeline_request.max_account_switches))
            except Exception:
                max_account_switches = configured_switches

        resume_cursors = self._normalize_resume_cursors(timeline_request.initial_cursors)
        collected_tweets: list[TweetRecord] = []
        seen_tweet_ids: set[str] = set()
        tasks_done = 0
        tasks_failed = 0
        retries = 0
        limit_reached = False
        exhausted_accounts = False

        user_lookup_url = self._resolve_user_lookup_url(manifest)
        timeline_url = self._resolve_profile_timeline_url(manifest)
        timeout_s = int(getattr(manifest, "timeout_s", 20) or 20)

        logger.info(
            "Profile timeline request started targets=%s limit=%s per_profile_limit=%s max_pages_per_profile=%s max_empty_pages=%s cursor_handoff=%s allow_anonymous=%s",
            len(targets),
            global_limit if global_limit is not None else "inf",
            per_profile_limit if per_profile_limit is not None else "inf",
            max_pages_per_profile,
            max_empty_pages,
            cursor_handoff,
            allow_anonymous,
        )

        for idx, target in enumerate(targets):
            if global_limit is not None and len(collected_tweets) >= global_limit:
                limit_reached = True
                break

            target_key = self._profile_target_key(target)
            starting_cursor = resume_cursors.get(target_key)
            cursor = starting_cursor
            username = await self._resolve_target_username(target=target)
            if not username:
                tasks_failed += 1
                logger.warning(
                    "Profile timeline target skipped index=%s reason=unresolved_username target=%r",
                    idx,
                    target,
                )
                continue

            user_id: Optional[str] = None
            target_done = False
            target_pages = 0
            target_tweets = 0
            empty_pages_count = 0
            account_switches = 0
            last_status = 200

            active_session = None
            leased_account: Optional[dict[str, Any]] = None
            lease_id: Optional[str] = None
            builder: Optional[AccountSessionBuilder] = None

            logger.info(
                "Profile timeline target start index=%s username=%s cursor=%s",
                idx,
                username,
                bool(cursor),
            )

            try:
                while target_pages < max_pages_per_profile:
                    if global_limit is not None and len(collected_tweets) >= global_limit:
                        limit_reached = True
                        break
                    if per_profile_limit is not None and target_tweets >= per_profile_limit:
                        break

                    if active_session is None:
                        if allow_anonymous:
                            try:
                                built = self.session_factory()
                                active_session = await self._maybe_await(built)
                            except Exception:
                                active_session = None
                            leased_account = None
                            lease_id = None
                            builder = None
                            if active_session is None:
                                last_status = 503
                                logger.warning("Profile timeline anonymous session could not be created")
                                break
                        else:
                            active_session, leased_account, lease_id, builder = await self._acquire_profile_session()
                            if active_session is None:
                                exhausted_accounts = True
                                last_status = 503
                                logger.warning("Profile timeline request failed: no eligible account could be leased")
                                break

                    if not user_id:
                        lookup_params = self._build_user_lookup_params(username, manifest)
                        lookup_data, lookup_status, lookup_headers, lookup_snippet = await self._graphql_get(
                            url=user_lookup_url,
                            params=lookup_params,
                            timeout_s=timeout_s,
                            session=active_session,
                            account_context=leased_account,
                        )
                        if self.accounts_repo is not None and lease_id and hasattr(self.accounts_repo, "record_usage"):
                            await self._maybe_await(self.accounts_repo.record_usage(lease_id, pages=1, tweets=0))
                        if lookup_status != 200 or lookup_data is None:
                            last_status = int(lookup_status)
                            if cursor_handoff and self._is_handoff_eligible_status(last_status) and account_switches < max_account_switches:
                                retries += 1
                                account_switches += 1
                                logger.info(
                                    "Profile timeline cursor handoff username=%s stage=user_lookup status=%s switch=%s/%s",
                                    username,
                                    last_status,
                                    account_switches,
                                    max_account_switches,
                                )
                                await self._close_profile_timeline_session(
                                    session=active_session,
                                    builder=builder,
                                    lease_id=lease_id,
                                    status_code=last_status,
                                )
                                active_session = None
                                leased_account = None
                                lease_id = None
                                builder = None
                                continue
                            logger.warning(
                                "Profile user lookup failed username=%s status=%s snippet=%s headers=%s",
                                username,
                                last_status,
                                lookup_snippet,
                                lookup_headers,
                            )
                            break

                        user_result = self._extract_user_result(lookup_data)
                        if not isinstance(user_result, dict):
                            last_status = 404
                            logger.warning("Profile user lookup failed username=%s status=404 reason=user_not_found", username)
                            break

                        resolved_user_id = str(user_result.get("rest_id") or user_result.get("id") or "").strip()
                        if not resolved_user_id:
                            legacy = user_result.get("legacy") if isinstance(user_result.get("legacy"), dict) else {}
                            resolved_user_id = str(legacy.get("id_str") or "").strip()
                        if not resolved_user_id:
                            last_status = 404
                            logger.warning("Profile user lookup failed username=%s status=404 reason=missing_user_id", username)
                            break
                        user_id = resolved_user_id

                    timeline_params = self._build_profile_timeline_params(
                        user_id=user_id,
                        cursor=cursor,
                        manifest=manifest,
                        runtime_hints=None,
                    )
                    data, status_code, _headers, _snippet = await self._graphql_get(
                        url=timeline_url,
                        params=timeline_params,
                        timeout_s=timeout_s,
                        session=active_session,
                        account_context=leased_account,
                    )

                    last_status = int(status_code)
                    if status_code != 200 or data is None:
                        if self.accounts_repo is not None and lease_id and hasattr(self.accounts_repo, "record_usage"):
                            await self._maybe_await(self.accounts_repo.record_usage(lease_id, pages=1, tweets=0))
                        if cursor_handoff and self._is_handoff_eligible_status(last_status) and account_switches < max_account_switches:
                            retries += 1
                            account_switches += 1
                            logger.info(
                                "Profile timeline cursor handoff username=%s stage=timeline status=%s switch=%s/%s",
                                username,
                                last_status,
                                account_switches,
                                max_account_switches,
                            )
                            await self._close_profile_timeline_session(
                                session=active_session,
                                builder=builder,
                                lease_id=lease_id,
                                status_code=last_status,
                            )
                            active_session = None
                            leased_account = None
                            lease_id = None
                            builder = None
                            continue
                        break

                    page_tweets, next_cursor = self._extract_profile_tweets_and_cursor(data)
                    unique_added = 0
                    page_unique_tweets: list[TweetRecord] = []
                    for tweet in page_tweets:
                        tweet_id = self._tweet_record_id(tweet)
                        if tweet_id and tweet_id in seen_tweet_ids:
                            continue
                        if tweet_id:
                            seen_tweet_ids.add(tweet_id)
                        collected_tweets.append(tweet)
                        page_unique_tweets.append(tweet)
                        unique_added += 1
                        target_tweets += 1
                        if global_limit is not None and len(collected_tweets) >= global_limit:
                            limit_reached = True
                            break
                        if per_profile_limit is not None and target_tweets >= per_profile_limit:
                            break

                    if page_unique_tweets and on_tweets_page is not None:
                        try:
                            await self._maybe_await(on_tweets_page(page_unique_tweets))
                        except Exception as exc:
                            logger.warning(
                                "Profile timeline streaming callback failed username=%s detail=%s",
                                username,
                                str(exc),
                            )

                    if page_tweets:
                        empty_pages_count = 0
                    else:
                        empty_pages_count += 1
                    logger.info(
                        "Profile timeline page processed status=200 username=%s results=%s unique_results=%s empty_pages=%s/%s next_cursor=%s",
                        username,
                        len(page_tweets),
                        unique_added,
                        empty_pages_count,
                        max_empty_pages,
                        bool(next_cursor),
                    )

                    target_pages += 1
                    if self.accounts_repo is not None and lease_id and hasattr(self.accounts_repo, "record_usage"):
                        await self._maybe_await(self.accounts_repo.record_usage(lease_id, pages=1, tweets=unique_added))
                    cursor = next_cursor
                    if limit_reached:
                        break
                    if per_profile_limit is not None and target_tweets >= per_profile_limit:
                        break
                    if empty_pages_count >= max_empty_pages:
                        target_done = True
                        logger.info(
                            "Profile timeline pagination stopped due to empty pages username=%s empty_pages=%s limit=%s",
                            username,
                            empty_pages_count,
                            max_empty_pages,
                        )
                        break
                    if not next_cursor:
                        target_done = True
                        break

                resume_cursor_value = str(cursor).strip() if cursor else ""
                if target_done or not resume_cursor_value:
                    resume_cursors.pop(target_key, None)
                else:
                    resume_cursors[target_key] = resume_cursor_value

                if target_done:
                    tasks_done += 1
                elif exhausted_accounts:
                    break
                elif last_status == 200:
                    tasks_done += 1
                else:
                    tasks_failed += 1
            finally:
                await self._close_profile_timeline_session(
                    session=active_session,
                    builder=builder,
                    lease_id=lease_id,
                    status_code=last_status,
                )

        stats = RunStats(
            tweets_count=len(collected_tweets),
            tasks_total=len(targets),
            tasks_done=tasks_done,
            tasks_failed=tasks_failed,
            retries=retries,
        )
        completed = not exhausted_accounts and not limit_reached and not resume_cursors

        logger.info(
            "Profile timeline request finished targets=%s tweets=%s completed=%s limit_reached=%s resumable_targets=%s",
            len(targets),
            len(collected_tweets),
            completed,
            limit_reached,
            len(resume_cursors),
        )
        return {
            "result": SearchResult(tweets=collected_tweets, stats=stats),
            "resume_cursors": resume_cursors,
            "completed": completed,
            "limit_reached": limit_reached,
        }

    async def get_follows(self, request, on_follows_page: Optional[Any] = None):
        follows_request = self._coerce_follows_request(request)
        manifest = await self.manifest_provider.get_manifest()
        targets = self._collect_follows_targets(follows_request)
        if not targets:
            logger.info("Follows request received no valid targets")
            return {
                "follows": [],
                "status_code": 400,
                "detail": "No valid targets provided",
                "meta": {"requested": 0, "resolved_targets": 0, "failed_targets": 0, "type": str(follows_request.follow_type)},
                "resume_cursors": {},
                "completed": True,
                "limit_reached": False,
            }

        follow_type = str(follows_request.follow_type or "following").strip().lower()
        if follow_type not in {"followers", "following", "verified_followers"}:
            return {
                "follows": [],
                "status_code": 400,
                "detail": f"Unsupported follow_type={follow_type}",
                "meta": {"requested": len(targets), "resolved_targets": 0, "failed_targets": len(targets), "type": follow_type},
                "resume_cursors": {},
                "completed": True,
                "limit_reached": False,
            }

        global_limit = self._coerce_positive_int(follows_request.limit)
        per_profile_limit = self._coerce_positive_int(follows_request.per_profile_limit)
        max_pages_per_profile = self._coerce_positive_int(follows_request.max_pages_per_profile)
        if max_pages_per_profile is None:
            max_pages_per_profile = float("inf")
        max_empty_pages = self._coerce_positive_int(follows_request.max_empty_pages)
        if max_empty_pages is None:
            max_empty_pages = self._coerce_positive_int(_config_value(self.config, "max_empty_pages", 1)) or 1
        cursor_handoff = bool(follows_request.cursor_handoff)
        configured_switches_raw = _config_value(self.config, "max_account_switches", 2)
        try:
            configured_switches = max(0, int(configured_switches_raw))
        except Exception:
            configured_switches = 2
        if follows_request.max_account_switches is None:
            max_account_switches = configured_switches
        else:
            try:
                max_account_switches = max(0, int(follows_request.max_account_switches))
            except Exception:
                max_account_switches = configured_switches
        try:
            account_requests_per_min = max(1, int(_config_value(self.config, "account_requests_per_min", 30)))
        except Exception:
            account_requests_per_min = 30
        try:
            account_min_delay_s = max(0.0, float(_config_value(self.config, "account_min_delay_s", 2.0)))
        except Exception:
            account_min_delay_s = 2.0

        if follow_type == "following":
            follows_url = self._resolve_following_url(manifest)
            follows_operation = FOLLOWING_OPERATION
        elif follow_type == "verified_followers":
            follows_url = self._resolve_verified_followers_url(manifest)
            follows_operation = VERIFIED_FOLLOWERS_OPERATION
        else:
            follows_url = self._resolve_followers_url(manifest)
            follows_operation = FOLLOWERS_OPERATION

        user_lookup_url = self._resolve_user_lookup_url(manifest)
        timeout_s = int(getattr(manifest, "timeout_s", 20) or 20)
        resume_cursors = self._normalize_resume_cursors(follows_request.initial_cursors)

        collected_follows: list[dict[str, Any]] = []
        tasks_done = 0
        tasks_failed = 0
        retries = 0
        exhausted_accounts = False
        limit_reached = False
        last_status = 200

        logger.info(
            "Follows request started type=%s targets=%s limit=%s per_profile_limit=%s max_pages_per_profile=%s max_empty_pages=%s cursor_handoff=%s",
            follow_type,
            len(targets),
            global_limit if global_limit is not None else "inf",
            per_profile_limit if per_profile_limit is not None else "inf",
            max_pages_per_profile,
            max_empty_pages,
            cursor_handoff,
        )

        for idx, target in enumerate(targets):
            if global_limit is not None and len(collected_follows) >= global_limit:
                limit_reached = True
                break

            target_key = self._profile_target_key(target)
            starting_cursor = resume_cursors.get(target_key)
            cursor = starting_cursor
            username = await self._resolve_target_username(target=target)
            seeded_user_id = str(target.get("user_id") or "").strip() or None
            if not username and not seeded_user_id:
                tasks_failed += 1
                logger.warning(
                    "Follows target skipped index=%s reason=unresolved_target type=%s target=%r",
                    idx,
                    follow_type,
                    target,
                )
                continue

            user_id: Optional[str] = seeded_user_id
            target_done = False
            target_pages = 0
            target_items = 0
            empty_pages_count = 0
            account_switches = 0
            target_seen_ids: set[str] = set()
            last_status = 200
            last_effective_status = 200
            last_headers: dict[str, Any] = {}

            active_session = None
            leased_account: Optional[dict[str, Any]] = None
            lease_id: Optional[str] = None
            builder: Optional[AccountSessionBuilder] = None
            account_limiter: Optional[TokenBucketLimiter] = None
            heartbeat_stop: Optional[asyncio.Event] = None
            heartbeat_task: Optional[asyncio.Task] = None

            logger.info(
                "Follows target start index=%s type=%s username=%s user_id=%s cursor=%s",
                idx,
                follow_type,
                username,
                user_id,
                bool(cursor),
            )

            try:
                while target_pages < max_pages_per_profile:
                    if global_limit is not None and len(collected_follows) >= global_limit:
                        limit_reached = True
                        break
                    if per_profile_limit is not None and target_items >= per_profile_limit:
                        break

                    if active_session is None:
                        active_session, leased_account, lease_id, builder = await self._acquire_follows_session()
                        if active_session is None:
                            exhausted_accounts = True
                            last_status = 503
                            last_effective_status = 503
                            logger.warning("Follows request failed: no eligible account could be leased")
                            break
                        account_limiter = TokenBucketLimiter(
                            requests_per_min=account_requests_per_min,
                            min_delay_s=account_min_delay_s,
                        )
                        heartbeat_stop, heartbeat_task = await self._start_lease_heartbeat(
                            lease_id=lease_id,
                            account_context=leased_account,
                        )

                    if not user_id:
                        lookup_params = self._build_user_lookup_params(username, manifest)
                        if account_limiter is not None:
                            await account_limiter.acquire()
                        lookup_data, lookup_status, lookup_headers, lookup_snippet = await self._graphql_get(
                            url=user_lookup_url,
                            params=lookup_params,
                            timeout_s=timeout_s,
                            session=active_session,
                            account_context=leased_account,
                        )
                        last_headers = lookup_headers or last_headers
                        effective_lookup_status = effective_status_with_rate_limit_headers(lookup_status, lookup_headers)
                        preemptive_lookup_rate_limited = lookup_status == 200 and effective_lookup_status == 429
                        if preemptive_lookup_rate_limited:
                            logger.info(
                                "Follows rate-limit preemptive block type=%s username=%s stage=user_lookup account=%s remaining=%s reset=%s treated_status=%s",
                                follow_type,
                                username,
                                self._account_label(leased_account),
                                parse_rate_limit_remaining(lookup_headers),
                                parse_rate_limit_reset(lookup_headers),
                                effective_lookup_status,
                            )
                        if self.accounts_repo is not None and lease_id and hasattr(self.accounts_repo, "record_usage"):
                            await self._maybe_await(self.accounts_repo.record_usage(lease_id, pages=1, tweets=0))
                        if effective_lookup_status != 200 or lookup_data is None:
                            last_status = int(effective_lookup_status)
                            last_effective_status = int(effective_lookup_status)
                            if cursor_handoff and self._is_handoff_eligible_status(last_status) and account_switches < max_account_switches:
                                retries += 1
                                account_switches += 1
                                logger.info(
                                    "Follows cursor handoff type=%s username=%s stage=user_lookup status=%s switch=%s/%s",
                                    follow_type,
                                    username,
                                    last_status,
                                    account_switches,
                                    max_account_switches,
                                )
                                await self._stop_lease_heartbeat(
                                    lease_id=lease_id,
                                    account_context=leased_account,
                                    stop_event=heartbeat_stop,
                                    task=heartbeat_task,
                                )
                                await self._close_profile_timeline_session(
                                    session=active_session,
                                    builder=builder,
                                    lease_id=lease_id,
                                    status_code=last_status,
                                    headers=last_headers,
                                    use_cooldown=True,
                                    effective_status_code=last_effective_status,
                                )
                                active_session = None
                                leased_account = None
                                lease_id = None
                                builder = None
                                account_limiter = None
                                heartbeat_stop = None
                                heartbeat_task = None
                                continue
                            logger.warning(
                                "Follows user lookup failed type=%s username=%s status=%s snippet=%s headers=%s",
                                follow_type,
                                username,
                                last_status,
                                lookup_snippet,
                                lookup_headers,
                            )
                            break
                        last_status = int(lookup_status)
                        last_effective_status = int(effective_lookup_status)

                        user_result = self._extract_user_result(lookup_data)
                        if not isinstance(user_result, dict):
                            last_status = 404
                            logger.warning(
                                "Follows user lookup failed type=%s username=%s status=404 reason=user_not_found",
                                follow_type,
                                username,
                            )
                            break

                        resolved_user_id = str(user_result.get("rest_id") or user_result.get("id") or "").strip()
                        if not resolved_user_id:
                            legacy = user_result.get("legacy") if isinstance(user_result.get("legacy"), dict) else {}
                            resolved_user_id = str(legacy.get("id_str") or "").strip()
                        if not resolved_user_id:
                            last_status = 404
                            logger.warning(
                                "Follows user lookup failed type=%s username=%s status=404 reason=missing_user_id",
                                follow_type,
                                username,
                            )
                            break
                        user_id = resolved_user_id

                    follows_params = self._build_follows_params(
                        user_id=user_id,
                        cursor=cursor,
                        manifest=manifest,
                        operation=follows_operation,
                        runtime_hints=None,
                    )
                    if account_limiter is not None:
                        await account_limiter.acquire()
                    data, status_code, _headers, _snippet = await self._graphql_get(
                        url=follows_url,
                        params=follows_params,
                        timeout_s=timeout_s,
                        session=active_session,
                        account_context=leased_account,
                    )
                    last_headers = _headers or last_headers
                    effective_timeline_status = effective_status_with_rate_limit_headers(status_code, _headers)
                    preemptive_page_rate_limited = status_code == 200 and effective_timeline_status == 429
                    if preemptive_page_rate_limited:
                        logger.info(
                            "Follows rate-limit preemptive block type=%s username=%s stage=timeline account=%s remaining=%s reset=%s treated_status=%s",
                            follow_type,
                            username,
                            self._account_label(leased_account),
                            parse_rate_limit_remaining(_headers),
                            parse_rate_limit_reset(_headers),
                            effective_timeline_status,
                        )

                    last_status = int(status_code)
                    last_effective_status = int(effective_timeline_status)
                    if status_code != 200 or data is None:
                        if self.accounts_repo is not None and lease_id and hasattr(self.accounts_repo, "record_usage"):
                            await self._maybe_await(self.accounts_repo.record_usage(lease_id, pages=1, tweets=0))
                        if cursor_handoff and self._is_handoff_eligible_status(last_effective_status) and account_switches < max_account_switches:
                            retries += 1
                            account_switches += 1
                            logger.info(
                                "Follows cursor handoff type=%s username=%s stage=timeline status=%s switch=%s/%s",
                                follow_type,
                                username,
                                last_effective_status,
                                account_switches,
                                max_account_switches,
                            )
                            await self._stop_lease_heartbeat(
                                lease_id=lease_id,
                                account_context=leased_account,
                                stop_event=heartbeat_stop,
                                task=heartbeat_task,
                            )
                            await self._close_profile_timeline_session(
                                session=active_session,
                                builder=builder,
                                lease_id=lease_id,
                                status_code=last_effective_status,
                                headers=last_headers,
                                use_cooldown=True,
                                effective_status_code=last_effective_status,
                            )
                            active_session = None
                            leased_account = None
                            lease_id = None
                            builder = None
                            account_limiter = None
                            heartbeat_stop = None
                            heartbeat_task = None
                            continue
                        break

                    page_users, next_cursor = self._extract_follows_users_and_cursor(data)
                    unique_added = 0
                    page_unique_follows: list[dict[str, Any]] = []

                    for user_result in page_users:
                        dedupe_key = self._user_result_dedupe_key(user_result)
                        if not dedupe_key:
                            continue
                        if dedupe_key in target_seen_ids:
                            continue
                        target_seen_ids.add(dedupe_key)

                        mapped_row = self._map_user_result_to_follow_record(
                            user_result=user_result,
                            target=target,
                            follow_type=follow_type,
                        )
                        collected_follows.append(mapped_row)
                        page_unique_follows.append(mapped_row)
                        unique_added += 1
                        target_items += 1
                        if global_limit is not None and len(collected_follows) >= global_limit:
                            limit_reached = True
                            break
                        if per_profile_limit is not None and target_items >= per_profile_limit:
                            break

                    if page_unique_follows and on_follows_page is not None:
                        try:
                            await self._maybe_await(on_follows_page(page_unique_follows))
                        except Exception as exc:
                            logger.warning(
                                "Follows streaming callback failed type=%s username=%s detail=%s",
                                follow_type,
                                username,
                                str(exc),
                            )

                    if page_users:
                        empty_pages_count = 0
                    else:
                        empty_pages_count += 1
                    logger.info(
                        "Follows page processed status=200 type=%s username=%s results=%s unique_results=%s empty_pages=%s/%s next_cursor=%s",
                        follow_type,
                        username,
                        len(page_users),
                        unique_added,
                        empty_pages_count,
                        max_empty_pages,
                        bool(next_cursor),
                    )

                    target_pages += 1
                    if self.accounts_repo is not None and lease_id and hasattr(self.accounts_repo, "record_usage"):
                        await self._maybe_await(self.accounts_repo.record_usage(lease_id, pages=1, tweets=unique_added))
                    cursor = next_cursor
                    if limit_reached:
                        break
                    if per_profile_limit is not None and target_items >= per_profile_limit:
                        break
                    if preemptive_page_rate_limited:
                        if not next_cursor:
                            target_done = True
                            break
                        if cursor_handoff and self._is_handoff_eligible_status(last_effective_status) and account_switches < max_account_switches:
                            retries += 1
                            account_switches += 1
                            logger.info(
                                "Follows cursor handoff type=%s username=%s stage=timeline status=%s switch=%s/%s",
                                follow_type,
                                username,
                                last_effective_status,
                                account_switches,
                                max_account_switches,
                            )
                            await self._stop_lease_heartbeat(
                                lease_id=lease_id,
                                account_context=leased_account,
                                stop_event=heartbeat_stop,
                                task=heartbeat_task,
                            )
                            await self._close_profile_timeline_session(
                                session=active_session,
                                builder=builder,
                                lease_id=lease_id,
                                status_code=last_effective_status,
                                headers=last_headers,
                                use_cooldown=True,
                                effective_status_code=last_effective_status,
                            )
                            active_session = None
                            leased_account = None
                            lease_id = None
                            builder = None
                            account_limiter = None
                            heartbeat_stop = None
                            heartbeat_task = None
                            continue
                        last_status = int(last_effective_status)
                        break
                    if empty_pages_count >= max_empty_pages:
                        target_done = True
                        logger.info(
                            "Follows pagination stopped due to empty pages type=%s username=%s empty_pages=%s limit=%s",
                            follow_type,
                            username,
                            empty_pages_count,
                            max_empty_pages,
                        )
                        break
                    if not next_cursor:
                        target_done = True
                        break

                resume_cursor_value = str(cursor).strip() if cursor else ""
                if target_done or not resume_cursor_value:
                    resume_cursors.pop(target_key, None)
                else:
                    resume_cursors[target_key] = resume_cursor_value

                if target_done:
                    tasks_done += 1
                elif exhausted_accounts:
                    break
                elif last_status == 200:
                    tasks_done += 1
                else:
                    tasks_failed += 1
            finally:
                await self._stop_lease_heartbeat(
                    lease_id=lease_id,
                    account_context=leased_account,
                    stop_event=heartbeat_stop,
                    task=heartbeat_task,
                )
                await self._close_profile_timeline_session(
                    session=active_session,
                    builder=builder,
                    lease_id=lease_id,
                    status_code=last_effective_status,
                    headers=last_headers,
                    use_cooldown=True,
                    effective_status_code=last_effective_status,
                )

        completed = not exhausted_accounts and not limit_reached and not resume_cursors
        if collected_follows:
            status_code = 200
        elif exhausted_accounts:
            status_code = 503
        else:
            status_code = int(last_status or 404)
            if status_code == 200:
                status_code = 404

        logger.info(
            "Follows request finished type=%s targets=%s items=%s completed=%s limit_reached=%s resumable_targets=%s",
            follow_type,
            len(targets),
            len(collected_follows),
            completed,
            limit_reached,
            len(resume_cursors),
        )
        return {
            "follows": collected_follows,
            "status_code": status_code,
            "meta": {
                "requested": len(targets),
                "resolved_targets": tasks_done,
                "failed_targets": tasks_failed,
                "retries": retries,
                "type": follow_type,
            },
            "resume_cursors": resume_cursors,
            "completed": completed,
            "limit_reached": limit_reached,
        }

    def _coerce_profile_request(self, request: Any) -> ProfileRequest:
        if isinstance(request, ProfileRequest):
            return request
        if isinstance(request, dict):
            payload = {
                "handles": request.get("handles") or [],
                "profile_urls": request.get("profile_urls") or [],
                "targets": request.get("targets") or [],
                "login": request.get("login", False),
            }
            return ProfileRequest.model_validate(payload)
        return ProfileRequest.model_validate(request)

    def _coerce_profile_timeline_request(self, request: Any) -> ProfileTimelineRequest:
        if isinstance(request, ProfileTimelineRequest):
            return request
        if isinstance(request, dict):
            payload = {
                "targets": request.get("targets") or [],
                "limit": request.get("limit"),
                "per_profile_limit": request.get("per_profile_limit"),
                "max_pages_per_profile": request.get("max_pages_per_profile"),
                "resume": bool(request.get("resume", False)),
                "query_hash": request.get("query_hash"),
                "initial_cursors": request.get("initial_cursors") or {},
                "cursor_handoff": bool(request.get("cursor_handoff", False)),
                "max_account_switches": request.get("max_account_switches"),
                "allow_anonymous": bool(request.get("allow_anonymous", False)),
                "max_empty_pages": request.get("max_empty_pages"),
            }
            return ProfileTimelineRequest.model_validate(payload)
        return ProfileTimelineRequest.model_validate(request)

    def _coerce_follows_request(self, request: Any) -> FollowsRequest:
        if isinstance(request, FollowsRequest):
            return request
        if isinstance(request, dict):
            payload = {
                "targets": request.get("targets") or [],
                "follow_type": request.get("follow_type", "following"),
                "limit": request.get("limit"),
                "per_profile_limit": request.get("per_profile_limit"),
                "max_pages_per_profile": request.get("max_pages_per_profile"),
                "resume": bool(request.get("resume", False)),
                "query_hash": request.get("query_hash"),
                "initial_cursors": request.get("initial_cursors") or {},
                "cursor_handoff": bool(request.get("cursor_handoff", False)),
                "max_account_switches": request.get("max_account_switches"),
                "max_empty_pages": request.get("max_empty_pages"),
                "raw_json": bool(request.get("raw_json", False)),
            }
            return FollowsRequest.model_validate(payload)
        return FollowsRequest.model_validate(request)

    def _collect_profile_targets(self, request: ProfileRequest) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        seen: set[str] = set()

        def _append(target: dict[str, Any]) -> None:
            username = str(target.get("username") or "").strip()
            profile_url = str(target.get("profile_url") or "").strip()

            key = ""
            if username:
                key = f"username:{username.lower()}"
            elif profile_url:
                key = f"url:{profile_url.lower()}"
            if not key or key in seen:
                return
            seen.add(key)

            row: dict[str, str] = {}
            raw = str(target.get("raw") or "").strip()
            source = str(target.get("source") or "").strip()
            if raw:
                row["raw"] = raw
            if source:
                row["source"] = source
            if username:
                row["username"] = username
            if profile_url:
                row["profile_url"] = profile_url
            out.append(row)

        for target in list(request.targets or []):
            if isinstance(target, dict):
                _append(target)
        for handle in list(request.handles or []):
            _append({"raw": str(handle), "source": "handles", "username": str(handle).strip().lstrip("@")})
        for profile_url in list(request.profile_urls or []):
            _append({"raw": str(profile_url), "source": "profile_urls", "profile_url": str(profile_url).strip()})

        return out

    def _collect_profile_timeline_targets(self, request: ProfileTimelineRequest) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        seen: set[str] = set()

        for target in list(request.targets or []):
            if not isinstance(target, dict):
                continue
            row = {
                "raw": str(target.get("raw") or "").strip(),
                "source": str(target.get("source") or "").strip(),
                "user_id": str(target.get("user_id") or "").strip(),
                "username": str(target.get("username") or "").strip().lstrip("@"),
                "profile_url": str(target.get("profile_url") or "").strip(),
            }
            key = self._profile_target_key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    def _collect_follows_targets(self, request: FollowsRequest) -> list[dict[str, str]]:
        out: list[dict[str, str]] = []
        seen: set[str] = set()

        for target in list(request.targets or []):
            if not isinstance(target, dict):
                continue
            row = {
                "raw": str(target.get("raw") or "").strip(),
                "source": str(target.get("source") or "").strip(),
                "user_id": str(target.get("user_id") or "").strip(),
                "username": str(target.get("username") or "").strip().lstrip("@"),
                "profile_url": str(target.get("profile_url") or "").strip(),
            }
            key = self._profile_target_key(row)
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(row)
        return out

    @staticmethod
    def _normalize_resume_cursors(value: Any) -> dict[str, str]:
        if not isinstance(value, dict):
            return {}
        out: dict[str, str] = {}
        for key, cursor in value.items():
            normalized_key = str(key or "").strip()
            normalized_cursor = str(cursor or "").strip()
            if not normalized_key or not normalized_cursor:
                continue
            out[normalized_key] = normalized_cursor
        return out

    @staticmethod
    def _profile_target_key(target: dict[str, Any]) -> str:
        user_id = str(target.get("user_id") or "").strip()
        if user_id:
            return f"id:{user_id}"
        username = str(target.get("username") or "").strip().lstrip("@")
        if username:
            return f"username:{username.lower()}"
        profile_url = str(target.get("profile_url") or "").strip().lower()
        if profile_url:
            return f"url:{profile_url}"
        raw = str(target.get("raw") or "").strip().lower()
        if raw:
            return f"raw:{raw}"
        return ""

    async def _acquire_profile_session(self) -> tuple[Optional[Any], Optional[dict[str, Any]], Optional[str], Optional[AccountSessionBuilder]]:
        if self.accounts_repo is None or not hasattr(self.accounts_repo, "acquire_leases"):
            return None, None, None, None

        run_id = f"profiles:{uuid.uuid4()}"
        leases = await self._maybe_await(
            self.accounts_repo.acquire_leases(
                count=1,
                run_id=run_id,
                worker_id_prefix="profiles",
            )
        )
        leases = list(leases or [])
        if not leases:
            diagnostics = None
            if hasattr(self.accounts_repo, "eligibility_diagnostics"):
                try:
                    diagnostics = await self._maybe_await(
                        self.accounts_repo.eligibility_diagnostics(sample_limit=5)
                    )
                except Exception:
                    diagnostics = None
            if isinstance(diagnostics, dict):
                logger.warning(
                    "Profiles lease unavailable total=%s eligible=%s blocked=%s sample=%s",
                    diagnostics.get("total"),
                    diagnostics.get("eligible"),
                    diagnostics.get("blocked_counts"),
                    diagnostics.get("blocked_samples"),
                )
            return None, None, None, None

        account = dict(leases[0])
        lease_id = str(account.get("lease_id") or "").strip() or None
        builder = AccountSessionBuilder(
            session_factory=self.session_factory,
            api_http_mode=self.http_mode,
            proxy=_config_value(self.config, "proxy", None),
            user_agent=_config_value(self.config, "api_user_agent", None),
            impersonate=str(_config_value(self.config, "api_http_impersonate", "chrome120") or "chrome120"),
        )
        try:
            built = await self._maybe_await(builder.build(account))
            if isinstance(built, tuple):
                session = built[0]
            else:
                session = built
            context = {
                "id": account.get("id"),
                "username": account.get("username"),
                "lease_id": lease_id,
            }
            return session, context, lease_id, builder
        except Exception:
            if lease_id and hasattr(self.accounts_repo, "release"):
                await self._maybe_await(self.accounts_repo.release(lease_id, fields_to_set={}, fields_to_inc={}))
            return None, None, None, None

    async def _acquire_follows_session(self) -> tuple[Optional[Any], Optional[dict[str, Any]], Optional[str], Optional[AccountSessionBuilder]]:
        if self.accounts_repo is None or not hasattr(self.accounts_repo, "acquire_leases"):
            return None, None, None, None

        run_id = f"follows:{uuid.uuid4()}"
        leases = await self._maybe_await(
            self.accounts_repo.acquire_leases(
                count=1,
                run_id=run_id,
                worker_id_prefix="follows",
            )
        )
        leases = list(leases or [])
        if not leases:
            diagnostics = None
            if hasattr(self.accounts_repo, "eligibility_diagnostics"):
                try:
                    diagnostics = await self._maybe_await(
                        self.accounts_repo.eligibility_diagnostics(sample_limit=5)
                    )
                except Exception:
                    diagnostics = None
            if isinstance(diagnostics, dict):
                logger.warning(
                    "Follows lease unavailable total=%s eligible=%s blocked=%s sample=%s",
                    diagnostics.get("total"),
                    diagnostics.get("eligible"),
                    diagnostics.get("blocked_counts"),
                    diagnostics.get("blocked_samples"),
                )
            return None, None, None, None

        account = dict(leases[0])
        lease_id = str(account.get("lease_id") or "").strip() or None
        builder = AccountSessionBuilder(
            session_factory=self.session_factory,
            api_http_mode=self.http_mode,
            proxy=_config_value(self.config, "proxy", None),
            user_agent=_config_value(self.config, "api_user_agent", None),
            impersonate=str(_config_value(self.config, "api_http_impersonate", "chrome120") or "chrome120"),
        )
        try:
            built = await self._maybe_await(builder.build(account))
            if isinstance(built, tuple):
                session = built[0]
            else:
                session = built
            context = {
                "id": account.get("id"),
                "username": account.get("username"),
                "lease_id": lease_id,
            }
            return session, context, lease_id, builder
        except Exception:
            if lease_id and hasattr(self.accounts_repo, "release"):
                await self._maybe_await(self.accounts_repo.release(lease_id, fields_to_set={}, fields_to_inc={}))
            return None, None, None, None

    async def _close_profile_timeline_session(
        self,
        *,
        session: Any,
        builder: Optional[AccountSessionBuilder],
        lease_id: Optional[str],
        status_code: int,
        headers: Optional[dict[str, Any]] = None,
        use_cooldown: bool = False,
        effective_status_code: Optional[int] = None,
    ) -> None:
        if session is not None:
            try:
                if builder is not None and hasattr(builder, "close"):
                    await self._maybe_await(builder.close(session))
                else:
                    await self._close_session(session)
            except Exception:
                pass

        if lease_id and self.accounts_repo is not None and hasattr(self.accounts_repo, "release"):
            raw_status = int(status_code or 200)
            effective_status = int(effective_status_code if effective_status_code is not None else raw_status)
            fields_to_set: dict[str, Any] = {}
            if use_cooldown:
                next_status, available_til, cooldown_reason = compute_cooldown(
                    effective_status,
                    headers,
                    self.config,
                )
                fields_to_set["status"] = int(next_status)
                fields_to_set["available_til"] = float(available_til)
                fields_to_set["cooldown_reason"] = cooldown_reason
                fields_to_set["last_error_code"] = None if effective_status in {1, 200} else int(effective_status)
            elif raw_status in {401, 403}:
                fields_to_set["status"] = int(raw_status)
                fields_to_set["last_error_code"] = int(raw_status)
            elif raw_status and raw_status != 200:
                fields_to_set["last_error_code"] = int(raw_status)
            else:
                fields_to_set["last_error_code"] = None
            try:
                await self._maybe_await(self.accounts_repo.release(lease_id, fields_to_set=fields_to_set, fields_to_inc={}))
            except Exception:
                pass

    @staticmethod
    def _is_handoff_eligible_status(status_code: int) -> bool:
        if status_code in {401, 403, 429, JSON_DECODE_STATUS, NETWORK_ERROR_STATUS}:
            return True
        return 500 <= int(status_code or 0) < 600

    async def _resolve_target_username(
        self,
        *,
        target: dict[str, str],
    ) -> Optional[str]:
        username = str(target.get("username") or "").strip().lstrip("@")
        if username:
            return username

        profile_url = str(target.get("profile_url") or "").strip()
        if profile_url:
            parsed = urlparse(profile_url if "://" in profile_url else f"https://{profile_url}")
            path_parts = [part for part in str(parsed.path or "").split("/") if part]
            if len(path_parts) == 1:
                handle = path_parts[0].strip().lstrip("@")
                if handle:
                    return handle

        return None

    def _resolve_user_lookup_url(self, manifest) -> str:
        query_id = (manifest.query_ids or {}).get(USER_LOOKUP_OPERATION) or DEFAULT_USER_LOOKUP_QUERY_ID
        endpoint = (manifest.endpoints or {}).get(USER_LOOKUP_OPERATION) or DEFAULT_USER_LOOKUP_ENDPOINT
        if "{query_id}" in endpoint:
            return endpoint.format(query_id=query_id)
        return endpoint

    def _resolve_profile_timeline_url(self, manifest) -> str:
        query_id = (manifest.query_ids or {}).get(PROFILE_TIMELINE_OPERATION) or DEFAULT_PROFILE_TIMELINE_QUERY_ID
        endpoint = (manifest.endpoints or {}).get(PROFILE_TIMELINE_OPERATION) or DEFAULT_PROFILE_TIMELINE_ENDPOINT
        if "{query_id}" in endpoint:
            return endpoint.format(query_id=query_id)
        return endpoint

    def _resolve_followers_url(self, manifest) -> str:
        query_id = (manifest.query_ids or {}).get(FOLLOWERS_OPERATION) or DEFAULT_FOLLOWERS_QUERY_ID
        endpoint = (manifest.endpoints or {}).get(FOLLOWERS_OPERATION) or DEFAULT_FOLLOWERS_ENDPOINT
        if "{query_id}" in endpoint:
            return endpoint.format(query_id=query_id)
        return endpoint

    def _resolve_following_url(self, manifest) -> str:
        query_id = (manifest.query_ids or {}).get(FOLLOWING_OPERATION) or DEFAULT_FOLLOWING_QUERY_ID
        endpoint = (manifest.endpoints or {}).get(FOLLOWING_OPERATION) or DEFAULT_FOLLOWING_ENDPOINT
        if "{query_id}" in endpoint:
            return endpoint.format(query_id=query_id)
        return endpoint

    def _resolve_verified_followers_url(self, manifest) -> str:
        query_id = (
            (manifest.query_ids or {}).get(VERIFIED_FOLLOWERS_OPERATION)
            or DEFAULT_VERIFIED_FOLLOWERS_QUERY_ID
        )
        endpoint = (
            (manifest.endpoints or {}).get(VERIFIED_FOLLOWERS_OPERATION)
            or DEFAULT_VERIFIED_FOLLOWERS_ENDPOINT
        )
        if "{query_id}" in endpoint:
            return endpoint.format(query_id=query_id)
        return endpoint

    def _build_user_lookup_params(self, username: str, manifest) -> dict[str, str]:
        variables = {
            "screen_name": username,
            "withGrokTranslatedBio": False,
        }
        features_payload = (
            manifest.features_for(USER_LOOKUP_OPERATION)
            if hasattr(manifest, "features_for")
            else (manifest.features or {})
        )
        params: dict[str, str] = {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(features_payload or {}, separators=(",", ":")),
        }
        field_toggles_payload = (
            manifest.field_toggles_for(USER_LOOKUP_OPERATION)
            if hasattr(manifest, "field_toggles_for")
            else None
        )
        if field_toggles_payload:
            params["fieldToggles"] = json.dumps(field_toggles_payload, separators=(",", ":"))
        return params

    def _build_profile_timeline_params(
        self,
        *,
        user_id: str,
        cursor: Optional[str],
        manifest,
        runtime_hints: Optional[dict[str, Optional[int]]] = None,
    ) -> dict[str, str]:
        count = self._resolve_page_size(runtime_hints=runtime_hints)
        variables: dict[str, Any] = {
            "userId": str(user_id),
            "count": int(count),
            "includePromotedContent": True,
            "withQuickPromoteEligibilityTweetFields": True,
            "withVoice": True,
        }
        if cursor:
            variables["cursor"] = cursor

        features_payload = (
            manifest.features_for(PROFILE_TIMELINE_OPERATION)
            if hasattr(manifest, "features_for")
            else (manifest.features or {})
        )
        params: dict[str, str] = {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(features_payload or {}, separators=(",", ":")),
        }
        field_toggles_payload = (
            manifest.field_toggles_for(PROFILE_TIMELINE_OPERATION)
            if hasattr(manifest, "field_toggles_for")
            else None
        )
        if field_toggles_payload:
            params["fieldToggles"] = json.dumps(field_toggles_payload, separators=(",", ":"))
        return params

    def _build_follows_params(
        self,
        *,
        user_id: str,
        cursor: Optional[str],
        manifest,
        operation: str,
        runtime_hints: Optional[dict[str, Optional[int]]] = None,
    ) -> dict[str, str]:
        count = self._resolve_page_size(runtime_hints=runtime_hints)
        variables: dict[str, Any] = {
            "userId": str(user_id),
            "count": int(count),
            "includePromotedContent": False,
            "withGrokTranslatedBio": False,
        }
        if cursor:
            variables["cursor"] = cursor

        features_payload_raw = (
            manifest.features_for(operation)
            if hasattr(manifest, "features_for")
            else (manifest.features or {})
        )
        features_payload = dict(features_payload_raw or {})
        for key, value in DEFAULT_FOLLOWS_FEATURES.items():
            if key not in features_payload or features_payload.get(key) is None:
                features_payload[key] = value
        params: dict[str, str] = {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(features_payload or {}, separators=(",", ":")),
        }
        field_toggles_payload = (
            manifest.field_toggles_for(operation)
            if hasattr(manifest, "field_toggles_for")
            else None
        )
        if field_toggles_payload:
            params["fieldToggles"] = json.dumps(field_toggles_payload, separators=(",", ":"))
        return params

    @staticmethod
    def _extract_user_result(payload: Any) -> Optional[dict[str, Any]]:
        if not isinstance(payload, dict):
            return None
        data_node = payload.get("data")
        if not isinstance(data_node, dict):
            return None
        user_node = data_node.get("user")
        if not isinstance(user_node, dict):
            return None
        result = user_node.get("result")
        if isinstance(result, dict):
            return result
        return None

    @staticmethod
    def _as_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0

    @staticmethod
    def _first_non_empty_str(*values: Any) -> Optional[str]:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _extract_user_result_profile_fields(
        self,
        user_result: dict[str, Any],
        *,
        fallback_username: str = "",
    ) -> dict[str, Any]:
        legacy = user_result.get("legacy") if isinstance(user_result.get("legacy"), dict) else {}
        core = user_result.get("core") if isinstance(user_result.get("core"), dict) else {}
        verification = user_result.get("verification") if isinstance(user_result.get("verification"), dict) else {}
        privacy = user_result.get("privacy") if isinstance(user_result.get("privacy"), dict) else {}
        avatar = user_result.get("avatar") if isinstance(user_result.get("avatar"), dict) else {}
        location_node = user_result.get("location") if isinstance(user_result.get("location"), dict) else {}
        profile_bio = user_result.get("profile_bio") if isinstance(user_result.get("profile_bio"), dict) else {}
        entities = legacy.get("entities") if isinstance(legacy.get("entities"), dict) else {}

        url_value = self._first_non_empty_str(legacy.get("url"))
        if not url_value:
            url_node = entities.get("url") if isinstance(entities.get("url"), dict) else {}
            url_candidates = url_node.get("urls") if isinstance(url_node.get("urls"), list) else []
            for url_row in url_candidates:
                if not isinstance(url_row, dict):
                    continue
                url_value = self._first_non_empty_str(
                    url_row.get("expanded_url"),
                    url_row.get("url"),
                    url_row.get("display_url"),
                )
                if url_value:
                    break

        verified_value = bool(legacy.get("verified", False)) or bool(verification.get("verified", False))
        protected_value = bool(legacy.get("protected", False)) or bool(privacy.get("protected", False))
        blue_verified_value = bool(user_result.get("is_blue_verified", False)) or bool(
            verification.get("is_blue_verified", False)
        )

        return {
            "user_id": self._first_non_empty_str(
                user_result.get("rest_id"),
                user_result.get("id"),
                legacy.get("id_str"),
            ),
            "username": self._first_non_empty_str(
                legacy.get("screen_name"),
                core.get("screen_name"),
                fallback_username,
            ),
            "name": self._first_non_empty_str(
                legacy.get("name"),
                core.get("name"),
            ),
            "description": self._first_non_empty_str(
                legacy.get("description"),
                profile_bio.get("description"),
            ),
            "location": self._first_non_empty_str(
                legacy.get("location"),
                location_node.get("location"),
            ),
            "created_at": self._first_non_empty_str(
                legacy.get("created_at"),
                core.get("created_at"),
            ),
            "followers_count": self._as_int(legacy.get("followers_count")),
            "following_count": self._as_int(legacy.get("friends_count")),
            "statuses_count": self._as_int(legacy.get("statuses_count")),
            "favourites_count": self._as_int(legacy.get("favourites_count")),
            "media_count": self._as_int(legacy.get("media_count")),
            "listed_count": self._as_int(legacy.get("listed_count")),
            "verified": verified_value,
            "blue_verified": blue_verified_value,
            "protected": protected_value,
            "profile_image_url": self._first_non_empty_str(
                legacy.get("profile_image_url_https"),
                legacy.get("profile_image_url"),
                avatar.get("image_url"),
            ),
            "profile_banner_url": self._first_non_empty_str(
                legacy.get("profile_banner_url"),
                avatar.get("banner_image_url"),
            ),
            "url": url_value,
        }

    def _map_user_result_to_profile_record(
        self,
        user_result: dict[str, Any],
        *,
        target: dict[str, str],
        username: str,
    ) -> dict[str, Any]:
        normalized = self._extract_user_result_profile_fields(
            user_result,
            fallback_username=username,
        )
        return {
            "input": {
                "raw": target.get("raw"),
                "source": target.get("source"),
            },
            "user_id": normalized.get("user_id"),
            "username": normalized.get("username"),
            "name": normalized.get("name"),
            "description": normalized.get("description"),
            "location": normalized.get("location"),
            "created_at": normalized.get("created_at"),
            "followers_count": normalized.get("followers_count"),
            "following_count": normalized.get("following_count"),
            "statuses_count": normalized.get("statuses_count"),
            "favourites_count": normalized.get("favourites_count"),
            "media_count": normalized.get("media_count"),
            "listed_count": normalized.get("listed_count"),
            "verified": bool(normalized.get("verified", False)),
            "blue_verified": bool(normalized.get("blue_verified", False)),
            "protected": bool(normalized.get("protected", False)),
            "profile_image_url": normalized.get("profile_image_url"),
            "profile_banner_url": normalized.get("profile_banner_url"),
            "url": normalized.get("url"),
            "raw": user_result,
        }

    def _map_user_result_to_follow_record(
        self,
        *,
        user_result: dict[str, Any],
        target: dict[str, str],
        follow_type: str,
    ) -> dict[str, Any]:
        normalized = self._extract_user_result_profile_fields(user_result)
        return {
            "type": str(follow_type),
            "target": {
                "raw": target.get("raw"),
                "source": target.get("source"),
                "user_id": target.get("user_id"),
                "username": target.get("username"),
                "profile_url": target.get("profile_url"),
            },
            "user_id": normalized.get("user_id"),
            "username": normalized.get("username"),
            "name": normalized.get("name"),
            "description": normalized.get("description"),
            "location": normalized.get("location"),
            "created_at": normalized.get("created_at"),
            "followers_count": normalized.get("followers_count"),
            "following_count": normalized.get("following_count"),
            "statuses_count": normalized.get("statuses_count"),
            "favourites_count": normalized.get("favourites_count"),
            "media_count": normalized.get("media_count"),
            "listed_count": normalized.get("listed_count"),
            "verified": bool(normalized.get("verified", False)),
            "blue_verified": bool(normalized.get("blue_verified", False)),
            "protected": bool(normalized.get("protected", False)),
            "profile_image_url": normalized.get("profile_image_url"),
            "profile_banner_url": normalized.get("profile_banner_url"),
            "url": normalized.get("url"),
            "raw": user_result,
        }

    @staticmethod
    def _user_result_dedupe_key(user_result: Any) -> str:
        if not isinstance(user_result, dict):
            return ""
        legacy = user_result.get("legacy") if isinstance(user_result.get("legacy"), dict) else {}
        rest_id = str(user_result.get("rest_id") or user_result.get("id") or legacy.get("id_str") or "").strip()
        if rest_id:
            return f"id:{rest_id}"
        username = str(legacy.get("screen_name") or "").strip().lower()
        if username:
            return f"username:{username}"
        return ""

    def _coerce_search_request(self, request: Any) -> SearchRequest:
        if isinstance(request, SearchRequest):
            return request
        if isinstance(request, dict):
            return SearchRequest.model_validate(request)
        return SearchRequest.model_validate(request)

    @staticmethod
    def _extract_runtime_context(request: Any) -> Tuple[Optional[Any], Optional[dict[str, Any]], dict[str, Optional[int]]]:
        runtime_hints: dict[str, Optional[int]] = {"page_size": None}
        if isinstance(request, dict):
            session = request.get("_account_session")
            account_context = request.get("_leased_account") or request.get("_account")
            runtime_hints["page_size"] = ApiEngine._coerce_positive_int(request.get("_page_size"))
            if isinstance(account_context, dict):
                return session, account_context, runtime_hints
            return session, None, runtime_hints
        return None, None, runtime_hints

    @staticmethod
    async def _maybe_await(value: Any):
        if inspect.isawaitable(value):
            return await value
        return value

    async def _start_lease_heartbeat(
        self,
        *,
        lease_id: Optional[str],
        account_context: Optional[dict[str, Any]],
    ) -> tuple[Optional[asyncio.Event], Optional[asyncio.Task]]:
        normalized_lease_id = str(lease_id or "").strip()
        if not normalized_lease_id:
            return None, None
        if self.accounts_repo is None or not hasattr(self.accounts_repo, "heartbeat"):
            return None, None

        heartbeat_every_s = max(0.0, float(_config_value(self.config, "account_lease_heartbeat_s", 30.0)))
        if heartbeat_every_s <= 0:
            return None, None

        ttl_s = max(1, int(_config_value(self.config, "account_lease_ttl_s", 120)))
        stop_event = asyncio.Event()
        logger.info(
            "Account heartbeat started username=%s id=%s lease_id=%s interval_s=%s ttl_s=%s",
            (account_context or {}).get("username"),
            (account_context or {}).get("id"),
            normalized_lease_id,
            heartbeat_every_s,
            ttl_s,
        )
        task = asyncio.create_task(
            self._lease_heartbeat_loop(
                lease_id=normalized_lease_id,
                account_context=account_context,
                interval_s=heartbeat_every_s,
                ttl_s=ttl_s,
                stop_event=stop_event,
            )
        )
        return stop_event, task

    async def _stop_lease_heartbeat(
        self,
        *,
        lease_id: Optional[str],
        account_context: Optional[dict[str, Any]],
        stop_event: Optional[asyncio.Event],
        task: Optional[asyncio.Task],
    ) -> None:
        if task is None:
            return
        if stop_event is not None:
            stop_event.set()
        cancelled = False
        try:
            await task
        except asyncio.CancelledError:
            cancelled = True
        except Exception:
            pass
        logger.info(
            "Account heartbeat stopped username=%s id=%s lease_id=%s",
            (account_context or {}).get("username"),
            (account_context or {}).get("id"),
            str(lease_id or "").strip() or None,
        )
        if cancelled:
            raise asyncio.CancelledError

    async def _lease_heartbeat_loop(
        self,
        *,
        lease_id: str,
        account_context: Optional[dict[str, Any]],
        interval_s: float,
        ttl_s: int,
        stop_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                pass
            if stop_event.is_set():
                break

            try:
                renewed = await self._maybe_await(self.accounts_repo.heartbeat(lease_id, extend_by_s=ttl_s))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Account heartbeat failed username=%s id=%s lease_id=%s detail=%s",
                    (account_context or {}).get("username"),
                    (account_context or {}).get("id"),
                    lease_id,
                    str(exc),
                )
                continue

            if not renewed:
                logger.warning(
                    "Account heartbeat failed username=%s id=%s lease_id=%s detail=lease_not_found",
                    (account_context or {}).get("username"),
                    (account_context or {}).get("id"),
                    lease_id,
                )
                break

    def _build_graphql_params(
        self,
        request: SearchRequest,
        cursor: Optional[str],
        manifest,
        *,
        runtime_hints: Optional[dict[str, Optional[int]]] = None,
    ) -> dict[str, str]:
        variables = self._build_variables(request, cursor, runtime_hints=runtime_hints)
        features_payload = (
            manifest.features_for("search_timeline")
            if hasattr(manifest, "features_for")
            else (manifest.features or {})
        )
        params: dict[str, str] = {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(features_payload or {}, separators=(",", ":")),
        }
        field_toggles_payload = (
            manifest.field_toggles_for("search_timeline")
            if hasattr(manifest, "field_toggles_for")
            else None
        )
        if field_toggles_payload:
            params["fieldToggles"] = json.dumps(field_toggles_payload, separators=(",", ":"))
        return params

    def _build_variables(
        self,
        request: SearchRequest,
        cursor: Optional[str],
        *,
        runtime_hints: Optional[dict[str, Optional[int]]] = None,
    ) -> dict[str, Any]:
        request_payload = request.model_dump(mode="python")
        normalized_query, _errors, _warnings = normalize_search_input(request_payload)
        if request.since:
            normalized_query["since"] = request.since
        if request.until:
            normalized_query["until"] = request.until
        if request.lang and not normalized_query.get("lang"):
            normalized_query["lang"] = request.lang
        if request.display_type and not normalized_query.get("search_sort"):
            normalized_query["search_sort"] = request.display_type

        raw_query = build_effective_search_query(normalized_query).strip()
        if not raw_query:
            raw_query = "from:elonmusk"

        display = (request.display_type or "Latest").strip().lower()
        product = "Latest" if display in {"recent", "latest"} else "Top"

        count = self._resolve_page_size(runtime_hints=runtime_hints)

        variables = {
            "rawQuery": raw_query,
            "count": count,
            "querySource": "typed_query",
            "product": product,
            "withGrokTranslatedBio": False,
        }
        if cursor:
            variables["cursor"] = cursor
        return variables

    def _resolve_page_size(self, *, runtime_hints: Optional[dict[str, Optional[int]]]) -> int:
        configured_page_size = self._coerce_positive_int(_config_value(self.config, "api_page_size", 20)) or 20
        count = max(1, min(int(configured_page_size), 100))

        hinted_page_size = self._coerce_positive_int((runtime_hints or {}).get("page_size"))
        if hinted_page_size is not None:
            count = max(1, min(int(hinted_page_size), 100))

        return int(count)

    @staticmethod
    def _coerce_positive_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        try:
            parsed = int(value)
        except Exception:
            return None
        if parsed <= 0:
            return None
        return parsed

    def _resolve_search_url(self, manifest) -> str:
        query_id = manifest.query_ids["search_timeline"]
        endpoint = manifest.endpoints["search_timeline"]
        if "{query_id}" in endpoint:
            return endpoint.format(query_id=query_id)
        return endpoint

    @staticmethod
    def _map_graphql_errors_to_status(errors) -> Optional[int]:
        for err in errors or []:
            if not isinstance(err, dict):
                continue
            message = str(err.get("message") or "").lower()
            extensions = err.get("extensions") or {}
            code = str(extensions.get("code") or extensions.get("errorType") or "").upper()

            if "rate limit" in message or "too many requests" in message or code in {"RATE_LIMITED", "RATE_LIMIT"}:
                return 429
            if (
                "authorization" in message
                or "auth" in message
                or "unauthorized" in message
                or code in {"UNAUTHORIZED", "AUTHENTICATION_ERROR"}
            ):
                return 401
            if "forbidden" in message or "suspended" in message or code in {"FORBIDDEN", "ACCOUNT_SUSPENDED"}:
                return 403
        return None

    async def _graphql_get(
        self,
        *,
        url: str,
        params: dict[str, str],
        timeout_s: int,
        session=None,
        account_context: Optional[dict[str, Any]] = None,
    ):
        active_session = session or self.session_factory()
        owns_session = session is None
        account_label = self._account_label(account_context)
        try:
            request_headers: dict[str, str] = {}
            tx_id = await self._build_transaction_id(method="GET", url=url)
            if tx_id:
                request_headers["X-Client-Transaction-Id"] = tx_id

            response = await self._session_get(
                active_session,
                url,
                params=params,
                timeout=timeout_s,
                allow_redirects=True,
                headers=request_headers if request_headers else None,
            )
            status = int(getattr(response, "status_code", 0) or 0)
            headers = dict(getattr(response, "headers", {}) or {})
            text_snippet = str(getattr(response, "text", "") or "")[:200]

            if status != 200:
                logger.info(
                    "API request endpoint=%s status=%s account=%s snippet=%s",
                    url,
                    status,
                    account_label,
                    text_snippet[:160],
                )
                return None, status, headers, text_snippet

            try:
                payload = await self._response_json(response)
            except Exception:
                logger.info("API request endpoint=%s status=%s account=%s", url, JSON_DECODE_STATUS, account_label)
                return None, JSON_DECODE_STATUS, headers, text_snippet

            if isinstance(payload, dict) and payload.get("errors"):
                mapped = self._map_graphql_errors_to_status(payload.get("errors"))
                if mapped is not None:
                    logger.info("API request endpoint=%s status=%s account=%s", url, mapped, account_label)
                    return None, mapped, headers, text_snippet

            return payload, status, headers, text_snippet
        except Exception as exc:
            detail = str(exc)
            logger.warning(
                "API request endpoint=%s status=%s account=%s detail=%s",
                url,
                NETWORK_ERROR_STATUS,
                account_label,
                detail,
            )
            return None, NETWORK_ERROR_STATUS, {}, detail[:200]
        finally:
            if owns_session:
                await self._close_session(active_session)

    async def _session_get(self, session, url: str, **kwargs):
        if kwargs.get("headers") is None:
            kwargs.pop("headers", None)
        getter = getattr(session, "get")
        if self.http_mode == HTTP_MODE_SYNC:
            self._log_http_mode_selection(mode=HTTP_MODE_SYNC, source="explicit")
            result = await self._call_in_thread(getter, url, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        if inspect.iscoroutinefunction(getter):
            source = "explicit" if self.http_mode == HTTP_MODE_ASYNC else "auto"
            self._log_http_mode_selection(mode=HTTP_MODE_ASYNC, source=source)
            result = getter(url, **kwargs)
            if inspect.isawaitable(result):
                return await result
            return result

        if self.http_mode == HTTP_MODE_ASYNC:
            self._log_http_mode_selection(mode=HTTP_MODE_SYNC, source="explicit_async_fallback")
            logger.info("API HTTP mode fallback requested=%s resolved=%s", HTTP_MODE_ASYNC, HTTP_MODE_SYNC)
        else:
            self._log_http_mode_selection(mode=HTTP_MODE_SYNC, source="auto_fallback_non_async_session")
            logger.info("API HTTP mode fallback requested=%s resolved=%s", HTTP_MODE_AUTO, HTTP_MODE_SYNC)

        result = await self._call_in_thread(getter, url, **kwargs)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _response_json(self, response):
        json_reader = getattr(response, "json")
        result = json_reader()
        if inspect.isawaitable(result):
            return await result
        return result

    async def _close_session(self, session) -> None:
        closer = getattr(session, "close", None)
        if closer is None:
            return
        if inspect.iscoroutinefunction(closer):
            await closer()
            return
        maybe_awaitable = closer()
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable

    def _log_http_mode_selection(self, *, mode: str, source: str) -> None:
        key = (mode, source)
        if key in self._logged_http_mode_selection:
            return
        self._logged_http_mode_selection.add(key)
        logger.info("API HTTP mode selected mode=%s source=%s", mode, source)

    @staticmethod
    def _account_label(account_context: Optional[dict[str, Any]]) -> str:
        if not isinstance(account_context, dict):
            return "-"
        username = account_context.get("username")
        account_id = account_context.get("id")
        if username and account_id:
            return f"{username}:{account_id}"
        if username:
            return str(username)
        if account_id:
            return str(account_id)
        return "-"

    async def _build_transaction_id(self, *, method: str, url: str) -> Optional[str]:
        provider = self.transaction_id_provider
        if provider is None or not hasattr(provider, "generate"):
            return None

        path = urlparse(url).path
        try:
            generate = getattr(provider, "generate")
            if inspect.iscoroutinefunction(generate):
                return await generate(method=method, path=path)
            value = await self._call_in_thread(generate, method=method, path=path)
            if inspect.isawaitable(value):
                return await value
            return value
        except Exception:
            return None

    async def _call_in_thread(self, func, *args, **kwargs):
        loop = asyncio.get_running_loop()
        done = loop.create_future()

        def _resolve_result(value):
            if not done.done():
                done.set_result(value)

        def _resolve_error(exc: Exception):
            if not done.done():
                done.set_exception(exc)

        def _runner():
            try:
                value = func(*args, **kwargs)
            except Exception as exc:
                loop.call_soon_threadsafe(_resolve_error, exc)
                return
            loop.call_soon_threadsafe(_resolve_result, value)

        thread = threading.Thread(target=_runner, daemon=True)
        thread.start()
        return await done

    def _extract_tweets_and_cursor(self, data: dict[str, Any]) -> Tuple[list[TweetRecord], Optional[str]]:
        tweets: list[TweetRecord] = []
        cursor: Optional[str] = None

        instructions = (
            data.get("data", {})
            .get("search_by_raw_query", {})
            .get("search_timeline", {})
            .get("timeline", {})
            .get("instructions", [])
        )

        for instruction in instructions:
            entries = []
            if isinstance(instruction, dict):
                entries.extend(instruction.get("entries", []) or [])
                entry_obj = instruction.get("entry")
                if isinstance(entry_obj, dict):
                    entries.append(entry_obj)

            for entry in entries:
                if not isinstance(entry, dict):
                    continue

                entry_id = str(entry.get("entryId") or "")
                content = entry.get("content", {}) if isinstance(entry.get("content"), dict) else {}

                if "cursor-bottom" in entry_id or entry_id.startswith("cursor-"):
                    value = content.get("value")
                    if isinstance(value, str) and value:
                        cursor = value

                if not entry_id.startswith("tweet-"):
                    continue

                item_content = content.get("itemContent", {}) if isinstance(content.get("itemContent"), dict) else {}
                tweet_result_raw = (
                    item_content.get("tweet_results", {})
                    .get("result", {})
                )
                if not isinstance(tweet_result_raw, dict):
                    continue

                tweet_result = tweet_result_raw
                if "tweet" in tweet_result_raw and isinstance(tweet_result_raw.get("tweet"), dict):
                    tweet_result = tweet_result_raw["tweet"]

                legacy = tweet_result.get("legacy", {}) if isinstance(tweet_result.get("legacy"), dict) else {}
                user_result = (
                    tweet_result.get("core", {})
                    .get("user_results", {})
                    .get("result", {})
                )
                user_legacy = user_result.get("legacy", {}) if isinstance(user_result, dict) else {}

                screen_name = user_legacy.get("screen_name") if isinstance(user_legacy, dict) else None
                user_name = user_legacy.get("name") if isinstance(user_legacy, dict) else None

                tweet_id = (
                    legacy.get("id_str")
                    or tweet_result.get("rest_id")
                    or entry_id.replace("tweet-", "")
                )

                note_text = (
                    tweet_result.get("note_tweet", {})
                    .get("note_tweet_results", {})
                    .get("result", {})
                    .get("text")
                )
                text = note_text or legacy.get("full_text") or ""

                media_urls: list[str] = []
                for media in (legacy.get("extended_entities", {}) or {}).get("media", []) or []:
                    if not isinstance(media, dict):
                        continue
                    url = media.get("media_url_https")
                    if isinstance(url, str) and url:
                        media_urls.append(url)

                tweet_url = None
                if screen_name and tweet_id:
                    tweet_url = f"https://x.com/{screen_name}/status/{tweet_id}"

                tweets.append(
                    TweetRecord(
                        tweet_id=str(tweet_id),
                        user=TweetUser(screen_name=screen_name, name=user_name),
                        timestamp=legacy.get("created_at"),
                        text=text,
                        comments=self._safe_int(legacy.get("reply_count")),
                        likes=self._safe_int(legacy.get("favorite_count")),
                        retweets=self._safe_int(legacy.get("retweet_count")),
                        media=TweetMedia(image_links=media_urls),
                        tweet_url=tweet_url,
                        raw=tweet_result_raw,
                    )
                )

        return tweets, cursor

    def _extract_profile_tweets_and_cursor(self, data: dict[str, Any]) -> Tuple[list[TweetRecord], Optional[str]]:
        tweets: list[TweetRecord] = []
        cursor: Optional[str] = None
        instructions = self._extract_profile_timeline_instructions(data)

        for instruction in instructions:
            entries: list[dict[str, Any]] = []
            if isinstance(instruction, dict):
                instruction_entries = instruction.get("entries")
                if isinstance(instruction_entries, list):
                    entries.extend(item for item in instruction_entries if isinstance(item, dict))
                instruction_entry = instruction.get("entry")
                if isinstance(instruction_entry, dict):
                    entries.append(instruction_entry)

            for entry in entries:
                entry_id = str(entry.get("entryId") or "")
                content = entry.get("content", {}) if isinstance(entry.get("content"), dict) else {}
                cursor_value = content.get("value")
                cursor_type = str(content.get("cursorType") or "").strip().lower()
                if cursor_value and isinstance(cursor_value, str):
                    if entry_id.startswith("cursor-bottom-") or cursor_type == "bottom":
                        cursor = cursor_value
                    elif cursor is None and (entry_id.startswith("cursor-") or cursor_type):
                        cursor = cursor_value

                if not entry_id.startswith("tweet-"):
                    continue

                item_content = content.get("itemContent", {}) if isinstance(content.get("itemContent"), dict) else {}
                tweet_result_raw = (
                    item_content.get("tweet_results", {})
                    .get("result", {})
                )
                if not isinstance(tweet_result_raw, dict):
                    continue

                tweet_result = tweet_result_raw
                if "tweet" in tweet_result_raw and isinstance(tweet_result_raw.get("tweet"), dict):
                    tweet_result = tweet_result_raw["tweet"]

                legacy = tweet_result.get("legacy", {}) if isinstance(tweet_result.get("legacy"), dict) else {}
                user_result = (
                    tweet_result.get("core", {})
                    .get("user_results", {})
                    .get("result", {})
                )
                user_legacy = user_result.get("legacy", {}) if isinstance(user_result, dict) else {}

                screen_name = user_legacy.get("screen_name") if isinstance(user_legacy, dict) else None
                user_name = user_legacy.get("name") if isinstance(user_legacy, dict) else None

                tweet_id = (
                    legacy.get("id_str")
                    or tweet_result.get("rest_id")
                    or entry_id.replace("tweet-", "")
                )

                note_text = (
                    tweet_result.get("note_tweet", {})
                    .get("note_tweet_results", {})
                    .get("result", {})
                    .get("text")
                )
                text = note_text or legacy.get("full_text") or ""

                media_urls: list[str] = []
                for media in (legacy.get("extended_entities", {}) or {}).get("media", []) or []:
                    if not isinstance(media, dict):
                        continue
                    url = media.get("media_url_https")
                    if isinstance(url, str) and url:
                        media_urls.append(url)

                tweet_url = None
                if screen_name and tweet_id:
                    tweet_url = f"https://x.com/{screen_name}/status/{tweet_id}"

                tweets.append(
                    TweetRecord(
                        tweet_id=str(tweet_id),
                        user=TweetUser(screen_name=screen_name, name=user_name),
                        timestamp=legacy.get("created_at"),
                        text=text,
                        comments=self._safe_int(legacy.get("reply_count")),
                        likes=self._safe_int(legacy.get("favorite_count")),
                        retweets=self._safe_int(legacy.get("retweet_count")),
                        media=TweetMedia(image_links=media_urls),
                        tweet_url=tweet_url,
                        raw=tweet_result_raw,
                    )
                )

        return tweets, cursor

    def _extract_follows_users_and_cursor(self, data: dict[str, Any]) -> Tuple[list[dict[str, Any]], Optional[str]]:
        users: list[dict[str, Any]] = []
        cursor: Optional[str] = None
        instructions = self._extract_profile_timeline_instructions(data)

        for instruction in instructions:
            entries: list[dict[str, Any]] = []
            if isinstance(instruction, dict):
                instruction_entries = instruction.get("entries")
                if isinstance(instruction_entries, list):
                    entries.extend(item for item in instruction_entries if isinstance(item, dict))
                instruction_entry = instruction.get("entry")
                if isinstance(instruction_entry, dict):
                    entries.append(instruction_entry)

            for entry in entries:
                entry_id = str(entry.get("entryId") or "")
                content = entry.get("content", {}) if isinstance(entry.get("content"), dict) else {}
                cursor_value = content.get("value")
                cursor_type = str(content.get("cursorType") or "").strip().lower()
                if cursor_value and isinstance(cursor_value, str):
                    if entry_id.startswith("cursor-bottom-") or cursor_type == "bottom":
                        cursor = cursor_value
                    elif cursor is None and (entry_id.startswith("cursor-") or cursor_type):
                        cursor = cursor_value

                for user_result in self._extract_follow_user_results_from_entry(entry):
                    users.append(user_result)

        return users, cursor

    def _extract_follow_user_results_from_entry(self, entry: dict[str, Any]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if not isinstance(entry, dict):
            return out

        content = entry.get("content")
        if not isinstance(content, dict):
            return out

        def _append_from_item(item: Any) -> None:
            if not isinstance(item, dict):
                return
            item_content = item.get("itemContent") if isinstance(item.get("itemContent"), dict) else item
            user_result = (
                item_content.get("user_results", {})
                .get("result", {})
            )
            if isinstance(user_result, dict) and user_result:
                out.append(user_result)

        _append_from_item(content.get("itemContent"))
        _append_from_item((content.get("item") or {}).get("itemContent") if isinstance(content.get("item"), dict) else None)

        items = content.get("items")
        if isinstance(items, list):
            for node in items:
                if not isinstance(node, dict):
                    continue
                item_obj = node.get("item") if isinstance(node.get("item"), dict) else node
                if isinstance(item_obj, dict):
                    _append_from_item(item_obj.get("itemContent"))
                _append_from_item(node.get("itemContent"))

        return out

    @staticmethod
    def _extract_profile_timeline_instructions(data: dict[str, Any]) -> list[dict[str, Any]]:
        instructions = (
            data.get("data", {})
            .get("user", {})
            .get("result", {})
            .get("timeline", {})
            .get("timeline", {})
            .get("instructions", [])
        )
        if isinstance(instructions, list):
            return instructions
        return []

    @staticmethod
    def _tweet_record_id(tweet: Any) -> Optional[str]:
        if tweet is None:
            return None
        if isinstance(tweet, dict):
            value = tweet.get("tweet_id") or tweet.get("id")
            if value:
                return str(value)
            return None
        value = getattr(tweet, "tweet_id", None)
        if value:
            return str(value)
        return None

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0
