from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Tuple

from .exceptions import AccountSessionAuthError, AccountSessionRuntimeError, AccountSessionTransientError
from .http_utils import apply_proxies_to_session, is_curl_cffi_session, normalize_http_proxies

# Public X web bearer token historically used by web GraphQL calls.
# Can be overridden at runtime via SCWEET_X_BEARER_TOKEN.
DEFAULT_X_BEARER_TOKEN = (
    os.getenv("SCWEET_X_BEARER_TOKEN")
    or os.getenv("X_BEARER")
    or "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)
DEFAULT_IMPERSONATE = os.getenv("SCWEET_HTTP_IMPERSONATE", "chrome120")
DEFAULT_HTTP_TIMEOUT = (10, 30)
HTTP_MODE_AUTO = "auto"
HTTP_MODE_ASYNC = "async"
HTTP_MODE_SYNC = "sync"

logger = logging.getLogger(__name__)


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _normalize_cookies_payload(payload: Any) -> Any:
    if payload is None:
        return None

    if hasattr(payload, "get_dict"):
        try:
            return payload.get_dict()
        except Exception:
            pass

    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return None
        try:
            decoded = json.loads(stripped)
        except Exception:
            return None
        return _normalize_cookies_payload(decoded)

    if isinstance(payload, (dict, list)):
        return payload

    return None


def _normalize_proxy_payload(payload: Any) -> Any:
    if payload is None:
        return None
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return None
        if stripped.startswith("{") or stripped.startswith("[") or stripped.startswith('"'):
            try:
                decoded = json.loads(stripped)
            except Exception:
                return stripped
            return decoded
        return stripped
    return payload


def _cookies_to_dict(cookies_payload: Any) -> dict[str, str]:
    if isinstance(cookies_payload, dict):
        out: dict[str, str] = {}
        for key, value in cookies_payload.items():
            name = _as_str(key)
            cookie_value = _as_str(value)
            if name and cookie_value is not None:
                out[name] = cookie_value
        return out

    if isinstance(cookies_payload, list):
        out: dict[str, str] = {}
        for item in cookies_payload:
            if not isinstance(item, dict):
                continue
            name = _as_str(item.get("name"))
            value = _as_str(item.get("value"))
            if name and value is not None:
                out[name] = value
        return out

    return {}


def _record_get(record: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


@dataclass(frozen=True)
class AccountAuthMaterial:
    auth_token: str
    csrf_token: str
    bearer_token: str
    cookies: dict[str, str]


def prepare_account_auth_material(
    account: Mapping[str, Any],
    *,
    default_bearer_token: Optional[str] = DEFAULT_X_BEARER_TOKEN,
) -> Tuple[Optional[AccountAuthMaterial], Optional[str]]:
    data = dict(account or {})
    cookies_payload = _normalize_cookies_payload(
        _record_get(data, "cookies_json", "cookies", "cookie_jar", "cookieJar")
    )
    cookies = _cookies_to_dict(cookies_payload)

    auth_token = _as_str(_record_get(data, "auth_token", "authToken", "token")) or _as_str(cookies.get("auth_token"))
    csrf_token = _as_str(_record_get(data, "csrf", "csrf_token", "ct0")) or _as_str(cookies.get("ct0"))
    bearer_token = _as_str(_record_get(data, "bearer", "bearer_token", "authorization")) or _as_str(
        default_bearer_token
    )
    if bearer_token and bearer_token.lower().startswith("bearer "):
        bearer_token = bearer_token.split(" ", 1)[1].strip()

    if not auth_token:
        return None, "missing_auth_token"
    if not csrf_token:
        return None, "missing_csrf"
    if not bearer_token:
        return None, "missing_bearer"

    normalized_cookies = dict(cookies)
    normalized_cookies["auth_token"] = auth_token
    normalized_cookies["ct0"] = csrf_token

    return (
        AccountAuthMaterial(
            auth_token=auth_token,
            csrf_token=csrf_token,
            bearer_token=bearer_token,
            cookies=normalized_cookies,
        ),
        None,
    )


class AccountSessionBuilder:
    def __init__(
        self,
        *,
        session_factory=None,
        api_http_mode: str = HTTP_MODE_AUTO,
        prefer_curl_cffi: bool = True,
        impersonate: str = DEFAULT_IMPERSONATE,
        timeout=DEFAULT_HTTP_TIMEOUT,
        default_bearer_token: Optional[str] = DEFAULT_X_BEARER_TOKEN,
        user_agent: Optional[str] = None,
        client_language: str = "en",
        referer: str = "https://x.com/",
        proxy: Any = None,
    ):
        self.prefer_curl_cffi = bool(prefer_curl_cffi)
        configured_mode = str(api_http_mode or HTTP_MODE_AUTO).strip().lower()
        if configured_mode not in {HTTP_MODE_AUTO, HTTP_MODE_ASYNC, HTTP_MODE_SYNC}:
            configured_mode = HTTP_MODE_AUTO
        self.api_http_mode = configured_mode
        self.impersonate = impersonate
        self.timeout = timeout
        self.proxy = proxy
        self._http_proxies = normalize_http_proxies(proxy)
        self.session_factory = session_factory or self._build_default_session_factory()
        self.default_bearer_token = default_bearer_token
        self.user_agent_override = _as_str(user_agent)
        self.client_language = client_language
        self.referer = referer

    def _build_default_session_factory(self):
        if self.api_http_mode != HTTP_MODE_SYNC:
            async_factory = self._build_curl_async_factory()
            if async_factory is not None:
                return async_factory
            if self.api_http_mode == HTTP_MODE_ASYNC:
                logger.info(
                    "Account session async mode requested but curl_cffi.AsyncSession is unavailable; "
                    "falling back to sync session"
                )
            else:
                logger.info("Account session auto mode could not resolve async session; falling back to sync session")

        sync_factory = self._build_sync_factory()
        if sync_factory is not None:
            return sync_factory
        raise RuntimeError("curl_cffi is required for API HTTP sessions")

    def _build_curl_async_factory(self):
        if not self.prefer_curl_cffi:
            return None
        try:
            from curl_cffi.requests import AsyncSession as CurlAsyncSession

            def _factory():
                kwargs = {"impersonate": self.impersonate, "timeout": self.timeout}
                if self._http_proxies:
                    kwargs["proxies"] = self._http_proxies
                try:
                    return CurlAsyncSession(**kwargs)
                except TypeError:
                    # Older curl_cffi versions may not accept proxies at init.
                    kwargs.pop("proxies", None)
                    return CurlAsyncSession(**kwargs)

            return _factory
        except Exception:
            return None

    def _build_sync_factory(self):
        if self.prefer_curl_cffi:
            try:
                from curl_cffi.requests import Session as CurlSession

                def _factory():
                    kwargs = {"impersonate": self.impersonate, "timeout": self.timeout}
                    if self._http_proxies:
                        kwargs["proxies"] = self._http_proxies
                    try:
                        return CurlSession(**kwargs)
                    except TypeError:
                        kwargs.pop("proxies", None)
                        return CurlSession(**kwargs)

                return _factory
            except Exception:
                logger.info("curl_cffi sync Session unavailable")
        return None

    def build(self, account: Mapping[str, Any]) -> tuple[Any, dict[str, Any]]:
        material, reason = prepare_account_auth_material(account, default_bearer_token=self.default_bearer_token)
        if material is None:
            raise AccountSessionAuthError(code="missing_auth_material", reason=reason or "missing_auth_material")

        try:
            session = self.session_factory()
        except Exception as exc:
            raise AccountSessionTransientError(
                code="session_factory_error",
                reason=exc.__class__.__name__,
            ) from exc
        if session is None:
            raise AccountSessionRuntimeError(
                code="session_factory_returned_none",
                reason="session_factory_returned_none",
            )

        try:
            account_proxy = _normalize_proxy_payload(_record_get(account, "proxy_json", "proxy"))
            account_proxies = normalize_http_proxies(account_proxy)
            effective_proxies = account_proxies if account_proxies is not None else self._http_proxies
            apply_proxies_to_session(session, effective_proxies)
            self._apply_cookies(session, material.cookies)
            self._apply_headers(session, material)
        except Exception as exc:
            close_fn = getattr(session, "close", None)
            if callable(close_fn):
                try:
                    close_fn()
                except Exception:
                    pass
            raise AccountSessionRuntimeError(
                code="session_init_failed",
                reason=exc.__class__.__name__,
            ) from exc

        metadata = {
            "account_id": account.get("id"),
            "username": account.get("username"),
            "cookie_count": len(material.cookies),
            "has_auth_token": True,
            "has_csrf": True,
            "has_bearer": True,
            "session_mode": "async" if inspect.iscoroutinefunction(getattr(session, "get", None)) else "sync",
        }
        return session, metadata

    @staticmethod
    def _apply_cookies(session: Any, cookies: dict[str, str]) -> None:
        jar = getattr(session, "cookies", None)
        if jar is None:
            return
        setter = getattr(jar, "set", None)
        if setter is None:
            updater = getattr(jar, "update", None)
            if callable(updater):
                updater(cookies)
            return
        for name, value in cookies.items():
            try:
                setter(name, value, domain=".x.com")
            except Exception:
                try:
                    setter(name, value)
                except Exception:
                    continue

    def _apply_headers(self, session: Any, material: AccountAuthMaterial) -> None:
        headers = {
            "Authorization": f"Bearer {material.bearer_token}",
            "X-Csrf-Token": material.csrf_token,
            "X-Twitter-Auth-Type": "OAuth2Session",
            "X-Twitter-Active-User": "yes",
            "X-Twitter-Client-Language": self.client_language,
            "Referer": self.referer,
        }

        # curl_cffi sets its own UA consistent with impersonation; overriding it can cause fingerprint mismatches.
        # For non-curl clients, we provide a browser-like UA by default.
        if self.user_agent_override is not None:
            headers["User-Agent"] = self.user_agent_override
        elif not is_curl_cffi_session(session):
            headers["User-Agent"] = DEFAULT_USER_AGENT

        current_headers = getattr(session, "headers", None)
        if current_headers is None:
            setattr(session, "headers", dict(headers))
            return
        updater = getattr(current_headers, "update", None)
        if callable(updater):
            updater(headers)
            return
        setattr(session, "headers", dict(headers))

    async def close(self, session: Any) -> None:
        close_fn = getattr(session, "close", None)
        if close_fn is None:
            return
        if inspect.iscoroutinefunction(close_fn):
            await close_fn()
            return
        maybe_awaitable = close_fn()
        if inspect.isawaitable(maybe_awaitable):
            await maybe_awaitable
            return
        if maybe_awaitable is not None:
            await asyncio.sleep(0)
