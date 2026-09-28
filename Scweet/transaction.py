from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from bs4 import BeautifulSoup

from .account_session import DEFAULT_HTTP_TIMEOUT, DEFAULT_IMPERSONATE, DEFAULT_USER_AGENT
from .http_utils import (
    X_PAGE_FULL,
    apply_proxies_to_session,
    classify_x_page,
    describe_rejected_x_page,
    is_curl_cffi_session,
    normalize_http_proxies,
)

logger = logging.getLogger(__name__)


from .utils import as_str as _as_str


def _extract_ondemand_url(html: str) -> str | None:
    marker = '"ondemand.s"'
    pos = html.find(marker)
    if pos == -1:
        return None
    comma = html.rfind(",", 0, pos)
    if comma == -1:
        return None
    colon = html.find(":", comma)
    if colon == -1:
        return None
    chunk_key = html[comma + 1 : colon].strip().strip('"').strip("'")
    search_start = pos + len(marker)
    needle = chunk_key + ':"'
    hash_start = html.find(needle, search_start)
    if hash_start == -1:
        return None
    hash_start += len(needle)
    hash_end = html.find('"', hash_start)
    if hash_end == -1:
        return None
    ondemand_hash = html[hash_start:hash_end]
    if not ondemand_hash or not all(c in "0123456789abcdef" for c in ondemand_hash):
        return None
    return f"https://abs.twimg.com/responsive-web/client-web/ondemand.s.{ondemand_hash}a.js"


class TransactionIdProvider:
    def __init__(
        self,
        *,
        enabled: bool = True,
        refresh_ttl_s: int = 6 * 60 * 60,
        # Not "https://x.com": that URL answers a 32 KB shell that holds no ondemand.s marker, so the
        # bootstrap finds no file, the header is dropped, and X answers 404 for every GraphQL request.
        # /home carries the marker only for a request with the cookies of an account that X accepts.
        home_url: str = "https://x.com/home",
        session_factory=None,
        user_agent: Optional[str] = None,
        proxy: Any = None,
        prefer_curl_cffi: bool = True,
        impersonate: str = DEFAULT_IMPERSONATE,
        timeout=DEFAULT_HTTP_TIMEOUT,
        cookies: Optional[dict] = None,
        init_attempts: int = 3,
        init_backoff_s: float = 1.5,
        cookie_sets: Optional[list[dict]] = None,
    ):
        self.enabled = bool(enabled)
        self.refresh_ttl_s = max(60, int(refresh_ttl_s))
        self.init_attempts = max(1, int(init_attempts))
        self.init_backoff_s = max(0.0, float(init_backoff_s))
        self.home_url = home_url
        self.prefer_curl_cffi = bool(prefer_curl_cffi)
        self.impersonate = impersonate
        self.timeout = timeout
        self.proxy = proxy
        # A {session} placeholder must carry a real token here too: a literal placeholder is not a valid
        # session name, and the provider answers 407 for the bootstrap of every account.
        from .account_session import fill_proxy_session_placeholder

        self._http_proxies = normalize_http_proxies(
            fill_proxy_session_placeholder(proxy, {"username": "manifest"})
        )
        # One entry for each account that can serve the bootstrap page: {"username": ..., "cookies": {...}}.
        # X serves the marker only to an accepted cookie, so a build tries the next account when one fails.
        self._cookie_sets: list[dict] = [
            dict(item) for item in (cookie_sets or []) if isinstance(item, dict) and item.get("cookies")
        ]
        if not self._cookie_sets and cookies:
            self._cookie_sets = [{"username": None, "cookies": dict(cookies)}]
        self._cookies = self._cookie_sets[0]["cookies"] if self._cookie_sets else cookies
        self.session_factory = session_factory or self._build_default_session_factory()
        self.user_agent_override = _as_str(user_agent)

        self._static_tx_id = os.getenv("SCWEET_X_CLIENT_TRANSACTION_ID")
        self._client_transaction = None
        self._client_ready_at = 0.0
        self._last_failure_at = 0.0
        self._deps_checked = False
        self._deps_available = False

        if self.enabled and not self._static_tx_id:
            self._ensure_dependencies()

    def _build_default_session_factory(self):
        if self.prefer_curl_cffi:
            try:
                from curl_cffi.requests import Session as CurlSession

                def _factory():
                    kwargs = {"impersonate": self.impersonate, "timeout": self.timeout}
                    if self._http_proxies:
                        kwargs["proxies"] = self._http_proxies
                    if self._cookies:
                        kwargs["cookies"] = self._cookies
                    try:
                        return CurlSession(**kwargs)
                    except TypeError:
                        kwargs.pop("proxies", None)
                        kwargs.pop("cookies", None)
                        return CurlSession(**kwargs)

                return _factory
            except Exception:
                logger.info("curl_cffi not available for transaction bootstrap; disabling transaction-id header")
        return lambda: None

    def _ensure_dependencies(self) -> bool:
        if self._deps_checked:
            return self._deps_available
        self._deps_checked = True
        try:
            from x_client_transaction import ClientTransaction  # noqa: F401
            from x_client_transaction.utils import handle_x_migration  # noqa: F401

            self._deps_available = True
        except Exception:
            self._deps_available = False
            logger.info("x_client_transaction not available; X-Client-Transaction-Id header disabled")
        return self._deps_available

    def _build_client_transaction(self):
        if not self._ensure_dependencies():
            return None
        if not self._cookie_sets:
            built, _kind = self._build_with_current_cookies()
            if built is None and _kind is not None:
                logger.warning("Transaction-id bootstrap failed: %s", describe_rejected_x_page(_kind))
            return built
        last_kind = None
        for index, item in enumerate(self._cookie_sets):
            self._cookies = item.get("cookies")
            built, kind = self._build_with_current_cookies()
            if built is not None:
                return built
            if kind is None:
                continue
            last_kind = kind
            if index + 1 < len(self._cookie_sets):
                logger.warning(
                    "Transaction-id bootstrap: X did not accept the cookies of account %s (page=%s); "
                    "trying the next account",
                    item.get("username") or "-",
                    kind,
                )
        if last_kind is not None:
            logger.warning("Transaction-id bootstrap failed: %s", describe_rejected_x_page(last_kind))
        return None

    def _build_with_current_cookies(self):
        """One build with ``self._cookies``. Returns ``(client_transaction, kind_of_rejected_page)``.

        The second item is ``None`` when the build succeeded or failed for another reason than the page.
        """
        from x_client_transaction import ClientTransaction
        from x_client_transaction.utils import handle_x_migration

        session = None
        try:
            session = self.session_factory()
            if session is None:
                return None, None

            headers = {
                "Referer": "https://x.com/",
                "Origin": "https://x.com",
                "X-Twitter-Active-User": "yes",
                "X-Twitter-Client-Language": "en",
            }
            if self.user_agent_override is not None:
                headers["User-Agent"] = self.user_agent_override
            elif not is_curl_cffi_session(session):
                headers["User-Agent"] = DEFAULT_USER_AGENT

            apply_proxies_to_session(session, self._http_proxies)
            session_headers = getattr(session, "headers", None)
            if session_headers is not None and hasattr(session_headers, "update"):
                session_headers.update(headers)

            home_page = handle_x_migration(session=session)

            ondemand_url = _extract_ondemand_url(str(home_page))
            page_kind = None
            if not ondemand_url:
                # handle_x_migration reads https://x.com, which answers a 32 KB shell with no
                # ondemand.s marker. self.home_url serves the full document to an accepted cookie.
                home_response = session.get(self.home_url, timeout=20, allow_redirects=True)
                home_text = str(getattr(home_response, "text", "") or "")
                ondemand_url = _extract_ondemand_url(home_text)
                if ondemand_url:
                    home_page = BeautifulSoup(home_text, "html.parser")
                else:
                    page_kind = classify_x_page(home_text, getattr(home_response, "url", None))
            if not ondemand_url:
                if page_kind is None or page_kind == X_PAGE_FULL:
                    page_kind = classify_x_page(str(home_page))
                logger.warning("Transaction-id bootstrap failed: ondemand URL not found (page=%s)", page_kind)
                return None, page_kind

            od_response = session.get(ondemand_url, timeout=20, allow_redirects=True)
            if int(getattr(od_response, "status_code", 0) or 0) >= 400:
                logger.warning(
                    "Transaction-id bootstrap failed: ondemand status=%s",
                    getattr(od_response, "status_code", None),
                )
                return None, None

            od_html = BeautifulSoup(str(getattr(od_response, "text", "") or ""), "html.parser")
            client_transaction = ClientTransaction(
                home_page_response=home_page,
                ondemand_file_response=od_html,
            )
            logger.info("Transaction-id bootstrap success")
            return client_transaction, None
        except Exception as exc:
            logger.warning("Transaction-id bootstrap exception: %s", str(exc))
            return None, None
        finally:
            if session is not None and hasattr(session, "close"):
                try:
                    session.close()
                except Exception:
                    pass

    def _rebuild_with_retries(self) -> None:
        # A failed build must never stamp the TTL: the old code did, so one bad
        # startup answered None for the next 6 hours while every request took a 404.
        now_ts = time.time()
        if (
            self._client_transaction is None
            and self._last_failure_at
            and (now_ts - self._last_failure_at) < self.init_backoff_s
        ):
            return
        for attempt in range(1, self.init_attempts + 1):
            built = self._build_client_transaction()
            if built is not None:
                self._client_transaction = built
                self._client_ready_at = time.time()
                self._last_failure_at = 0.0
                return
            if attempt < self.init_attempts:
                time.sleep(self.init_backoff_s * attempt)
        # A stale generator that works beats none, so a TTL rebuild keeps the old one.
        self._last_failure_at = time.time()
        if self._client_transaction is None:
            logger.warning(
                "Transaction-id build failed after %d attempts; the next request retries. "
                "A request without the x-client-transaction-id header answers 404.",
                self.init_attempts,
            )

    def refresh(self) -> bool:
        """Discard the generator and build a new one now. Returns the readiness."""
        if self._static_tx_id:
            return True
        if not self.enabled:
            return False
        self._client_transaction = None
        self._client_ready_at = 0.0
        self._last_failure_at = 0.0
        self._rebuild_with_retries()
        return self._client_transaction is not None

    def generate(self, *, method: str, path: str) -> Optional[str]:
        if self._static_tx_id:
            return str(self._static_tx_id)
        if not self.enabled:
            return None

        now_ts = time.time()
        expired = (now_ts - self._client_ready_at) >= self.refresh_ttl_s
        if self._client_transaction is None or expired:
            self._rebuild_with_retries()

        if self._client_transaction is None:
            return None

        try:
            return self._client_transaction.generate_transaction_id(method=method, path=path)
        except Exception as exc:
            logger.warning("Transaction-id generation failed: %s", str(exc))
            self._client_transaction = None
            self._client_ready_at = 0.0
            return None
