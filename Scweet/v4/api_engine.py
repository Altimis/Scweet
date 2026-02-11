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
from .models import ProfileRequest, SearchRequest, SearchResult, TweetMedia, TweetRecord, TweetUser
from .query import build_effective_search_query, normalize_search_input

JSON_DECODE_STATUS = 598
NETWORK_ERROR_STATUS = 599
HTTP_MODE_AUTO = "auto"
HTTP_MODE_ASYNC = "async"
HTTP_MODE_SYNC = "sync"
DEFAULT_USER_LOOKUP_QUERY_ID = "-oaLodhGbbnzJBACb1kk2Q"
DEFAULT_USER_LOOKUP_ENDPOINT = "https://x.com/i/api/graphql/{query_id}/UserByScreenName"
USER_LOOKUP_OPERATION = "user_lookup_screen_name"
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

    async def get_profiles(self, request):
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

    async def get_follows(self, request):
        return {
            "follows": [],
            "status_code": 501,
            "detail": "Not implemented yet",
            "request": request,
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

    def _map_user_result_to_profile_record(
        self,
        user_result: dict[str, Any],
        *,
        target: dict[str, str],
        username: str,
    ) -> dict[str, Any]:
        legacy = user_result.get("legacy") if isinstance(user_result.get("legacy"), dict) else {}
        rest_id = str(
            user_result.get("rest_id")
            or user_result.get("id")
            or legacy.get("id_str")
            or ""
        ).strip()
        screen_name = str(legacy.get("screen_name") or username or "").strip()
        return {
            "input": {
                "raw": target.get("raw"),
                "source": target.get("source"),
            },
            "user_id": rest_id or None,
            "username": screen_name or None,
            "name": legacy.get("name"),
            "description": legacy.get("description"),
            "location": legacy.get("location"),
            "created_at": legacy.get("created_at"),
            "followers_count": self._as_int(legacy.get("followers_count")),
            "following_count": self._as_int(legacy.get("friends_count")),
            "statuses_count": self._as_int(legacy.get("statuses_count")),
            "favourites_count": self._as_int(legacy.get("favourites_count")),
            "media_count": self._as_int(legacy.get("media_count")),
            "listed_count": self._as_int(legacy.get("listed_count")),
            "verified": bool(legacy.get("verified", False)),
            "blue_verified": bool(user_result.get("is_blue_verified", False)),
            "protected": bool(legacy.get("protected", False)),
            "profile_image_url": legacy.get("profile_image_url_https") or legacy.get("profile_image_url"),
            "profile_banner_url": legacy.get("profile_banner_url"),
            "url": legacy.get("url"),
            "raw": user_result,
        }

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

            logger.info("API request endpoint=%s status=%s account=%s", url, status, account_label)
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

    @staticmethod
    def _safe_int(value: Any) -> int:
        try:
            return int(value)
        except Exception:
            return 0
