from __future__ import annotations

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


def _account_to_dict(account: AccountTable) -> dict[str, Any]:
    return {column.name: getattr(account, column.name) for column in AccountTable.__table__.columns}


class AccountsRepo:
    def __init__(
        self,
        db_path: str,
        *,
        lease_ttl_s: int = 120,
        daily_pages_limit: int = 5000,
        daily_tweets_limit: int = 50000,
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
        username = account.get("username")
        if not username:
            raise ValueError("Account record must include `username`")

        valid_keys = set(AccountTable.__table__.columns.keys())
        payload = {k: v for k, v in account.items() if k in valid_keys}
        cookies_value = payload.get("cookies_json")
        if isinstance(cookies_value, (dict, list)):
            payload["cookies_json"] = json.dumps(cookies_value, separators=(",", ":"))

        with session_scope(self.db_path) as session:
            stmt = select(AccountTable).where(AccountTable.username == username).limit(1)
            existing = session.execute(stmt).scalar_one_or_none()
            if existing is None:
                obj = AccountTable(username=username)
                for key, value in payload.items():
                    if key == "id":
                        continue
                    setattr(obj, key, value)
                session.add(obj)
                session.flush()
                return

            for key, value in payload.items():
                if key in {"id", "username"}:
                    continue
                setattr(existing, key, value)
            session.flush()


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

    def get_cached(self, key: str) -> Optional[dict]:
        now_ts = time.time()
        with session_scope(self.db_path) as session:
            stmt = select(ManifestCacheTable).where(ManifestCacheTable.key == key).limit(1)
            cached = session.execute(stmt).scalar_one_or_none()
            if cached is None:
                return None
            if cached.expires_at <= now_ts:
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
