from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import delete, func, select

from .repos import AccountsRepo, ResumeRepo
from .schema import AccountTable, ResumeStateTable, RunTable
from .storage import init_db, session_scope


def _today_string() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _as_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _fingerprint(value: Any, *, chars: int = 10) -> str:
    text = _as_str(value)
    if not text:
        return "-"
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[: max(4, int(chars))]


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
        raw = value.strip()
        if not raw:
            return {}
        try:
            decoded = json.loads(raw)
        except Exception:
            return {}
        return _cookies_to_dict(decoded)
    return {}


def _proxy_from_db_value(value: Any) -> Any:
    raw = _as_str(value)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return raw


def _row_to_dict(row: Any, table) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in table.__table__.columns}


def _redact_account_record(
    record: dict[str, Any],
    *,
    include_cookies: bool,
    reveal_secrets: bool,
) -> dict[str, Any]:
    auth_token = _as_str(record.get("auth_token"))
    csrf = _as_str(record.get("csrf"))
    bearer = _as_str(record.get("bearer"))
    cookies_dict = _cookies_to_dict(record.get("cookies_json"))
    proxy_value = record.get("proxy_json")
    proxy_raw = _as_str(proxy_value)

    out: dict[str, Any] = {
        "id": record.get("id"),
        "username": record.get("username"),
        "status": record.get("status"),
        "available_til": record.get("available_til"),
        "cooldown_reason": record.get("cooldown_reason"),
        "last_error_code": record.get("last_error_code"),
        "busy": record.get("busy"),
        "lease_id": record.get("lease_id"),
        "lease_run_id": record.get("lease_run_id"),
        "lease_worker_id": record.get("lease_worker_id"),
        "lease_acquired_at": record.get("lease_acquired_at"),
        "lease_expires_at": record.get("lease_expires_at"),
        "daily_requests": record.get("daily_requests"),
        "daily_tweets": record.get("daily_tweets"),
        "last_reset_date": record.get("last_reset_date"),
        "total_tweets": record.get("total_tweets"),
        "last_used": record.get("last_used"),
        "auth_token_fp": _fingerprint(auth_token),
        "csrf_fp": _fingerprint(csrf),
        "has_bearer": bool(bearer),
        "cookies_count": int(len([k for k, v in cookies_dict.items() if _as_str(v) is not None])),
        "has_proxy": bool(proxy_raw),
        "proxy_fp": _fingerprint(proxy_raw),
    }

    if include_cookies:
        out["cookies_keys"] = sorted({str(key) for key in cookies_dict.keys()})

    if reveal_secrets:
        out["auth_token"] = auth_token
        out["csrf"] = csrf
        out["bearer"] = bearer
        out["cookies"] = dict(cookies_dict)
        out["proxy"] = _proxy_from_db_value(proxy_value)

    return out


class ScweetDB:
    """Public DB/state wrapper for Scweet's local SQLite state."""

    def __init__(
        self,
        db_path: str = "scweet_state.db",
        *,
        account_daily_requests_limit: int = 5000,
        account_daily_tweets_limit: int = 50000,
    ):
        self.db_path = str(db_path or "scweet_state.db")
        self.account_daily_requests_limit = max(1, int(account_daily_requests_limit or 5000))
        self.account_daily_tweets_limit = max(1, int(account_daily_tweets_limit or 50000))
        init_db(self.db_path)

    def accounts_summary(self) -> dict[str, Any]:
        now_ts = time.time()
        eligible = AccountsRepo(
            self.db_path,
            require_auth_material=True,
            daily_pages_limit=self.account_daily_requests_limit,
            daily_tweets_limit=self.account_daily_tweets_limit,
        ).count_eligible(now_ts=now_ts)

        with session_scope(self.db_path) as session:
            total = int(session.execute(select(func.count()).select_from(AccountTable)).scalar_one() or 0)
            unusable = int(
                session.execute(select(func.count()).select_from(AccountTable).where(AccountTable.status == 0)).scalar_one()
                or 0
            )
            cooling_down = int(
                session.execute(
                    select(func.count())
                    .select_from(AccountTable)
                    .where(AccountTable.available_til.is_not(None), AccountTable.available_til > now_ts)
                ).scalar_one()
                or 0
            )
            leased = int(
                session.execute(
                    select(func.count())
                    .select_from(AccountTable)
                    .where(AccountTable.lease_id.is_not(None), AccountTable.lease_expires_at.is_not(None), AccountTable.lease_expires_at > now_ts)
                ).scalar_one()
                or 0
            )
            with_token = int(
                session.execute(
                    select(func.count())
                    .select_from(AccountTable)
                    .where(func.length(func.trim(func.coalesce(AccountTable.auth_token, ""))) > 0)
                ).scalar_one()
                or 0
            )
            with_cookies = int(
                session.execute(
                    select(func.count())
                    .select_from(AccountTable)
                    .where(func.length(func.trim(func.coalesce(AccountTable.cookies_json, ""))) > 0)
                ).scalar_one()
                or 0
            )

        return {
            "db_path": self.db_path,
            "total": total,
            "eligible": int(eligible),
            "unusable": unusable,
            "cooling_down": cooling_down,
            "leased": leased,
            "with_auth_token": with_token,
            "with_cookies": with_cookies,
        }

    def list_accounts(
        self,
        *,
        limit: int = 200,
        offset: int = 0,
        eligible_only: bool = False,
        unusable_only: bool = False,
        include_cookies: bool = False,
        reveal_secrets: bool = False,
    ) -> list[dict[str, Any]]:
        now_ts = time.time()
        clauses = []
        if eligible_only:
            repo = AccountsRepo(
                self.db_path,
                require_auth_material=True,
                daily_pages_limit=self.account_daily_requests_limit,
                daily_tweets_limit=self.account_daily_tweets_limit,
            )
            clauses.extend(repo._eligible_clauses(now_ts))  # type: ignore[attr-defined]
        if unusable_only:
            clauses.append(AccountTable.status == 0)

        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).order_by(AccountTable.id.asc())
            if clauses:
                stmt = stmt.where(*clauses)
            stmt = stmt.offset(max(0, int(offset))).limit(max(1, int(limit)))
            rows = list(session.execute(stmt).scalars().all())
            records = [_row_to_dict(row, AccountTable) for row in rows]

        return [
            _redact_account_record(
                record,
                include_cookies=bool(include_cookies),
                reveal_secrets=bool(reveal_secrets),
            )
            for record in records
        ]

    def get_account(
        self,
        username: str,
        *,
        include_cookies: bool = False,
        reveal_secrets: bool = False,
    ) -> Optional[dict[str, Any]]:
        record = AccountsRepo(self.db_path).get_by_username(username)
        if record is None:
            return None
        return _redact_account_record(
            record,
            include_cookies=bool(include_cookies),
            reveal_secrets=bool(reveal_secrets),
        )

    def delete_account(self, username: str) -> dict[str, Any]:
        name = _as_str(username)
        if not name:
            raise ValueError("username is required")
        with session_scope(self.db_path) as session:
            result = session.execute(delete(AccountTable).where(AccountTable.username == name))
            deleted = int(getattr(result, "rowcount", 0) or 0)
        return {"deleted": deleted}

    def set_account_proxy(self, username: str, proxy: Any) -> dict[str, Any]:
        """Set (or clear) an account's per-account proxy override.

        `proxy` accepted forms:
        - None (clears proxy override)
        - str (proxy URL, host:port, etc.)
        - dict (host/port or http/https mapping)
        """

        name = _as_str(username)
        if not name:
            raise ValueError("username is required")

        if proxy is None:
            stored: Optional[str] = None
        elif isinstance(proxy, (dict, list)):
            stored = json.dumps(proxy, separators=(",", ":"))
        else:
            stored = _as_str(proxy)

        updated = 0
        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).where(AccountTable.username == name).limit(1)
            account = session.execute(stmt).scalar_one_or_none()
            if account is None:
                return {"updated": 0}
            setattr(account, "proxy_json", stored)
            session.flush()
            updated = 1
        return {"updated": updated, "cleared": proxy is None}

    def mark_account_unusable(self, username: str, *, reason: str = "manual") -> dict[str, Any]:
        name = _as_str(username)
        if not name:
            raise ValueError("username is required")
        cooldown_reason = f"unusable:{_as_str(reason) or 'manual'}"

        updated = 0
        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).where(AccountTable.username == name).limit(1)
            account = session.execute(stmt).scalar_one_or_none()
            if account is None:
                return {"updated": 0}
            account.status = 0
            account.available_til = 0.0
            account.cooldown_reason = cooldown_reason
            account.last_error_code = 401
            account.busy = False
            account.lease_id = None
            account.lease_run_id = None
            account.lease_worker_id = None
            account.lease_acquired_at = None
            account.lease_expires_at = None
            session.flush()
            updated = 1

        return {"updated": updated}

    def reset_account_cooldowns(
        self,
        *,
        usernames: Optional[Iterable[str]] = None,
        include_unusable: bool = False,
        clear_leases: bool = False,
    ) -> dict[str, Any]:
        targets = [name for name in [(_as_str(item) or "") for item in (usernames or [])] if name]
        updated = 0
        with session_scope(self.db_path) as session:
            stmt = select(AccountTable)
            if targets:
                stmt = stmt.where(AccountTable.username.in_(targets))
            rows = list(session.execute(stmt).scalars().all())
            for account in rows:
                if not include_unusable and int(getattr(account, "status", 1) or 0) == 0:
                    continue
                account.available_til = 0.0
                account.cooldown_reason = None
                account.last_error_code = None
                if include_unusable and int(getattr(account, "status", 1) or 0) == 0:
                    account.status = 1
                if clear_leases:
                    account.busy = False
                    account.lease_id = None
                    account.lease_run_id = None
                    account.lease_worker_id = None
                    account.lease_acquired_at = None
                    account.lease_expires_at = None
                updated += 1
            session.flush()
        return {"updated": updated}

    def clear_leases(self, *, expired_only: bool = True) -> dict[str, Any]:
        now_ts = time.time()
        updated = 0
        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).where(AccountTable.lease_id.is_not(None))
            if expired_only:
                stmt = stmt.where(AccountTable.lease_expires_at.is_not(None), AccountTable.lease_expires_at <= now_ts)
            rows = list(session.execute(stmt).scalars().all())
            for account in rows:
                account.busy = False
                account.lease_id = None
                account.lease_run_id = None
                account.lease_worker_id = None
                account.lease_acquired_at = None
                account.lease_expires_at = None
                updated += 1
            session.flush()
        return {"released": updated, "expired_only": bool(expired_only)}

    def reset_daily_counters(self, *, usernames: Optional[Iterable[str]] = None) -> dict[str, Any]:
        targets = [name for name in [(_as_str(item) or "") for item in (usernames or [])] if name]
        updated = 0
        today = _today_string()
        with session_scope(self.db_path) as session:
            stmt = select(AccountTable)
            if targets:
                stmt = stmt.where(AccountTable.username.in_(targets))
            rows = list(session.execute(stmt).scalars().all())
            for account in rows:
                account.daily_requests = 0
                account.daily_tweets = 0
                account.last_reset_date = today
                updated += 1
            session.flush()
        return {"updated": updated}

    def import_accounts_from_sources(
        self,
        *,
        accounts_file: Optional[str] = None,
        cookies_file: Optional[str] = None,
        env_path: Optional[str] = None,
        cookies: Any = None,
        bootstrap_strategy: Any = "auto",
        bootstrap_timeout_s: int = 30,
        creds_bootstrap_timeout_s: int = 180,
        proxy: Any = None,
        user_agent: Optional[str] = None,
        headless: bool = True,
        disable_images: bool = False,
        code_callback: Any = None,
    ) -> dict[str, int]:
        from .auth import import_accounts_to_db

        runtime = {
            "proxy": proxy,
            "user_agent": user_agent,
            "headless": bool(headless),
            "disable_images": bool(disable_images),
            "code_callback": code_callback,
        }
        processed = int(
            import_accounts_to_db(
                self.db_path,
                accounts_file=accounts_file,
                cookies_file=cookies_file,
                env_path=env_path,
                cookies_payload=cookies,
                bootstrap_strategy=bootstrap_strategy,
                bootstrap_timeout_s=int(bootstrap_timeout_s),
                creds_bootstrap_timeout_s=int(creds_bootstrap_timeout_s),
                runtime=runtime,
            )
        )
        eligible = int(
            AccountsRepo(
                self.db_path,
                require_auth_material=True,
                daily_pages_limit=self.account_daily_requests_limit,
                daily_tweets_limit=self.account_daily_tweets_limit,
            ).count_eligible()
        )
        return {"processed": processed, "eligible": eligible}

    def collapse_duplicates_by_auth_token(self, *, dry_run: bool = True) -> dict[str, Any]:
        return AccountsRepo(self.db_path).collapse_duplicates_by_auth_token(dry_run=bool(dry_run))

    def get_checkpoint(self, query_hash: str) -> Optional[dict[str, Any]]:
        return ResumeRepo(self.db_path).get_checkpoint(query_hash)

    def clear_checkpoint(self, query_hash: str) -> None:
        ResumeRepo(self.db_path).clear_checkpoint(query_hash)

    def clear_all_checkpoints(self) -> dict[str, Any]:
        with session_scope(self.db_path) as session:
            result = session.execute(delete(ResumeStateTable))
            deleted = int(getattr(result, "rowcount", 0) or 0)
        return {"deleted": deleted}

    def list_runs(self, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
        with session_scope(self.db_path) as session:
            stmt = (
                select(RunTable)
                .order_by(RunTable.started_at.desc(), RunTable.id.desc())
                .offset(max(0, int(offset)))
                .limit(max(1, int(limit)))
            )
            rows = list(session.execute(stmt).scalars().all())
            records = [_row_to_dict(row, RunTable) for row in rows]

        out: list[dict[str, Any]] = []
        for item in records:
            for key in ("input_json", "stats_json"):
                raw = item.get(key)
                if isinstance(raw, str) and raw.strip():
                    try:
                        item[key] = json.loads(raw)
                    except Exception:
                        item[key] = raw
            out.append(item)
        return out

    def last_run(self) -> Optional[dict[str, Any]]:
        rows = self.list_runs(limit=1)
        return rows[0] if rows else None

    def runs_summary(self, *, limit: int = 500) -> dict[str, Any]:
        runs = self.list_runs(limit=max(1, int(limit)))
        by_status: dict[str, int] = {}
        tasks_failed = 0
        for run in runs:
            status = str(run.get("status") or "").strip() or "unknown"
            by_status[status] = by_status.get(status, 0) + 1
            stats = run.get("stats_json")
            if isinstance(stats, dict):
                try:
                    tasks_failed += int(stats.get("tasks_failed") or 0)
                except Exception:
                    pass
        return {
            "db_path": self.db_path,
            "total_runs": len(runs),
            "by_status": by_status,
            "tasks_failed_total": int(tasks_failed),
            "last_run": runs[0] if runs else None,
        }
