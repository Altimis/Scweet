from __future__ import annotations

import hashlib
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import requests

from .account_session import DEFAULT_X_BEARER_TOKEN, prepare_account_auth_material
from .repos import AccountsRepo

logger = logging.getLogger(__name__)

_DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# Overridable in tests for deterministic, network-free behavior.
_SESSION_FACTORY = requests.Session

_CANONICAL_KEYS = {
    "username",
    "auth_token",
    "cookies_json",
    "csrf",
    "bearer",
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
            if not any(record.values()):
                continue

            normalized = normalize_account_record(record)
            if normalized.get("username"):
                records.append(normalized)

    return records


def load_cookies_json(path: str) -> list[dict]:
    file_path = Path(path)
    with file_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)

    raw_records: list[Any] = []

    if isinstance(payload, list):
        raw_records = payload
    elif isinstance(payload, dict):
        if isinstance(payload.get("accounts"), list):
            raw_records = payload["accounts"]
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


def bootstrap_cookies_from_auth_token(auth_token: str, timeout_s: int = 30) -> Optional[dict]:
    token = _as_str(auth_token)
    if not token:
        logger.warning("Auth bootstrap skipped: missing auth_token")
        return None

    session = None
    token_fp = _token_fingerprint(token)
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

        response = session.get(
            "https://x.com/home",
            headers={"User-Agent": _DEFAULT_USER_AGENT},
            timeout=timeout_s,
            allow_redirects=True,
        )
        status_code = int(getattr(response, "status_code", 0) or 0)
        if status_code >= 400:
            logger.warning("Auth bootstrap failed token_fp=%s: response_status=%s", token_fp, status_code)
            return None

        cookies: dict[str, Any] = {}
        if hasattr(session, "cookies"):
            try:
                cookies = requests.utils.dict_from_cookiejar(session.cookies)
            except Exception:
                try:
                    cookies = session.cookies.get_dict()
                except Exception:
                    cookies = {}

        if not cookies and hasattr(response, "cookies"):
            try:
                cookies = response.cookies.get_dict()
            except Exception:
                cookies = {}

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
    bootstrap_timeout_s: int = 30,
    bootstrap_fn=None,
) -> int:
    repo = AccountsRepo(db_path)
    processed = 0
    effective_bootstrap = bootstrap_fn or bootstrap_cookies_from_auth_token

    def _normalize_and_enrich(record: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_account_record(record)
        username = _as_str(normalized.get("username")) or "<unknown>"
        token_fp = _token_fingerprint(_as_str(normalized.get("auth_token")))

        material, reason = prepare_account_auth_material(normalized)
        token = _as_str(normalized.get("auth_token"))
        needs_bootstrap = material is None and token and reason in {"missing_csrf", "missing_auth_token"}
        if needs_bootstrap:
            logger.info(
                "Import account bootstrap required username=%s token_fp=%s reason=%s",
                username,
                token_fp,
                reason,
            )
            bootstrapped = effective_bootstrap(token, timeout_s=bootstrap_timeout_s)
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

    return processed
