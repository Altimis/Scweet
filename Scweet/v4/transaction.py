from __future__ import annotations

import logging
import os
import time
from typing import Any, Optional

from bs4 import BeautifulSoup

from .account_session import DEFAULT_HTTP_TIMEOUT, DEFAULT_IMPERSONATE, DEFAULT_USER_AGENT
from .http_utils import apply_proxies_to_session, is_curl_cffi_session, normalize_http_proxies

logger = logging.getLogger(__name__)


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


class TransactionIdProvider:
    def __init__(
        self,
        *,
        enabled: bool = True,
        refresh_ttl_s: int = 15 * 60,
        home_url: str = "https://x.com",
        session_factory=None,
        user_agent: Optional[str] = None,
        proxy: Any = None,
        prefer_curl_cffi: bool = True,
        impersonate: str = DEFAULT_IMPERSONATE,
        timeout=DEFAULT_HTTP_TIMEOUT,
    ):
        self.enabled = bool(enabled)
        self.refresh_ttl_s = max(60, int(refresh_ttl_s))
        self.home_url = home_url
        self.prefer_curl_cffi = bool(prefer_curl_cffi)
        self.impersonate = impersonate
        self.timeout = timeout
        self.proxy = proxy
        self._http_proxies = normalize_http_proxies(proxy)
        self.session_factory = session_factory or self._build_default_session_factory()
        self.user_agent_override = _as_str(user_agent)

        self._static_tx_id = os.getenv("SCWEET_X_CLIENT_TRANSACTION_ID")
        self._client_transaction = None
        self._client_ready_at = 0.0
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
                    try:
                        return CurlSession(**kwargs)
                    except TypeError:
                        kwargs.pop("proxies", None)
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
            from x_client_transaction.utils import get_ondemand_file_url, handle_x_migration  # noqa: F401

            self._deps_available = True
        except Exception:
            self._deps_available = False
            logger.info("x_client_transaction not available; X-Client-Transaction-Id header disabled")
        return self._deps_available

    def _build_client_transaction(self):
        if not self._ensure_dependencies():
            return None
        from x_client_transaction import ClientTransaction
        from x_client_transaction.utils import get_ondemand_file_url, handle_x_migration

        session = None
        try:
            session = self.session_factory()
            if session is None:
                return None

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

            # Keep actor parity: run migration handling before extracting ondemand.js URL.
            home_page = handle_x_migration(session=session)

            ondemand_url = get_ondemand_file_url(response=home_page)
            if not ondemand_url:
                logger.warning("Transaction-id bootstrap failed: ondemand URL not found")
                return None

            od_response = session.get(ondemand_url, timeout=20, allow_redirects=True)
            if int(getattr(od_response, "status_code", 0) or 0) >= 400:
                logger.warning(
                    "Transaction-id bootstrap failed: ondemand status=%s",
                    getattr(od_response, "status_code", None),
                )
                return None

            od_html = BeautifulSoup(str(getattr(od_response, "text", "") or ""), "html.parser")
            client_transaction = ClientTransaction(
                home_page_response=home_page,
                ondemand_file_response=od_html,
            )
            logger.info("Transaction-id bootstrap success")
            return client_transaction
        except Exception as exc:
            logger.warning("Transaction-id bootstrap exception: %s", str(exc))
            return None
        finally:
            if session is not None and hasattr(session, "close"):
                try:
                    session.close()
                except Exception:
                    pass

    def generate(self, *, method: str, path: str) -> Optional[str]:
        if self._static_tx_id:
            return str(self._static_tx_id)
        if not self.enabled:
            return None

        now_ts = time.time()
        expired = (now_ts - self._client_ready_at) >= self.refresh_ttl_s
        if self._client_transaction is None or expired:
            self._client_transaction = self._build_client_transaction()
            self._client_ready_at = now_ts

        if self._client_transaction is None:
            return None

        try:
            return self._client_transaction.generate_transaction_id(method=method, path=path)
        except Exception as exc:
            logger.warning("Transaction-id generation failed: %s", str(exc))
            self._client_transaction = None
            self._client_ready_at = 0.0
            return None
