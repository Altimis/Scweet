from __future__ import annotations

import asyncio
import inspect
import json
import logging
import threading
from typing import Any, Optional, Tuple
from urllib.parse import urlparse

from .models import SearchRequest, SearchResult, TweetMedia, TweetRecord, TweetUser

JSON_DECODE_STATUS = 598
NETWORK_ERROR_STATUS = 599
HTTP_MODE_AUTO = "auto"
HTTP_MODE_ASYNC = "async"
HTTP_MODE_SYNC = "sync"
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
        return {
            "profiles": {},
            "status_code": 501,
            "detail": "Not implemented in Phase 4",
            "request": request,
        }

    async def get_follows(self, request):
        return {
            "follows": [],
            "status_code": 501,
            "detail": "Not implemented in Phase 4",
            "request": request,
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

    def _build_graphql_params(
        self,
        request: SearchRequest,
        cursor: Optional[str],
        manifest,
        *,
        runtime_hints: Optional[dict[str, Optional[int]]] = None,
    ) -> dict[str, str]:
        variables = self._build_variables(request, cursor, runtime_hints=runtime_hints)
        return {
            "variables": json.dumps(variables, separators=(",", ":")),
            "features": json.dumps(manifest.features or {}, separators=(",", ":")),
        }

    def _build_variables(
        self,
        request: SearchRequest,
        cursor: Optional[str],
        *,
        runtime_hints: Optional[dict[str, Optional[int]]] = None,
    ) -> dict[str, Any]:
        query_parts: list[str] = []

        words = [word.strip() for word in (request.words or []) if str(word).strip()]
        if words:
            if len(words) == 1:
                query_parts.append(f"({words[0]})")
            else:
                query_parts.append("(" + " OR ".join(words) + ")")

        if request.from_account:
            query_parts.append(f"(from:{request.from_account})")
        if request.to_account:
            query_parts.append(f"(to:{request.to_account})")
        if request.mention_account:
            mention = request.mention_account.lstrip("@")
            query_parts.append(f"(@{mention})")
        if request.hashtag:
            hashtag = request.hashtag if request.hashtag.startswith("#") else f"#{request.hashtag}"
            query_parts.append(f"({hashtag})")
        if request.lang:
            query_parts.append(f"lang:{request.lang}")
        if request.since:
            query_parts.append(f"since:{request.since}")
        if request.until:
            query_parts.append(f"until:{request.until}")

        if not query_parts:
            query_parts.append("from:elonmusk")

        display = (request.display_type or "Latest").strip().lower()
        product = "Latest" if display in {"recent", "latest"} else "Top"

        count = self._resolve_page_size(runtime_hints=runtime_hints)

        variables = {
            "rawQuery": " ".join(query_parts).strip(),
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
            logger.warning("API request endpoint=%s status=%s account=%s detail=%s", url, NETWORK_ERROR_STATUS, account_label, str(exc))
            return None, NETWORK_ERROR_STATUS, {}, ""
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
