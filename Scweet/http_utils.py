from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote, urlparse


from .utils import as_str as _as_str


def _ensure_scheme(url: str, *, default_scheme: str = "http") -> str:
    if "://" in url:
        return url
    return f"{default_scheme}://{url}"


def normalize_http_proxies(proxy: Any) -> Optional[dict[str, str]]:
    """Normalize a "proxy" value into requests/curl_cffi style proxies dict.

    Accepted forms:
    - None -> None
    - str -> used for both http/https (scheme inferred as http if missing)
    - dict with keys "http"/"https" -> used directly (missing scheme inferred as http)
    - dict with keys host/port[/scheme][/username/password] -> converted to URL and used for both
    """

    if proxy is None:
        return None

    if isinstance(proxy, str):
        raw = _as_str(proxy)
        if not raw:
            return None
        url = _ensure_scheme(raw)
        return {"http": url, "https": url}

    if not isinstance(proxy, dict):
        return None

    http_url = _as_str(proxy.get("http"))
    https_url = _as_str(proxy.get("https"))
    if http_url or https_url:
        out: dict[str, str] = {}
        if http_url:
            out["http"] = _ensure_scheme(http_url)
        if https_url:
            out["https"] = _ensure_scheme(https_url)
        if "http" in out and "https" not in out:
            out["https"] = out["http"]
        if "https" in out and "http" not in out:
            out["http"] = out["https"]
        return out or None

    host = _as_str(proxy.get("host"))
    port = _as_str(proxy.get("port"))
    if not host or not port:
        return None

    scheme = _as_str(proxy.get("scheme")) or "http"
    if "://" in scheme:
        scheme = scheme.split("://", 1)[0]
    if not scheme:
        scheme = "http"

    username = _as_str(proxy.get("username") or proxy.get("user"))
    password = _as_str(proxy.get("password") or proxy.get("pass"))
    if username and password:
        auth = f"{quote(username, safe='')}:{quote(password, safe='')}"
        netloc = f"{auth}@{host}:{port}"
    else:
        netloc = f"{host}:{port}"

    url = f"{scheme}://{netloc}"
    return {"http": url, "https": url}


def apply_proxies_to_session(session: Any, proxies: Optional[dict[str, str]]) -> bool:
    """Best-effort proxy application; returns True if we applied something."""

    if session is None or not proxies:
        return False

    applied = False

    # requests.Session uses `proxies` and respects them per-request.
    if hasattr(session, "proxies"):
        try:
            current = getattr(session, "proxies")
            if isinstance(current, dict):
                current.update(proxies)
            else:
                setattr(session, "proxies", dict(proxies))
            applied = True
        except Exception:
            pass

    # Some clients use `proxy` instead.
    if not applied and hasattr(session, "proxy"):
        try:
            setattr(session, "proxy", dict(proxies))
            applied = True
        except Exception:
            pass

    # If user explicitly set proxies, avoid mixing with env proxy vars.
    if applied and hasattr(session, "trust_env"):
        try:
            setattr(session, "trust_env", False)
        except Exception:
            pass

    return applied


def extract_proxy_server(proxy: Any) -> Optional[str]:
    """Return a Chrome-style proxy server string ("host:port") if possible."""

    if proxy is None:
        return None

    if isinstance(proxy, dict):
        host = _as_str(proxy.get("host"))
        port = _as_str(proxy.get("port"))
        if host and port:
            return f"{host}:{port}"
        return None

    if isinstance(proxy, str):
        raw = _as_str(proxy)
        if not raw:
            return None
        if "://" not in raw:
            return raw
        parsed = urlparse(raw)
        server = parsed.netloc or parsed.path
        return server or None

    return None


NO_SIGNATURE_DETAIL = "no x-client-transaction-id header: the build of the request signature failed"
NO_SIGNATURE_CAUSE = (
    "cause: X answers 404 to a request without the x-client-transaction-id header. Scweet could not "
    "build that header, because X did not accept the cookies of any account for its bootstrap page. "
    "Add an account with a fresh auth_token from a browser where you are logged in."
)

X_PAGE_FULL = "full"
X_PAGE_LOGIN = "login"
X_PAGE_SHELL = "shell"

_LOGIN_URL_MARKERS = ("/i/jf/onboarding/web", "mode=login", "/i/flow/login")
_LOGIN_TITLE = "X - The Everything App"


def classify_x_page(html: Any, final_url: Any = None) -> str:
    """Name the page that X served to a bootstrap request.

    ``full`` holds the ``"ondemand.s"`` marker or a ``main.js`` URL. ``login`` is the page that X serves
    when it does not accept the cookies of the request: the final URL is under ``/i/jf/onboarding/web``,
    or the title is the one of that page. ``shell`` is any other page without the markers.
    """
    text = str(html or "")
    if '"ondemand.s"' in text or "/responsive-web/client-web/main." in text:
        return X_PAGE_FULL
    url = _as_str(final_url) or ""
    if any(marker in url for marker in _LOGIN_URL_MARKERS):
        return X_PAGE_LOGIN
    title_start = text.find("<title>")
    if title_start != -1:
        title = text[title_start + 7 : title_start + 7 + 120]
        if title.lstrip().startswith(_LOGIN_TITLE):
            return X_PAGE_LOGIN
    return X_PAGE_SHELL


def describe_rejected_x_page(kind: str) -> str:
    """The cause and the action for a page without the markers, in the words of the reader."""
    if kind == X_PAGE_LOGIN:
        return (
            "X answered its login page, so X did not accept the cookies of the request. "
            "Copy a fresh auth_token from a browser where you are logged in."
        )
    return (
        "X answered a page without the ondemand marker. Since 2026-09 that page needs the cookies of an "
        "account that X accepts. Add an account with a fresh auth_token."
    )


def is_curl_cffi_session(session: Any) -> bool:
    if session is None:
        return False
    cls = getattr(session, "__class__", None)
    module = str(getattr(cls, "__module__", "") or "")
    return "curl_cffi" in module
