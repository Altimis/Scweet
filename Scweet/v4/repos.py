from __future__ import annotations

import hashlib
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import and_, delete, func, or_, select

from .account_session import DEFAULT_X_BEARER_TOKEN, prepare_account_auth_material
from .schema import AccountTable, ManifestCacheTable, ResumeStateTable, RunTable
from .storage import init_db, session_scope

logger = logging.getLogger(__name__)

_REUSABLE_STATUSES = (1, 401, 403, 404)


def _today_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except Exception:
        return None


def _is_synthetic_username(username: str) -> bool:
    normalized = (username or "").strip().lower()
    return normalized.startswith("auth_") or normalized.startswith("cookie_")


def _cookies_to_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}

    if isinstance(value, dict):
        return dict(value)

    if isinstance(value, list):
        out: dict[str, Any] = {}
        for item in value:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if name:
                out[str(name)] = item.get("value")
        return out

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            decoded = json.loads(stripped)
        except Exception:
            return {}
        return _cookies_to_dict(decoded)

    return {}


def _cookies_non_empty_count(cookies: dict[str, Any]) -> int:
    count = 0
    for value in (cookies or {}).values():
        text = _as_str(value)
        if text is not None:
            count += 1
    return count


def _auth_quality(*, auth_token: Optional[str], csrf: Optional[str], cookies: dict[str, Any]) -> tuple[int, int, int, int]:
    has_token = 1 if _as_str(auth_token) else 0
    has_csrf = 1 if _as_str(csrf) else 0
    has_cookies = 1 if cookies else 0
    cookie_count = _cookies_non_empty_count(cookies)
    return (has_token, has_csrf, has_cookies, cookie_count)


def _merge_cookie_dicts(existing: dict[str, Any], incoming: dict[str, Any], *, prefer_incoming: bool) -> dict[str, Any]:
    merged = dict(existing or {})
    for key, value in (incoming or {}).items():
        value_text = _as_str(value)
        if value_text is None:
            continue
        if prefer_incoming:
            merged[key] = value
            continue

        current_text = _as_str(merged.get(key))
        if current_text is None:
            merged[key] = value
    return merged


def _account_to_dict(account: AccountTable) -> dict[str, Any]:
    return {column.name: getattr(account, column.name) for column in AccountTable.__table__.columns}


class AccountsRepo:
    def __init__(
        self,
        db_path: str,
        *,
        lease_ttl_s: int = 120,
        daily_pages_limit: int = 30,
        daily_tweets_limit: int = 600,
        require_auth_material: bool = False,
        default_bearer_token: Optional[str] = DEFAULT_X_BEARER_TOKEN,
    ):
        self.db_path = db_path
        self.lease_ttl_s = lease_ttl_s
        self.daily_pages_limit = daily_pages_limit
        self.daily_tweets_limit = daily_tweets_limit
        self.require_auth_material = bool(require_auth_material)
        self.default_bearer_token = default_bearer_token
        init_db(db_path)

    def _eligible_clauses(self, now_ts: float):
        today = _today_string()
        clauses = [
            or_(AccountTable.status.is_(None), AccountTable.status.in_(_REUSABLE_STATUSES)),
            or_(AccountTable.available_til.is_(None), AccountTable.available_til <= now_ts),
            or_(
                AccountTable.lease_id.is_(None),
                AccountTable.lease_expires_at.is_(None),
                AccountTable.lease_expires_at <= now_ts,
            ),
            or_(
                AccountTable.last_reset_date.is_(None),
                AccountTable.last_reset_date != today,
                and_(
                    func.coalesce(AccountTable.daily_requests, 0) < self.daily_pages_limit,
                    func.coalesce(AccountTable.daily_tweets, 0) < self.daily_tweets_limit,
                ),
            ),
        ]
        if self.require_auth_material:
            clauses.extend(
                [
                    func.length(func.trim(func.coalesce(AccountTable.auth_token, ""))) > 0,
                    func.length(func.trim(func.coalesce(AccountTable.csrf, ""))) > 0,
                    func.length(func.trim(func.coalesce(AccountTable.cookies_json, ""))) > 0,
                ]
            )
            if not self.default_bearer_token:
                clauses.append(func.length(func.trim(func.coalesce(AccountTable.bearer, ""))) > 0)
        return clauses

    def acquire_leases(
        self,
        count: int,
        run_id: str,
        worker_id_prefix: str,
        now_ts: Optional[float] = None,
    ) -> list[dict]:
        now_ts = now_ts or time.time()
        leases: list[dict[str, Any]] = []

        with session_scope(self.db_path) as session:
            worker_slot = 0
            while worker_slot < count:
                stmt = (
                    select(AccountTable)
                    .where(*self._eligible_clauses(now_ts))
                    .order_by(func.coalesce(AccountTable.last_used, 0).asc(), AccountTable.id.asc())
                    .limit(1)
                )
                account = session.execute(stmt).scalar_one_or_none()
                if account is None:
                    break

                account_data = _account_to_dict(account)
                if self.require_auth_material:
                    material, reason = prepare_account_auth_material(
                        account_data,
                        default_bearer_token=self.default_bearer_token,
                    )
                    if material is None:
                        account.status = 0
                        account.available_til = 0.0
                        account.cooldown_reason = f"unusable:{reason or 'missing_auth_material'}"
                        account.last_error_code = 401
                        account.busy = False
                        account.lease_id = None
                        account.lease_run_id = None
                        account.lease_worker_id = None
                        account.lease_acquired_at = None
                        account.lease_expires_at = None
                        session.flush()
                        logger.info(
                            "Account marked unusable during lease eligibility check username=%s id=%s reason=%s",
                            account.username,
                            account.id,
                            reason,
                        )
                        continue

                lease_id = str(uuid.uuid4())
                account.lease_id = lease_id
                account.lease_run_id = run_id
                account.lease_worker_id = f"{worker_id_prefix}:{worker_slot}"
                account.lease_acquired_at = now_ts
                account.lease_expires_at = now_ts + self.lease_ttl_s
                account.busy = True
                account.last_used = now_ts
                session.flush()
                leases.append(_account_to_dict(account))
                worker_slot += 1

        return leases

    def count_eligible(self, now_ts: Optional[float] = None) -> int:
        now_ts = now_ts or time.time()
        with session_scope(self.db_path) as session:
            stmt = select(func.count()).select_from(AccountTable).where(*self._eligible_clauses(now_ts))
            count = session.execute(stmt).scalar_one()
            return int(count)

    def eligibility_diagnostics(self, *, now_ts: Optional[float] = None, sample_limit: int = 5) -> dict[str, Any]:
        """Return a compact eligibility breakdown to explain lease failures."""

        now_ts = float(now_ts or time.time())
        today = _today_string()
        sample_limit = max(1, int(sample_limit or 5))
        blocked_counts: dict[str, int] = {}
        blocked_samples: list[dict[str, Any]] = []
        eligible = 0

        with session_scope(self.db_path) as session:
            rows = [
                _account_to_dict(row)
                for row in session.execute(select(AccountTable).order_by(AccountTable.id.asc())).scalars().all()
            ]

        for row in rows:
            reasons: list[str] = []
            status_value = _as_int(row.get("status"))
            if status_value is not None and status_value not in _REUSABLE_STATUSES:
                reasons.append("status")

            available_til = row.get("available_til")
            try:
                if available_til is not None and float(available_til) > now_ts:
                    reasons.append("cooldown")
            except Exception:
                pass

            lease_id = _as_str(row.get("lease_id"))
            lease_expires_at = row.get("lease_expires_at")
            lease_active = False
            if lease_id:
                try:
                    lease_active = lease_expires_at is None or float(lease_expires_at) > now_ts
                except Exception:
                    lease_active = True
            if lease_active:
                reasons.append("leased")

            last_reset_date = _as_str(row.get("last_reset_date"))
            daily_requests = int(row.get("daily_requests", 0) or 0)
            daily_tweets = int(row.get("daily_tweets", 0) or 0)
            if (
                last_reset_date == today
                and (
                    daily_requests >= int(self.daily_pages_limit)
                    or daily_tweets >= int(self.daily_tweets_limit)
                )
            ):
                reasons.append("daily_limit")

            if self.require_auth_material:
                if not _as_str(row.get("auth_token")):
                    reasons.append("missing_auth_token")
                if not _as_str(row.get("csrf")):
                    reasons.append("missing_csrf")
                if not _as_str(row.get("cookies_json")):
                    reasons.append("missing_cookies")
                if not self.default_bearer_token and not _as_str(row.get("bearer")):
                    reasons.append("missing_bearer")

            if not reasons:
                eligible += 1
                continue

            for reason in reasons:
                blocked_counts[reason] = blocked_counts.get(reason, 0) + 1

            if len(blocked_samples) < sample_limit:
                blocked_samples.append(
                    {
                        "id": row.get("id"),
                        "username": row.get("username"),
                        "status": status_value,
                        "available_til": available_til,
                        "daily_requests": daily_requests,
                        "daily_tweets": daily_tweets,
                        "has_token": bool(_as_str(row.get("auth_token"))),
                        "has_csrf": bool(_as_str(row.get("csrf"))),
                        "has_cookies": bool(_as_str(row.get("cookies_json"))),
                        "reasons": reasons,
                    }
                )

        return {
            "total": len(rows),
            "eligible": int(eligible),
            "blocked_counts": blocked_counts,
            "blocked_samples": blocked_samples,
        }

    def heartbeat(self, lease_id: str, extend_by_s: int) -> bool:
        now_ts = time.time()
        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).where(AccountTable.lease_id == lease_id).limit(1)
            account = session.execute(stmt).scalar_one_or_none()
            if account is None:
                return False
            account.lease_expires_at = now_ts + (extend_by_s or self.lease_ttl_s)
            session.flush()
            return True

    def release(self, lease_id: str, fields_to_set: dict, fields_to_inc: Optional[dict] = None) -> bool:
        fields_to_inc = fields_to_inc or {}
        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).where(AccountTable.lease_id == lease_id).limit(1)
            account = session.execute(stmt).scalar_one_or_none()
            if account is None:
                return False

            for key, value in fields_to_set.items():
                if hasattr(account, key):
                    setattr(account, key, value)
            for key, value in fields_to_inc.items():
                if hasattr(account, key):
                    current = getattr(account, key) or 0
                    setattr(account, key, current + value)

            account.lease_id = None
            account.lease_run_id = None
            account.lease_worker_id = None
            account.lease_acquired_at = None
            account.lease_expires_at = None
            account.busy = False
            account.last_used = time.time()
            session.flush()
            return True

    def record_usage(self, lease_id: str, pages: int = 0, tweets: int = 0) -> None:
        today = _today_string()
        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).where(AccountTable.lease_id == lease_id).limit(1)
            account = session.execute(stmt).scalar_one_or_none()
            if account is None:
                return

            if account.last_reset_date != today:
                account.daily_requests = 0
                account.daily_tweets = 0
                account.last_reset_date = today

            account.daily_requests = (account.daily_requests or 0) + pages
            account.daily_tweets = (account.daily_tweets or 0) + tweets
            account.total_tweets = (account.total_tweets or 0) + tweets
            session.flush()

    def upsert_account(self, account: dict) -> None:
        incoming_username = _as_str(account.get("username"))
        if not incoming_username:
            raise ValueError("Account record must include `username`")

        valid_keys = set(AccountTable.__table__.columns.keys())
        payload = {k: v for k, v in account.items() if k in valid_keys}
        cookies_value = payload.get("cookies_json")
        if isinstance(cookies_value, (dict, list)):
            payload["cookies_json"] = json.dumps(cookies_value, separators=(",", ":"))
        proxy_value = payload.get("proxy_json")
        if isinstance(proxy_value, (dict, list)):
            payload["proxy_json"] = json.dumps(proxy_value, separators=(",", ":"))
        elif isinstance(proxy_value, str):
            cleaned = proxy_value.strip()
            payload["proxy_json"] = cleaned if cleaned else None

        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).where(AccountTable.username == incoming_username).limit(1)
            existing = session.execute(stmt).scalar_one_or_none()
            match_reason = "username" if existing is not None else ""

            incoming_auth_token = _as_str(payload.get("auth_token"))
            if existing is None and incoming_auth_token:
                stmt = (
                    select(AccountTable)
                    .where(AccountTable.auth_token == incoming_auth_token)
                    .order_by(AccountTable.id.asc())
                    .limit(1)
                )
                existing = session.execute(stmt).scalar_one_or_none()
                if existing is not None:
                    match_reason = "auth_token"

            if existing is None:
                obj = AccountTable(username=incoming_username)
                for key, value in payload.items():
                    if key == "id":
                        continue
                    setattr(obj, key, value)
                session.add(obj)
                session.flush()
                return

            # If we matched by auth_token and the DB username is synthetic while the incoming one looks real,
            # rename to the incoming username (subject to uniqueness).
            if match_reason == "auth_token" and existing.username != incoming_username:
                existing_name = _as_str(existing.username) or ""
                if _is_synthetic_username(existing_name) and not _is_synthetic_username(incoming_username):
                    conflict_stmt = select(AccountTable).where(AccountTable.username == incoming_username).limit(1)
                    conflict = session.execute(conflict_stmt).scalar_one_or_none()
                    if conflict is None:
                        existing.username = incoming_username

            existing_cookies = _cookies_to_dict(getattr(existing, "cookies_json", None))
            incoming_cookies = _cookies_to_dict(payload.get("cookies_json"))

            existing_quality = _auth_quality(
                auth_token=_as_str(getattr(existing, "auth_token", None)),
                csrf=_as_str(getattr(existing, "csrf", None)),
                cookies=existing_cookies,
            )
            incoming_quality = _auth_quality(
                auth_token=incoming_auth_token,
                csrf=_as_str(payload.get("csrf")),
                cookies=incoming_cookies,
            )
            upgrade_auth = incoming_quality > existing_quality

            merged_cookies: Optional[dict[str, Any]] = None
            if existing_cookies or incoming_cookies:
                merged_cookies = _merge_cookie_dicts(
                    existing_cookies,
                    incoming_cookies,
                    prefer_incoming=upgrade_auth,
                )
                if merged_cookies != existing_cookies:
                    setattr(existing, "cookies_json", json.dumps(merged_cookies, separators=(",", ":")))

            existing_auth_token = _as_str(getattr(existing, "auth_token", None))
            if incoming_auth_token and (not existing_auth_token or (upgrade_auth and incoming_auth_token != existing_auth_token)):
                existing.auth_token = incoming_auth_token

            incoming_csrf = _as_str(payload.get("csrf"))
            existing_csrf = _as_str(getattr(existing, "csrf", None))
            if incoming_csrf and (not existing_csrf or (upgrade_auth and incoming_csrf != existing_csrf)):
                existing.csrf = incoming_csrf

            incoming_bearer = _as_str(payload.get("bearer"))
            existing_bearer = _as_str(getattr(existing, "bearer", None))
            if incoming_bearer and (not existing_bearer or (upgrade_auth and incoming_bearer != existing_bearer)):
                existing.bearer = incoming_bearer

            incoming_proxy = _as_str(payload.get("proxy_json"))
            existing_proxy = _as_str(getattr(existing, "proxy_json", None))
            if incoming_proxy and (not existing_proxy or incoming_proxy != existing_proxy):
                setattr(existing, "proxy_json", incoming_proxy)

            # Avoid downgrading status/cooldown fields due to partial imports.
            incoming_status = _as_int(payload.get("status"))
            existing_status = _as_int(getattr(existing, "status", None))
            if incoming_status is not None:
                if existing_status in (None, 0) and incoming_status not in (None, 0):
                    existing.status = incoming_status
                elif existing_status not in (None, 0) and incoming_status in (None, 0):
                    pass
                elif existing_status is None:
                    existing.status = incoming_status

            # If auth material was upgraded, clear unusable markers.
            if upgrade_auth:
                cooldown_reason = _as_str(getattr(existing, "cooldown_reason", None))
                if cooldown_reason and cooldown_reason.startswith("unusable:"):
                    existing.cooldown_reason = None
                    existing.last_error_code = None
                    if _as_int(getattr(existing, "status", None)) == 0:
                        existing.status = 1

            session.flush()

    def get_by_username(self, username: str) -> Optional[dict[str, Any]]:
        name = _as_str(username)
        if not name:
            return None
        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).where(AccountTable.username == name).limit(1)
            existing = session.execute(stmt).scalar_one_or_none()
            if existing is None:
                return None
            return _account_to_dict(existing)

    def get_by_auth_token(self, auth_token: str) -> Optional[dict[str, Any]]:
        token = _as_str(auth_token)
        if not token:
            return None
        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).where(AccountTable.auth_token == token).order_by(AccountTable.id.asc()).limit(1)
            existing = session.execute(stmt).scalar_one_or_none()
            if existing is None:
                return None
            return _account_to_dict(existing)

    def collapse_duplicates_by_auth_token(self, *, dry_run: bool = True) -> dict[str, Any]:
        """Collapse duplicate account rows that share the same (non-empty) auth_token.

        This is an opt-in maintenance routine; it is never run automatically.
        """

        def _token_fingerprint(value: str) -> str:
            token = _as_str(value)
            if not token:
                return "-"
            return hashlib.sha1(token.encode("utf-8")).hexdigest()[:10]

        def _status_rank(value: Any) -> int:
            parsed = _as_int(value)
            if parsed is None:
                return 0
            return 1 if parsed != 0 else 0

        def _last_used_value(value: Any) -> float:
            try:
                return float(value or 0.0)
            except Exception:
                return 0.0

        def _score(record: dict[str, Any]) -> tuple[tuple[int, int, int, int], int, float]:
            cookies = _cookies_to_dict(record.get("cookies_json"))
            quality = _auth_quality(
                auth_token=_as_str(record.get("auth_token")),
                csrf=_as_str(record.get("csrf")),
                cookies=cookies,
            )
            return (quality, _status_rank(record.get("status")), _last_used_value(record.get("last_used")))

        plan: list[dict[str, Any]] = []
        deleted_rows = 0
        updated_rows = 0
        renamed_rows = 0

        with session_scope(self.db_path) as session:
            token_expr = func.trim(func.coalesce(AccountTable.auth_token, ""))
            stmt = (
                select(AccountTable)
                .where(func.length(token_expr) > 0)
                .order_by(token_expr.asc(), AccountTable.id.asc())
            )
            rows = list(session.execute(stmt).scalars().all())

            groups: dict[str, list[AccountTable]] = {}
            for row in rows:
                token = _as_str(getattr(row, "auth_token", None))
                if not token:
                    continue
                groups.setdefault(token, []).append(row)

            dup_groups = {token: grp for token, grp in groups.items() if len(grp) > 1}
            for token, accounts in dup_groups.items():
                records: list[tuple[AccountTable, dict[str, Any]]] = [(acct, _account_to_dict(acct)) for acct in accounts]
                # Stable tie-breaking: preserve deterministic ordering by id (query already orders by id asc).
                canonical_obj, canonical_dict = max(records, key=lambda item: _score(item[1]))
                canonical_quality, _canon_status_rank, _canon_last_used = _score(canonical_dict)

                group_ids = {int(getattr(obj, "id")) for obj, _rec in records if getattr(obj, "id", None) is not None}
                delete_objs = [obj for obj, _rec in records if obj is not canonical_obj]
                delete_usernames = [str(getattr(obj, "username", "") or "") for obj in delete_objs]

                rename_to: Optional[str] = None
                canonical_name = _as_str(getattr(canonical_obj, "username", None)) or ""
                if canonical_name and _is_synthetic_username(canonical_name):
                    real_candidates = [
                        (obj, rec)
                        for obj, rec in records
                        if not _is_synthetic_username(_as_str(getattr(obj, "username", None)) or "")
                    ]
                    if real_candidates:
                        real_obj, _real_rec = max(real_candidates, key=lambda item: _score(item[1]))
                        target_name = _as_str(getattr(real_obj, "username", None))
                        if target_name and target_name != canonical_name:
                            conflict_stmt = select(AccountTable).where(AccountTable.username == target_name).limit(1)
                            conflict = session.execute(conflict_stmt).scalar_one_or_none()
                            # Allow renaming when the only conflict is within this duplicate group (we're deleting it).
                            if conflict is None or int(getattr(conflict, "id")) in group_ids:
                                rename_to = target_name

                plan.append(
                    {
                        "auth_token_fp": _token_fingerprint(token),
                        "count": len(accounts),
                        "keep_username": canonical_name,
                        "delete_usernames": delete_usernames,
                        "rename_to": rename_to,
                    }
                )

                if dry_run:
                    continue

                merged_cookies = _cookies_to_dict(getattr(canonical_obj, "cookies_json", None))
                best_csrf = _as_str(getattr(canonical_obj, "csrf", None)) or _as_str(merged_cookies.get("ct0"))
                best_bearer = _as_str(getattr(canonical_obj, "bearer", None))
                best_proxy = _as_str(getattr(canonical_obj, "proxy_json", None))
                best_status = _as_int(getattr(canonical_obj, "status", None)) or 0
                best_last_used = _last_used_value(getattr(canonical_obj, "last_used", None))

                for other_obj, other_dict in records:
                    if other_obj is canonical_obj:
                        continue
                    other_cookies = _cookies_to_dict(getattr(other_obj, "cookies_json", None))
                    other_quality, _other_status_rank, _other_last_used = _score(other_dict)
                    merged_cookies = _merge_cookie_dicts(
                        merged_cookies,
                        other_cookies,
                        prefer_incoming=other_quality > canonical_quality,
                    )

                    if not best_csrf:
                        best_csrf = _as_str(getattr(other_obj, "csrf", None)) or _as_str(other_cookies.get("ct0"))
                    if not best_bearer:
                        best_bearer = _as_str(getattr(other_obj, "bearer", None))
                    if not best_proxy:
                        best_proxy = _as_str(getattr(other_obj, "proxy_json", None))
                    if best_status == 0 and _as_int(getattr(other_obj, "status", None)) not in (None, 0):
                        best_status = int(getattr(other_obj, "status"))
                    best_last_used = max(best_last_used, _last_used_value(getattr(other_obj, "last_used", None)))

                # Ensure canonical cookies include the auth token and (when available) ct0.
                merged_cookies.setdefault("auth_token", token)
                if best_csrf:
                    merged_cookies.setdefault("ct0", best_csrf)

                canonical_obj.auth_token = token
                if best_csrf:
                    canonical_obj.csrf = best_csrf
                if best_bearer:
                    canonical_obj.bearer = best_bearer
                if best_proxy:
                    canonical_obj.proxy_json = best_proxy
                canonical_obj.status = int(best_status)
                canonical_obj.last_used = float(best_last_used)
                canonical_obj.cookies_json = json.dumps(merged_cookies, separators=(",", ":"))
                updated_rows += 1

                # Delete duplicates first to avoid username uniqueness conflicts during rename.
                for obj in delete_objs:
                    session.delete(obj)
                    deleted_rows += 1
                session.flush()

                if rename_to:
                    canonical_obj.username = rename_to
                    renamed_rows += 1
                    session.flush()

        return {
            "dry_run": bool(dry_run),
            "groups": len(plan),
            "rows_to_delete": int(sum(max(0, item["count"] - 1) for item in plan)),
            "deleted_rows": int(deleted_rows),
            "updated_rows": int(updated_rows),
            "renamed_rows": int(renamed_rows),
            "plan": plan,
        }


class RunsRepo:
    def __init__(self, db_path: str):
        self.db_path = db_path
        init_db(db_path)

    def create_run(self, query_hash: str, input_payload: dict) -> str:
        run_id = str(uuid.uuid4())
        now_ts = time.time()
        payload_json = json.dumps(input_payload or {}, separators=(",", ":"))
        with session_scope(self.db_path) as session:
            run = RunTable(
                run_id=run_id,
                status="running",
                started_at=now_ts,
                finished_at=None,
                query_hash=query_hash,
                tweets_count=0,
                input_json=payload_json,
                stats_json=None,
            )
            session.add(run)
            session.flush()
        return run_id

    def finalize_run(self, run_id: str, status: str, tweets_count: int, stats: Optional[dict] = None) -> None:
        with session_scope(self.db_path) as session:
            stmt = select(RunTable).where(RunTable.run_id == run_id).limit(1)
            run = session.execute(stmt).scalar_one_or_none()
            if run is None:
                return
            run.status = status
            run.tweets_count = tweets_count
            run.finished_at = time.time()
            run.stats_json = json.dumps(stats or {}, separators=(",", ":")) if stats is not None else run.stats_json
            session.flush()


class ResumeRepo:
    def __init__(self, db_path: str):
        self.db_path = db_path
        init_db(db_path)

    def get_checkpoint(self, query_hash: str) -> Optional[dict]:
        with session_scope(self.db_path) as session:
            stmt = (
                select(ResumeStateTable)
                .where(ResumeStateTable.query_hash == query_hash)
                .order_by(ResumeStateTable.updated_at.desc(), ResumeStateTable.id.desc())
                .limit(1)
            )
            state = session.execute(stmt).scalar_one_or_none()
            if state is None:
                return None
            return {
                "run_id": state.run_id,
                "query_hash": state.query_hash,
                "cursor": state.cursor,
                "since": state.since,
                "until": state.until,
                "updated_at": state.updated_at,
            }

    def save_checkpoint(self, query_hash: str, cursor: Optional[str], since: str, until: str) -> None:
        now_ts = time.time()
        with session_scope(self.db_path) as session:
            stmt = select(ResumeStateTable).where(ResumeStateTable.query_hash == query_hash).limit(1)
            state = session.execute(stmt).scalar_one_or_none()
            if state is None:
                state = ResumeStateTable(
                    run_id="",
                    query_hash=query_hash,
                    cursor=cursor,
                    since=since,
                    until=until,
                    updated_at=now_ts,
                )
                session.add(state)
            else:
                state.cursor = cursor
                state.since = since
                state.until = until
                state.updated_at = now_ts
            session.flush()

    def clear_checkpoint(self, query_hash: str) -> None:
        with session_scope(self.db_path) as session:
            session.execute(delete(ResumeStateTable).where(ResumeStateTable.query_hash == query_hash))
            session.flush()


class ManifestRepo:
    def __init__(self, db_path: str):
        self.db_path = db_path
        init_db(db_path)

    def get_cached(self, key: str, *, allow_expired: bool = False) -> Optional[dict]:
        now_ts = time.time()
        with session_scope(self.db_path) as session:
            stmt = select(ManifestCacheTable).where(ManifestCacheTable.key == key).limit(1)
            cached = session.execute(stmt).scalar_one_or_none()
            if cached is None:
                return None
            if (not allow_expired) and cached.expires_at <= now_ts:
                return None
            try:
                manifest = json.loads(cached.manifest_json)
            except Exception:
                manifest = None
            return {
                "key": cached.key,
                "manifest": manifest,
                "fetched_at": cached.fetched_at,
                "expires_at": cached.expires_at,
                "etag": cached.etag,
            }

    def set_cached(self, key: str, manifest: dict, ttl_s: int, etag: Optional[str] = None) -> None:
        now_ts = time.time()
        expires_at = now_ts + max(ttl_s, 0)
        manifest_json = json.dumps(manifest or {}, separators=(",", ":"))
        with session_scope(self.db_path) as session:
            stmt = select(ManifestCacheTable).where(ManifestCacheTable.key == key).limit(1)
            cached = session.execute(stmt).scalar_one_or_none()
            if cached is None:
                cached = ManifestCacheTable(
                    key=key,
                    manifest_json=manifest_json,
                    fetched_at=now_ts,
                    expires_at=expires_at,
                    etag=etag,
                )
                session.add(cached)
            else:
                cached.manifest_json = manifest_json
                cached.fetched_at = now_ts
                cached.expires_at = expires_at
                cached.etag = etag
            session.flush()
