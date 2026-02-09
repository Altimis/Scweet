from __future__ import annotations

from typing import Any, Optional
from urllib.parse import quote, urlparse


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


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


def is_curl_cffi_session(session: Any) -> bool:
    if session is None:
        return False
    cls = getattr(session, "__class__", None)
    module = str(getattr(cls, "__module__", "") or "")
    return "curl_cffi" in module
