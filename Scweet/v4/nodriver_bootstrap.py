from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, Mapping, Optional


logger = logging.getLogger(__name__)


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _cookies_list_to_dict(cookies: Any) -> dict[str, str]:
    if isinstance(cookies, dict):
        out: dict[str, str] = {}
        for key, value in cookies.items():
            name = _as_str(key)
            cookie_value = _as_str(value)
            if name and cookie_value is not None:
                out[name] = cookie_value
        return out

    if isinstance(cookies, list):
        out: dict[str, str] = {}
        for item in cookies:
            if not isinstance(item, dict):
                continue
            name = _as_str(item.get("name"))
            value = _as_str(item.get("value"))
            if name and value is not None:
                out[name] = value
        return out

    return {}


async def abootstrap_cookies_from_credentials(
    account: Mapping[str, Any],
    *,
    proxy: Any = None,
    user_agent: Optional[str] = None,
    headless: bool = True,
    disable_images: bool = False,
    code_callback: Optional[Callable[[str, str], Awaitable[str]]] = None,
    timeout_s: int = 180,
) -> Optional[dict[str, str]]:
    """Login via nodriver and extract cookies.

    This is isolated from scraping: it only performs a login flow and returns cookies
    suitable for `normalize_account_record` (dict of cookie name -> value).
    """

    username = _as_str(account.get("username"))
    password = _as_str(account.get("password"))
    email = _as_str(account.get("email")) or _as_str(account.get("email_address"))
    email_password = _as_str(account.get("email_password"))

    if not password:
        logger.warning("Nodriver bootstrap skipped: missing password username=%s", username or "<unknown>")
        return None

    # Legacy login flow expects an email-like identifier for the first step.
    identifier = email or username
    if not identifier:
        logger.warning("Nodriver bootstrap skipped: missing email/username identifier")
        return None

    from .nodriver_login import alogin_and_get_cookies

    cookies_dict = await alogin_and_get_cookies(
        account,
        proxy=proxy,
        user_agent=user_agent,
        headless=bool(headless),
        disable_images=bool(disable_images),
        code_callback=code_callback,
        timeout_s=int(timeout_s),
    )
    if not cookies_dict:
        logger.warning("Nodriver bootstrap failed username=%s", username or "<unknown>")
        return None

    logger.info(
        "Nodriver bootstrap success username=%s cookie_count=%s has_ct0=%s",
        username or "<unknown>",
        len(cookies_dict),
        bool(_as_str(cookies_dict.get("ct0"))),
    )
    return cookies_dict


def bootstrap_cookies_from_credentials(
    account: Mapping[str, Any],
    *,
    proxy: Any = None,
    user_agent: Optional[str] = None,
    headless: bool = True,
    disable_images: bool = False,
    code_callback: Optional[Callable[[str, str], Awaitable[str]]] = None,
    timeout_s: int = 180,
) -> Optional[dict[str, str]]:
    """Synchronous wrapper for nodriver credential bootstrap.

    `import_accounts_to_db` is currently synchronous; this wrapper makes it safe
    to use in that code path.
    """

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            abootstrap_cookies_from_credentials(
                account,
                proxy=proxy,
                user_agent=user_agent,
                headless=headless,
                disable_images=disable_images,
                code_callback=code_callback,
                timeout_s=timeout_s,
            )
        )
    raise RuntimeError(
        "bootstrap_cookies_from_credentials() cannot run inside an active event loop; "
        "use abootstrap_cookies_from_credentials() instead."
    )
