from __future__ import annotations

import hashlib
import inspect
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .account_session import DEFAULT_X_BEARER_TOKEN, prepare_account_auth_material
from .http_utils import apply_proxies_to_session, is_curl_cffi_session, normalize_http_proxies
from .repos import AccountsRepo

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Overridable in tests for deterministic, network-free behavior.
def _default_session_factory():
    from curl_cffi.requests import Session as CurlSession

    return CurlSession()


_SESSION_FACTORY = _default_session_factory

_CANONICAL_KEYS = {
    "username",
    "auth_token",
    "cookies_json",
    "csrf",
    "bearer",
    "proxy_json",
    "status",
    "available_til",
    "daily_requests",
    "daily_tweets",
    "last_reset_date",
    "total_tweets",
    "busy",
    "last_used",
    "last_error_code",
    "cooldown_reason",
}


def _today_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def _as_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None:
        return default
    try:
        return float(value)
    except Exception:
        return default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _first(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record and record[key] not in (None, ""):
            return record[key]
    return None


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
            return stripped
        return _normalize_cookies_payload(decoded)

    if isinstance(payload, (dict, list)):
        return payload

    return str(payload)


def _normalize_proxy_payload(payload: Any) -> Any:
    """Normalize a proxy payload into a stable python value.

    Accepted forms:
    - None
    - str (proxy URL, or JSON-encoded dict)
    - dict (host/port or http/https mapping)
    """

    if payload is None:
        return None

    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return None
        # Allow JSON-encoded proxy dicts in text sources (accounts.txt, DB, etc).
        if stripped.startswith("{") or stripped.startswith("[") or stripped.startswith('"'):
            try:
                decoded = json.loads(stripped)
            except Exception:
                return stripped
            return decoded
        return stripped

    if isinstance(payload, dict):
        return dict(payload)

    return payload


def _cookies_to_dict(cookies_payload: Any) -> dict[str, Any]:
    if isinstance(cookies_payload, dict):
        return cookies_payload
    if isinstance(cookies_payload, list):
        out: dict[str, Any] = {}
        for item in cookies_payload:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if name:
                out[str(name)] = item.get("value")
        return out
    return {}


def _derive_username(
    username: Optional[str],
    email: Optional[str],
    auth_token: Optional[str],
    cookies_payload: Any,
) -> Optional[str]:
    if username:
        return username

    if email and "@" in email:
        local = email.split("@", 1)[0].strip()
        if local:
            return local

    if auth_token:
        digest = hashlib.sha1(auth_token.encode("utf-8")).hexdigest()[:12]
        return f"auth_{digest}"

    if cookies_payload is not None:
        try:
            blob = json.dumps(cookies_payload, sort_keys=True, separators=(",", ":"), default=str)
        except Exception:
            blob = str(cookies_payload)
        digest = hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
        return f"cookie_{digest}"

    return None


def _token_fingerprint(auth_token: Optional[str]) -> str:
    token = _as_str(auth_token)
    if not token:
        return "-"
    return hashlib.sha1(token.encode("utf-8")).hexdigest()[:10]


def normalize_account_record(record: dict) -> dict:
    data = dict(record or {})

    username = _as_str(_first(data, "username", "user", "handle", "screen_name", "account", "login"))
    password = _as_str(_first(data, "password", "pass"))
    email = _as_str(_first(data, "email", "email_address", "mail"))
    email_password = _as_str(_first(data, "email_password", "email_pass", "mail_password", "mail_pass"))
    two_fa = _as_str(_first(data, "2fa", "two_fa", "twofa", "otp_secret", "otp"))

    auth_token = _as_str(_first(data, "auth_token", "authToken", "token"))
    cookies_payload_raw = _normalize_cookies_payload(
        _first(data, "cookies_json", "cookies", "cookie_jar", "cookieJar")
    )
    cookies_dict = _cookies_to_dict(cookies_payload_raw)
    proxy_payload = _normalize_proxy_payload(_first(data, "proxy_json", "proxy"))

    if not auth_token:
        auth_token = _as_str(cookies_dict.get("auth_token"))

    csrf = _as_str(_first(data, "csrf", "csrf_token", "ct0"))
    if not csrf:
        csrf = _as_str(cookies_dict.get("ct0"))

    bearer = _as_str(_first(data, "bearer", "bearer_token", "authorization"))
    if bearer and bearer.lower().startswith("bearer "):
        bearer = bearer.split(" ", 1)[1].strip()
    if not bearer:
        bearer = _as_str(DEFAULT_X_BEARER_TOKEN)

    if auth_token:
        cookies_dict.setdefault("auth_token", auth_token)
    if csrf:
        cookies_dict.setdefault("ct0", csrf)
    cookies_payload = cookies_dict or None

    username = _derive_username(username, email, auth_token, cookies_payload)

    normalized = {
        "username": username,
        "auth_token": auth_token,
        "cookies_json": cookies_payload,
        "csrf": csrf,
        "bearer": bearer,
        "proxy_json": proxy_payload,
        "status": _as_int(_first(data, "status"), default=1),
        "available_til": _as_float(_first(data, "available_til", "available_until", "cooldown_until"), default=None),
        "daily_requests": max(0, _as_int(_first(data, "daily_requests"), default=0)),
        "daily_tweets": max(0, _as_int(_first(data, "daily_tweets"), default=0)),
        "last_reset_date": _as_str(_first(data, "last_reset_date", "reset_date")) or _today_string(),
        "total_tweets": max(0, _as_int(_first(data, "total_tweets"), default=0)),
        "busy": _as_bool(_first(data, "busy"), default=False),
        "last_used": _as_float(_first(data, "last_used", "last_used_at"), default=time.time()),
    }

    # Keep extra credential fields for future auth flows.
    if password is not None:
        normalized["password"] = password
    if email is not None:
        normalized["email"] = email
    if email_password is not None:
        normalized["email_password"] = email_password
    if two_fa is not None:
        normalized["two_fa"] = two_fa

    # Ensure required canonical keys are always present.
    for key in _CANONICAL_KEYS:
        normalized.setdefault(key, None)

    return normalized


def _load_dotenv_values(env_path: str) -> dict[str, str]:
    file_path = Path(env_path)
    if not file_path.exists():
        return {}

    # Prefer python-dotenv's pure parser (no os.environ side effects) if available.
    try:
        from dotenv import dotenv_values  # type: ignore

        raw = dotenv_values(str(file_path))
        return {str(key): str(value) for key, value in raw.items() if key and value is not None}
    except Exception:
        pass

    values: dict[str, str] = {}
    with file_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.lower().startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[key] = value
    return values


def _parse_cookie_header(value: str) -> dict[str, str]:
    raw = str(value or "").strip()
    if not raw:
        return {}

    lowered = raw.lower()
    if lowered.startswith("cookie:"):
        raw = raw.split(":", 1)[1].strip()

    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        chunk = part.strip()
        if not chunk:
            continue
        if "=" not in chunk:
            continue
        name, cookie_value = chunk.split("=", 1)
        name = name.strip()
        cookie_value = cookie_value.strip()
        if not name:
            continue
        if len(cookie_value) >= 2 and cookie_value[0] == cookie_value[-1] and cookie_value[0] in {"'", '"'}:
            cookie_value = cookie_value[1:-1]
        cookies[name] = cookie_value
    return cookies


def _parse_netscape_cookies_text(value: str) -> dict[str, str]:
    """Parse a Netscape cookies.txt export into a cookie dict.

    Format: 7 columns per line:
      domain, flag, path, secure, expiry, name, value
    """

    text = str(value or "")
    if not text.strip():
        return {}

    cookies: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Netscape exports use comments; HttpOnly cookies are prefixed with '#HttpOnly_'.
        if line.startswith("#") and not line.startswith("#HttpOnly_"):
            continue
        if line.startswith("#HttpOnly_"):
            line = line[len("#HttpOnly_") :].lstrip()

        parts = line.split("\t")
        if len(parts) < 7:
            parts = line.split()
        if len(parts) < 7:
            continue
        if len(parts) > 7:
            remainder = "\t".join(parts[6:]) if "\t" in line else " ".join(parts[6:])
            parts = parts[:6] + [remainder]

        name = str(parts[5] or "").strip()
        if not name:
            continue
        cookies[name] = str(parts[6] or "")

    return cookies


def load_env_account(path: str) -> list[dict]:
    """Load a single account record from a dotenv-style file.

    Supported keys (case-insensitive):
    - Legacy v3: EMAIL, EMAIL_PASSWORD, USERNAME, PASSWORD
    - v4: AUTH_TOKEN, CT0 (or CSRF), TWO_FA/OTP_SECRET/OTP

    This loader is deterministic and performs no network calls.
    """

    raw = _load_dotenv_values(path)
    if not raw:
        return []

    values = {str(key).strip().upper(): _as_str(value) for key, value in raw.items() if key}

    record = {
        "email": values.get("EMAIL"),
        "email_password": values.get("EMAIL_PASSWORD"),
        "username": values.get("USERNAME"),
        "password": values.get("PASSWORD"),
        "two_fa": values.get("TWO_FA") or values.get("OTP_SECRET") or values.get("OTP"),
        "auth_token": values.get("AUTH_TOKEN"),
        # Prefer explicit CT0 (cookie name) when present.
        "csrf": values.get("CT0") or values.get("CSRF"),
        "proxy": values.get("PROXY"),
    }

    normalized = normalize_account_record(record)
    if normalized.get("username"):
        return [normalized]
    return []


_ACCOUNT_RECORD_HINT_KEYS = {
    # Identity / account record shape.
    "username",
    "user",
    "handle",
    "screen_name",
    "account",
    "login",
    # Nested cookie payload keys.
    "cookies",
    "cookies_json",
    "cookie_jar",
    "cookieJar",
    # Credentials.
    "password",
    "pass",
    "email",
    "email_address",
    "mail",
    "email_password",
    "email_pass",
    "mail_password",
    "mail_pass",
    "2fa",
    "two_fa",
    "twofa",
    "otp_secret",
    "otp",
    # Canonical + operational keys.
    "bearer",
    "bearer_token",
    "authorization",
    "csrf",
    "status",
    "available_til",
    "available_until",
    "cooldown_until",
    "daily_requests",
    "daily_tweets",
    "last_reset_date",
    "reset_date",
    "total_tweets",
    "busy",
    "last_used",
    "last_used_at",
    "last_error_code",
    "cooldown_reason",
    # Lease fields.
    "lease_id",
    "lease_run_id",
    "lease_worker_id",
    "lease_acquired_at",
    "lease_expires_at",
}


def _looks_like_cookie_mapping_dict(value: dict[str, Any]) -> bool:
    if not value:
        return False
    # If it already looks like an account record (identity/operational fields), don't treat it as raw cookies.
    for key in value.keys():
        if str(key) in _ACCOUNT_RECORD_HINT_KEYS:
            return False
    return any(key in value for key in ("auth_token", "ct0", "csrf_token", "authToken", "token"))


def load_cookies_payload(payload: Any) -> list[dict]:
    """Load account records from a direct `cookies=` payload.

    Accepted forms:
    - a single account record dict (username/auth_token/cookies/etc)
    - a raw cookie mapping dict: {"auth_token": "...", "ct0": "...", ...}
    - a raw cookie list: [{"name": "auth_token", "value": "..."}, ...]
    - a list of account records
    - an object form with {"accounts": [...]} (same as cookies.json)
    - a mapping of username -> cookies/account payload (same as cookies.json)
    - a JSON string containing any of the above

    This loader is deterministic and performs no network calls.
    """

    if payload is None:
        return []

    if hasattr(payload, "get_dict"):
        payload = payload.get_dict()

    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return []
        try:
            if Path(stripped).exists():
                return load_cookies_json(stripped)
        except Exception:
            pass
        try:
            decoded = json.loads(stripped)
        except Exception:
            cookie_header = _parse_cookie_header(stripped)
            if cookie_header:
                return load_cookies_payload({"cookies": cookie_header})
            # Treat raw strings as a direct auth_token value for convenience.
            return load_cookies_payload({"auth_token": stripped})
        return load_cookies_payload(decoded)

    raw_records: list[Any] = []

    if isinstance(payload, list):
        if not payload:
            return []
        dict_items = [item for item in payload if isinstance(item, dict)]
        looks_like_account_records = any(
            any(
                key in item
                for key in (
                    "username",
                    "user",
                    "handle",
                    "screen_name",
                    "account",
                    "login",
                    "auth_token",
                    "authToken",
                    "token",
                    "cookies",
                    "cookies_json",
                    "cookie_jar",
                    "cookieJar",
                )
            )
            for item in dict_items
        )
        looks_like_cookie_dicts = bool(dict_items) and all(
            "name" in item and "value" in item for item in dict_items
        )
        if looks_like_account_records:
            raw_records = payload
        elif looks_like_cookie_dicts:
            raw_records = [{"cookies": payload}]
        else:
            # Ambiguous list; assume it's a cookie list for a single account.
            raw_records = [{"cookies": payload}]
    elif isinstance(payload, dict):
        if isinstance(payload.get("accounts"), list):
            raw_records = payload["accounts"]
        elif _looks_like_cookie_mapping_dict(payload):
            raw_records = [{"cookies": payload}]
        elif any(
            key in payload
            for key in (
                "username",
                "user",
                "handle",
                "screen_name",
                "account",
                "login",
                "auth_token",
                "authToken",
                "token",
                "cookies",
                "cookies_json",
                "cookie_jar",
                "cookieJar",
                "csrf",
                "csrf_token",
                "ct0",
            )
        ):
            raw_records = [payload]
        else:
            # Mapping-like: username -> cookies/account payload.
            for key, value in payload.items():
                if isinstance(value, dict):
                    if _looks_like_cookie_mapping_dict(value):
                        raw_records.append({"username": key, "cookies": value})
                    else:
                        item = dict(value)
                        item.setdefault("username", key)
                        raw_records.append(item)
                else:
                    raw_records.append({"username": key, "cookies": value})
    else:
        raw_records = [{"cookies": payload}]

    records: list[dict[str, Any]] = []
    for item in raw_records:
        if isinstance(item, dict):
            source = item
        else:
            source = {"cookies": item}

        normalized = normalize_account_record(source)
        if normalized.get("username"):
            records.append(normalized)

    return records


def load_accounts_txt(path: str) -> list[dict]:
    records: list[dict[str, Any]] = []
    file_path = Path(path)

    with file_path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("#"):
                continue

            proxy_spec: Any = None
            if "\t" in line:
                base, suffix = line.split("\t", 1)
                line = base.strip()
                proxy_spec = _normalize_proxy_payload(suffix)

            parts = [part.strip() for part in line.split(":")]
            if len(parts) > 6:
                parts = parts[:5] + [":".join(parts[5:]).strip()]
            if len(parts) < 6:
                parts.extend([""] * (6 - len(parts)))

            record = {
                "username": parts[0],
                "password": parts[1],
                "email": parts[2],
                "email_password": parts[3],
                "2fa": parts[4],
                "auth_token": parts[5],
            }
            if proxy_spec is not None:
                record["proxy"] = proxy_spec
            if not any(record.values()):
                continue

            normalized = normalize_account_record(record)
            if normalized.get("username"):
                records.append(normalized)

    return records


def load_cookies_json(path: str) -> list[dict]:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")

    try:
        payload = json.loads(text)
    except Exception:
        cookies = _parse_netscape_cookies_text(text)
        if not cookies:
            raise
        payload = [{"cookies": cookies}]

    raw_records: list[Any] = []

    if isinstance(payload, list):
        raw_records = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("accounts"), list):
            raw_records = payload["accounts"]
        elif _looks_like_cookie_mapping_dict(payload):
            raw_records = [{"cookies": payload}]
        elif any(
            key in payload
            for key in (
                "username",
                "user",
                "handle",
                "auth_token",
                "authToken",
                "token",
                "cookies",
                "cookies_json",
            )
        ):
            raw_records = [payload]
        else:
            for key, value in payload.items():
                if isinstance(value, dict):
                    if _looks_like_cookie_mapping_dict(value):
                        raw_records.append({"username": key, "cookies": value})
                    else:
                        item = dict(value)
                        item.setdefault("username", key)
                        raw_records.append(item)
                else:
                    raw_records.append({"username": key, "cookies": value})

    records: list[dict[str, Any]] = []
    for item in raw_records:
        if isinstance(item, dict):
            source = item
        else:
            source = {"cookies": item}

        normalized = normalize_account_record(source)
        if normalized.get("username"):
            records.append(normalized)

    return records


def bootstrap_cookies_from_auth_token(auth_token: str, timeout_s: int = 30, *, proxy: Any = None) -> Optional[dict]:
    token = _as_str(auth_token)
    if not token:
        logger.warning("Auth bootstrap skipped: missing auth_token")
        return None

    session = None
    token_fp = _token_fingerprint(token)
    proxies = normalize_http_proxies(proxy)
    try:
        session = _SESSION_FACTORY()
        if session is None:
            logger.warning("Auth bootstrap failed token_fp=%s: session factory returned None", token_fp)
            return None

        logger.info("Auth bootstrap start token_fp=%s timeout_s=%s", token_fp, timeout_s)
        if hasattr(session, "cookies") and hasattr(session.cookies, "set"):
            try:
                session.cookies.set("auth_token", token, domain=".x.com")
            except Exception:
                session.cookies.set("auth_token", token)

        apply_proxies_to_session(session, proxies)
        headers = None
        if not is_curl_cffi_session(session):
            headers = {"User-Agent": _DEFAULT_USER_AGENT}
        if headers is None:
            response = session.get("https://x.com/home", timeout=timeout_s, allow_redirects=True)
        else:
            response = session.get(
                "https://x.com/home",
                headers=headers,
                timeout=timeout_s,
                allow_redirects=True,
            )
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code >= 400:
            logger.warning("Auth bootstrap failed token_fp=%s: response_status=%s", token_fp, status_code)
            return None

        def _cookies_to_dict(value: Any) -> dict[str, Any]:
            if value is None:
                return {}
            if isinstance(value, dict):
                return dict(value)
            getter = getattr(value, "get_dict", None)
            if getter is not None:
                try:
                    got = getter()
                    if isinstance(got, dict):
                        return dict(got)
                except Exception:
                    pass
            try:
                return {str(item.name): item.value for item in value}
            except Exception:
                return {}

        cookies: dict[str, Any] = {}
        if hasattr(session, "cookies"):
            cookies = _cookies_to_dict(getattr(session, "cookies", None))

        if not cookies and hasattr(response, "cookies"):
            cookies = _cookies_to_dict(getattr(response, "cookies", None))

        if not cookies:
            logger.warning("Auth bootstrap failed token_fp=%s: no cookies captured", token_fp)
            return None

        cookies.setdefault("auth_token", token)
        logger.info(
            "Auth bootstrap success token_fp=%s cookie_count=%s has_ct0=%s",
            token_fp,
            len(cookies),
            bool(_as_str(cookies.get("ct0"))),
        )
        return cookies
    except Exception as exc:
        logger.warning("Auth bootstrap exception token_fp=%s detail=%s", token_fp, str(exc))
        return None
    finally:
        if session is not None and hasattr(session, "close"):
            try:
                session.close()
            except Exception:
                pass


def import_accounts_to_db(
    db_path: str,
    accounts_file: Optional[str] = None,
    cookies_file: Optional[str] = None,
    env_path: Optional[str] = None,
    cookies_payload: Any = None,
    bootstrap_strategy: Any = "auto",
    bootstrap_timeout_s: int = 30,
    bootstrap_fn=None,
    creds_bootstrap_timeout_s: int = 180,
    creds_bootstrap_fn=None,
    runtime: Optional[Mapping[str, Any]] = None,
) -> int:
    repo = AccountsRepo(db_path)
    processed = 0
    effective_bootstrap = bootstrap_fn or bootstrap_cookies_from_auth_token
    runtime_options = dict(runtime or {})

    strategy_raw = getattr(bootstrap_strategy, "value", bootstrap_strategy)
    strategy = str(strategy_raw or "auto").strip().lower()
    if strategy not in {"auto", "token_only", "nodriver_only", "none"}:
        logger.warning("Unknown bootstrap_strategy=%s; using auto", str(strategy_raw))
        strategy = "auto"
    allow_token_bootstrap = strategy in {"auto", "token_only"}
    allow_creds_bootstrap = strategy in {"auto", "nodriver_only"}

    def _call_token_bootstrap(auth_token: str, *, proxy: Any) -> Optional[dict]:
        if effective_bootstrap is None:
            return None
        try:
            params = inspect.signature(effective_bootstrap).parameters
            if "proxy" in params:
                return effective_bootstrap(
                    auth_token,
                    timeout_s=bootstrap_timeout_s,
                    proxy=proxy,
                )
        except Exception:
            pass
        return effective_bootstrap(auth_token, timeout_s=bootstrap_timeout_s)

    def _db_has_usable_auth(username: Optional[str], token: Optional[str]) -> bool:
        existing = repo.get_by_username(username or "") if username else None
        if existing is None and token:
            existing = repo.get_by_auth_token(token)
        if existing is None:
            return False
        material, _reason = prepare_account_auth_material(existing)
        return material is not None

    def _normalize_and_enrich(record: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_account_record(record)
        username = _as_str(normalized.get("username")) or "<unknown>"
        token_fp = _token_fingerprint(_as_str(normalized.get("auth_token")))
        record_proxy = normalized.get("proxy_json")
        if record_proxy is None:
            record_proxy = runtime_options.get("proxy")
        record_proxy = _normalize_proxy_payload(record_proxy)

        if _db_has_usable_auth(_as_str(normalized.get("username")), _as_str(normalized.get("auth_token"))):
            logger.info("Import account reuse username=%s token_fp=%s", username, token_fp)
            return normalized

        material, reason = prepare_account_auth_material(normalized)
        token = _as_str(normalized.get("auth_token"))
        needs_bootstrap = (
            allow_token_bootstrap
            and material is None
            and token
            and reason in {"missing_csrf", "missing_auth_token"}
        )
        if needs_bootstrap:
            logger.info(
                "Import account bootstrap required username=%s token_fp=%s reason=%s",
                username,
                token_fp,
                reason,
            )
            bootstrapped = _call_token_bootstrap(token, proxy=record_proxy)
            if bootstrapped:
                cookies_dict = _cookies_to_dict(_normalize_cookies_payload(bootstrapped))
                if cookies_dict:
                    normalized["cookies_json"] = cookies_dict
                    normalized["csrf"] = _as_str(normalized.get("csrf")) or _as_str(cookies_dict.get("ct0"))
                    normalized["auth_token"] = token
                    logger.info(
                        "Import account bootstrap success username=%s token_fp=%s cookie_count=%s has_ct0=%s",
                        username,
                        token_fp,
                        len(cookies_dict),
                        bool(_as_str(cookies_dict.get("ct0"))),
                    )
                material, reason = prepare_account_auth_material(normalized)
            else:
                logger.warning(
                    "Import account bootstrap failed username=%s token_fp=%s",
                    username,
                    token_fp,
                )

        if material is None:
            # If auth_token bootstrap couldn't produce usable auth, try credentials via nodriver.
            has_password = _as_str(normalized.get("password")) is not None
            has_login_identifier = (
                _as_str(normalized.get("email")) is not None or _as_str(normalized.get("username")) is not None
            )
            if allow_creds_bootstrap and has_password and has_login_identifier:
                effective_creds_bootstrap = creds_bootstrap_fn
                if effective_creds_bootstrap is None:
                    try:
                        from .nodriver_bootstrap import bootstrap_cookies_from_credentials as _default_creds_bootstrap

                        effective_creds_bootstrap = _default_creds_bootstrap
                    except Exception:
                        effective_creds_bootstrap = None

                if effective_creds_bootstrap is not None:
                    logger.info(
                        "Import account creds bootstrap required username=%s token_fp=%s",
                        username,
                        token_fp,
                    )
                    try:
                        bootstrapped = effective_creds_bootstrap(
                            normalized,
                            proxy=record_proxy,
                            user_agent=runtime_options.get("user_agent"),
                            headless=bool(runtime_options.get("headless", True)),
                            disable_images=bool(runtime_options.get("disable_images", False)),
                            code_callback=runtime_options.get("code_callback"),
                            timeout_s=int(creds_bootstrap_timeout_s),
                        )
                    except Exception as exc:
                        logger.warning(
                            "Import account creds bootstrap exception username=%s detail=%s",
                            username,
                            str(exc),
                        )
                        bootstrapped = None

                    if bootstrapped:
                        cookies_dict = _cookies_to_dict(_normalize_cookies_payload(bootstrapped))
                        if cookies_dict:
                            normalized["cookies_json"] = cookies_dict
                            normalized["csrf"] = _as_str(normalized.get("csrf")) or _as_str(cookies_dict.get("ct0"))
                            normalized["auth_token"] = _as_str(normalized.get("auth_token")) or _as_str(
                                cookies_dict.get("auth_token")
                            )
                            logger.info(
                                "Import account creds bootstrap success username=%s cookie_count=%s has_ct0=%s",
                                username,
                                len(cookies_dict),
                                bool(_as_str(cookies_dict.get("ct0"))),
                            )
                        material, reason = prepare_account_auth_material(normalized)
                    else:
                        logger.warning("Import account creds bootstrap failed username=%s", username)

        if material is None:
            normalized["status"] = 0
            normalized["available_til"] = 0.0
            normalized["cooldown_reason"] = f"unusable:{reason or 'missing_auth_material'}"
            normalized["last_error_code"] = 401
            logger.warning(
                "Import account unusable username=%s token_fp=%s reason=%s",
                username,
                token_fp,
                reason or "missing_auth_material",
            )
            return normalized

        normalized["auth_token"] = material.auth_token
        normalized["csrf"] = material.csrf_token
        normalized["bearer"] = material.bearer_token
        normalized["cookies_json"] = material.cookies
        logger.info(
            "Import account ready username=%s token_fp=%s cookie_count=%s",
            username,
            token_fp,
            len(material.cookies),
        )
        cooldown_reason = _as_str(normalized.get("cooldown_reason"))
        if cooldown_reason and cooldown_reason.startswith("unusable:"):
            normalized["cooldown_reason"] = None
            normalized["last_error_code"] = None
            if int(_as_int(normalized.get("status"), default=1)) == 0:
                normalized["status"] = 1
        return normalized

    if accounts_file:
        for record in load_accounts_txt(accounts_file):
            repo.upsert_account(_normalize_and_enrich(record))
            processed += 1

    if cookies_file:
        for record in load_cookies_json(cookies_file):
            repo.upsert_account(_normalize_and_enrich(record))
            processed += 1

    if env_path:
        for record in load_env_account(env_path):
            repo.upsert_account(_normalize_and_enrich(record))
            processed += 1

    if cookies_payload is not None:
        for record in load_cookies_payload(cookies_payload):
            repo.upsert_account(_normalize_and_enrich(record))
            processed += 1

    return processed
