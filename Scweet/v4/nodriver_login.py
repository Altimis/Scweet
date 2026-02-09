from __future__ import annotations

import asyncio
import logging
import platform
from typing import Any, Awaitable, Callable, Mapping, Optional

logger = logging.getLogger(__name__)


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def _select_and_type(tab: Any, css: str, text: str, *, timeout_s: float) -> bool:
    try:
        el = await tab.select(css, timeout=timeout_s)
    except Exception:
        return False
    try:
        await el.send_keys(text)
    except Exception:
        return False
    return True


async def _click_first_text(tab: Any, labels: list[str], *, timeout_s: float) -> bool:
    for label in labels:
        if not label:
            continue
        try:
            el = await tab.find(label, best_match=True, timeout=timeout_s)
        except Exception:
            continue
        try:
            await el.click()
            return True
        except Exception:
            continue
    return False


async def _text_exists(tab: Any, labels: list[str], *, timeout_s: float) -> bool:
    for label in labels:
        if not label:
            continue
        try:
            await tab.find(label, timeout=timeout_s)
            return True
        except Exception:
            continue
    return False


async def _is_logged_in(tab: Any) -> bool:
    try:
        await tab.select("a[href='/home']")
        return True
    except Exception:
        return False


def _cookies_list_to_dict(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        out: dict[str, str] = {}
        for key, item in value.items():
            name = _as_str(key)
            cookie_value = _as_str(item)
            if name and cookie_value is not None:
                out[name] = cookie_value
        return out

    if isinstance(value, list):
        out: dict[str, str] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            name = _as_str(item.get("name"))
            cookie_value = _as_str(item.get("value"))
            if name and cookie_value is not None:
                out[name] = cookie_value
        return out

    return {}


async def alogin_and_get_cookies(
    account_record: Mapping[str, Any],
    *,
    proxy: Any = None,
    user_agent: Optional[str] = None,
    headless: bool = True,
    disable_images: bool = False,
    code_callback: Optional[Callable[[str, str], Awaitable[str]]] = None,
    timeout_s: int = 180,
) -> Optional[dict[str, str]]:
    """Login via nodriver and return cookies as a {name: value} mapping.

    This module is intentionally scoped to credential-based cookie bootstrap only.
    It performs no scraping and does not parse .env files.
    """

    async def _inner() -> Optional[dict[str, str]]:
        display = None
        driver = None
        tab = None

        username = _as_str(account_record.get("username"))
        password = _as_str(account_record.get("password"))
        email = _as_str(account_record.get("email")) or _as_str(account_record.get("email_address"))
        email_password = _as_str(account_record.get("email_password"))

        identifier = email or username
        if not password:
            logger.warning("Nodriver login skipped: missing password username=%s", username or "<unknown>")
            return None
        if not identifier:
            logger.warning("Nodriver login skipped: missing email/username identifier")
            return None

        try:
            if headless and platform.system() == "Linux":
                try:
                    from pyvirtualdisplay import Display  # type: ignore

                    display = Display(visible=0, size=(1024, 768))
                    display.start()
                    logger.info("Nodriver login: started virtual display for Linux headless mode")
                except Exception as exc:
                    logger.warning("Nodriver login: virtual display not available detail=%s", str(exc))

            try:
                import nodriver as uc  # type: ignore
            except Exception as exc:
                logger.warning("Nodriver login unavailable (missing dependency) detail=%s", str(exc))
                return None

            config = uc.Config()
            config.lang = "en-US"
            if headless and platform.system() in {"Windows", "Darwin"}:
                config.headless = True

            if isinstance(proxy, dict):
                host = _as_str(proxy.get("host"))
                port = _as_str(proxy.get("port"))
                if host and port:
                    config.add_argument(f"--proxy-server={host}:{port}")
            if user_agent:
                config.add_argument(f"--user-agent={user_agent}")
            if disable_images:
                config.add_argument("--blink-settings=imagesEnabled=false")

            driver = await uc.start(config)
            tab = await driver.get("draft:,")

            if isinstance(proxy, dict) and _as_str(proxy.get("username")) and _as_str(proxy.get("password")):
                proxy_user = _as_str(proxy.get("username")) or ""
                proxy_pass = _as_str(proxy.get("password")) or ""

                async def _auth_required(event: uc.cdp.fetch.AuthRequired):  # type: ignore[attr-defined]
                    asyncio.create_task(
                        tab.send(
                            uc.cdp.fetch.continue_with_auth(
                                request_id=event.request_id,
                                auth_challenge_response=uc.cdp.fetch.AuthChallengeResponse(
                                    response="ProvideCredentials",
                                    username=proxy_user,
                                    password=proxy_pass,
                                ),
                            )
                        )
                    )

                async def _request_paused(event: uc.cdp.fetch.RequestPaused):  # type: ignore[attr-defined]
                    asyncio.create_task(tab.send(uc.cdp.fetch.continue_request(request_id=event.request_id)))

                try:
                    tab.add_handler(uc.cdp.fetch.RequestPaused, _request_paused)
                    tab.add_handler(uc.cdp.fetch.AuthRequired, _auth_required)
                    await tab.send(uc.cdp.fetch.enable(handle_auth_requests=True))
                except Exception:
                    pass

            tab = await driver.get("https://x.com/login")
            await tab.sleep(2)

            ok = await _select_and_type(tab, "input[autocomplete=username]", identifier, timeout_s=20)
            if not ok:
                logger.warning("Nodriver login failed: could not type identifier")
                return None
            await tab.sleep(1)

            clicked = await _click_first_text(tab, ["Next", "Suivant"], timeout_s=10)
            if not clicked:
                logger.warning("Nodriver login failed: could not click Next")
                return None
            await tab.sleep(1)

            # Some flows ask for username/phone after the identifier step.
            needs_username = await _text_exists(
                tab,
                [
                    "Enter your phone number or username",
                    "Entrez votre adresse email ou votre nom d'utilisateur.",
                ],
                timeout_s=2,
            )
            if needs_username:
                await _select_and_type(
                    tab,
                    "input[data-testid=ocfEnterTextTextInput]",
                    username or identifier,
                    timeout_s=10,
                )
                await tab.sleep(1)
                await _click_first_text(tab, ["Next", "Suivant", "Login", "Se Connecter", "Se connecter"], timeout_s=10)
                await tab.sleep(1)

            ok = await _select_and_type(tab, "input[autocomplete=current-password]", password, timeout_s=20)
            if not ok:
                logger.warning("Nodriver login failed: could not type password")
                return None
            await tab.sleep(1)

            clicked = await _click_first_text(tab, ["Log in", "Login", "Se Connecter", "Se connecter"], timeout_s=10)
            if not clicked:
                logger.warning("Nodriver login failed: could not click Log in")
                return None
            await tab.sleep(2)

            if await _is_logged_in(tab):
                raw = await driver.cookies.get_all(requests_cookie_format=True)
                return _cookies_list_to_dict(raw)

            wants_code = await _text_exists(tab, ["Confirmation code", "Code de confirmation"], timeout_s=4)
            if wants_code:
                if code_callback is None:
                    logger.warning("Nodriver login requires confirmation code but no code_callback was provided")
                    return None
                await tab.sleep(10)
                try:
                    code = await code_callback(email or "", email_password or "")
                except Exception as exc:
                    logger.warning("code_callback failed detail=%s", str(exc))
                    return None
                code = _as_str(code)
                if not code:
                    return None
                ok = await _select_and_type(tab, "input[data-testid=ocfEnterTextTextInput]", code, timeout_s=20)
                if not ok:
                    return None
                await tab.sleep(1)
                await _click_first_text(tab, ["Next", "Suivant", "Login", "Se Connecter", "Se connecter"], timeout_s=10)
                await tab.sleep(2)

                if await _is_logged_in(tab):
                    raw = await driver.cookies.get_all(requests_cookie_format=True)
                    return _cookies_list_to_dict(raw)

            locked = await _text_exists(
                tab,
                [
                    "Please verify your email address.",
                    "Your account has been locked.",
                    "Votre compte a ete verrouille.",
                ],
                timeout_s=4,
            )
            if locked:
                logger.warning("Nodriver login failed: account locked/verification required username=%s", username or "<unknown>")
                return None

            if await _is_logged_in(tab):
                raw = await driver.cookies.get_all(requests_cookie_format=True)
                return _cookies_list_to_dict(raw)

            return None
        finally:
            if driver is not None:
                try:
                    driver.stop()
                except Exception:
                    pass
            if display is not None:
                try:
                    display.stop()
                except Exception:
                    pass

    timeout = int(timeout_s or 0)
    if timeout > 0:
        try:
            return await asyncio.wait_for(_inner(), timeout=float(timeout))
        except asyncio.TimeoutError:
            logger.warning("Nodriver login timed out timeout_s=%s", timeout)
            return None
    return await _inner()

