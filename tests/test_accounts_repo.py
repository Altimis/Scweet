from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from sqlalchemy import select

from Scweet.repos import AccountsRepo
from Scweet.schema import AccountTable
from Scweet.storage import session_scope


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _find_account(db_path: str, username: str) -> dict:
    with session_scope(db_path) as session:
        stmt = select(AccountTable).where(AccountTable.username == username).limit(1)
        record = session.execute(stmt).scalar_one()
        return {column.name: getattr(record, column.name) for column in AccountTable.__table__.columns}


def _read_accounts(db_path: str) -> list[dict]:
    with session_scope(db_path) as session:
        rows = session.execute(select(AccountTable).order_by(AccountTable.id.asc())).scalars().all()
        out: list[dict] = []
        for row in rows:
            out.append(
                {
                    "id": row.id,
                    "username": row.username,
                    "auth_token": row.auth_token,
                    "csrf": row.csrf,
                    "bearer": row.bearer,
                    "cookies_json": row.cookies_json,
                    "status": row.status,
                    "available_til": row.available_til,
                    "daily_requests": row.daily_requests,
                    "daily_tweets": row.daily_tweets,
                    "total_tweets": row.total_tweets,
                    "last_reset_date": row.last_reset_date,
                    "last_used": row.last_used,
                    "busy": row.busy,
                    "lease_id": row.lease_id,
                    "lease_expires_at": row.lease_expires_at,
                    "cooldown_reason": row.cooldown_reason,
                    "last_error_code": row.last_error_code,
                }
            )
        return out


# ── Leasing tests ──────────────────────────────────────────────────────


def test_eligibility_filtering_and_lease_lifecycle(tmp_path):
    db_path = str(tmp_path / "accounts.db")
    now_ts = 1_700_000_000.0

    repo = AccountsRepo(db_path, lease_ttl_s=90, daily_pages_limit=3, daily_tweets_limit=5)

    repo.upsert_account({"username": "eligible_a", "status": 1, "last_used": 100.0})
    repo.upsert_account({"username": "disabled", "status": 0, "last_used": 90.0})
    repo.upsert_account({"username": "cooldown", "status": 1, "available_til": now_ts + 50, "last_used": 80.0})
    repo.upsert_account(
        {
            "username": "leased_busy",
            "status": 1,
            "lease_id": "busy-lease",
            "lease_expires_at": now_ts + 50,
            "last_used": 70.0,
        }
    )
    repo.upsert_account(
        {
            "username": "leased_expired",
            "status": 1,
            "lease_id": "old-lease",
            "lease_expires_at": now_ts - 1,
            "last_used": 60.0,
        }
    )
    repo.upsert_account(
        {
            "username": "daily_limit_hit",
            "status": 1,
            "last_reset_date": _today(),
            "daily_requests": 3,
            "daily_tweets": 2,
            "last_used": 50.0,
        }
    )

    assert repo.count_eligible(now_ts=now_ts) == 2

    leases = repo.acquire_leases(2, run_id="run-1", worker_id_prefix="w", now_ts=now_ts)
    assert len(leases) == 2
    leased_usernames = {item["username"] for item in leases}
    assert leased_usernames == {"eligible_a", "leased_expired"}

    first_lease_id = leases[0]["lease_id"]
    assert first_lease_id

    before_hb = time.time()
    assert repo.heartbeat(first_lease_id, extend_by_s=180) is True
    after_hb = time.time()
    assert repo.heartbeat("missing-lease", extend_by_s=30) is False

    updated = _find_account(db_path, leases[0]["username"])
    assert before_hb + 180 <= updated["lease_expires_at"] <= after_hb + 180

    released = repo.release(
        first_lease_id,
        fields_to_set={"available_til": now_ts + 120, "cooldown_reason": "rate_limit"},
        fields_to_inc={"daily_requests": 1},
    )
    assert released is True

    updated = _find_account(db_path, leases[0]["username"])
    assert updated["lease_id"] is None
    assert updated["lease_expires_at"] is None
    assert updated["available_til"] == now_ts + 120
    assert updated["cooldown_reason"] == "rate_limit"
    assert updated["daily_requests"] == 1

    assert repo.count_eligible(now_ts=now_ts) == 0


def test_record_usage_applies_daily_reset_and_totals(tmp_path):
    db_path = str(tmp_path / "usage.db")
    repo = AccountsRepo(db_path, lease_ttl_s=60, daily_pages_limit=100, daily_tweets_limit=100)

    now_ts = 1_700_000_500.0
    repo.upsert_account(
        {
            "username": "usage_user",
            "status": 1,
            "last_reset_date": "2000-01-01",
            "daily_requests": 90,
            "daily_tweets": 70,
            "total_tweets": 11,
            "last_used": 1.0,
        }
    )

    leases = repo.acquire_leases(1, run_id="run-usage", worker_id_prefix="u", now_ts=now_ts)
    assert len(leases) == 1
    lease_id = leases[0]["lease_id"]

    repo.record_usage(lease_id, pages=2, tweets=3)

    updated = _find_account(db_path, "usage_user")
    assert updated["last_reset_date"] == _today()
    assert updated["daily_requests"] == 2
    assert updated["daily_tweets"] == 3
    assert updated["total_tweets"] == 14


def test_require_auth_material_filters_out_accounts_missing_auth_fields(tmp_path):
    db_path = str(tmp_path / "require_auth.db")
    repo = AccountsRepo(
        db_path,
        lease_ttl_s=60,
        daily_pages_limit=100,
        daily_tweets_limit=100,
        require_auth_material=True,
        default_bearer_token="bearer-default",
    )
    now_ts = 1_700_100_000.0

    repo.upsert_account(
        {
            "username": "valid",
            "status": 1,
            "auth_token": "tok-valid",
            "csrf": "csrf-valid",
            "bearer": "bearer-valid",
            "cookies_json": {"auth_token": "tok-valid", "ct0": "csrf-valid"},
            "last_used": 10.0,
        }
    )
    repo.upsert_account(
        {
            "username": "missing_csrf",
            "status": 1,
            "auth_token": "tok-missing",
            "cookies_json": {"auth_token": "tok-missing"},
            "last_used": 1.0,
        }
    )

    assert repo.count_eligible(now_ts=now_ts) == 1

    leases = repo.acquire_leases(2, run_id="run-auth", worker_id_prefix="w", now_ts=now_ts)
    assert len(leases) == 1
    assert leases[0]["username"] == "valid"


# ── Upsert / merge tests ──────────────────────────────────────────────


def test_upsert_partial_record_does_not_wipe_existing_auth_material_or_counters(tmp_path):
    db_path = str(tmp_path / "merge.db")
    repo = AccountsRepo(db_path)

    repo.upsert_account(
        {
            "username": "user1",
            "auth_token": "tok-1",
            "csrf": "csrf-1",
            "bearer": "bearer-1",
            "cookies_json": {"auth_token": "tok-1", "ct0": "csrf-1", "k": "v"},
            "status": 1,
            "daily_requests": 7,
            "daily_tweets": 3,
            "total_tweets": 11,
            "last_reset_date": "2026-02-01",
            "last_used": 123.0,
            "busy": True,
            "lease_id": "lease-1",
            "lease_expires_at": 999.0,
            "cooldown_reason": "rate_limit",
            "last_error_code": 429,
        }
    )

    repo.upsert_account(
        {
            "username": "user1",
            "auth_token": None,
            "csrf": None,
            "bearer": None,
            "cookies_json": None,
            "status": 0,
            "daily_requests": 0,
            "daily_tweets": 0,
            "total_tweets": 0,
            "last_used": 0.0,
            "busy": False,
            "lease_id": None,
            "lease_expires_at": None,
        }
    )

    rows = _read_accounts(db_path)
    assert len(rows) == 1
    row = rows[0]

    assert row["auth_token"] == "tok-1"
    assert row["csrf"] == "csrf-1"
    assert row["bearer"] == "bearer-1"
    cookies = json.loads(row["cookies_json"])
    assert cookies["auth_token"] == "tok-1"
    assert cookies["ct0"] == "csrf-1"
    assert cookies["k"] == "v"

    assert row["status"] == 1
    assert row["daily_requests"] == 7
    assert row["daily_tweets"] == 3
    assert row["total_tweets"] == 11
    assert row["last_reset_date"] == "2026-02-01"
    assert row["last_used"] == 123.0
    assert row["busy"] is True
    assert row["lease_id"] == "lease-1"
    assert row["lease_expires_at"] == 999.0
    assert row["cooldown_reason"] == "rate_limit"
    assert row["last_error_code"] == 429


def test_upsert_same_auth_token_under_different_username_merges_and_renames_synthetic(tmp_path):
    db_path = str(tmp_path / "dedup.db")
    repo = AccountsRepo(db_path)

    repo.upsert_account(
        {
            "username": "auth_deadbeef0000",
            "auth_token": "tok-dup",
            "cookies_json": {"auth_token": "tok-dup"},
            "status": 1,
        }
    )

    repo.upsert_account(
        {
            "username": "realuser",
            "auth_token": "tok-dup",
            "csrf": "csrf-dup",
            "cookies_json": {"auth_token": "tok-dup", "ct0": "csrf-dup", "extra": "1"},
            "status": 1,
        }
    )

    rows = _read_accounts(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["username"] == "realuser"
    assert row["auth_token"] == "tok-dup"
    assert row["csrf"] == "csrf-dup"
    cookies = json.loads(row["cookies_json"])
    assert cookies["ct0"] == "csrf-dup"
    assert cookies["extra"] == "1"


def test_upsert_better_auth_material_upgrades_partial_without_losing_existing_cookie_keys(tmp_path):
    db_path = str(tmp_path / "upgrade.db")
    repo = AccountsRepo(db_path)

    repo.upsert_account(
        {
            "username": "upgrade_user",
            "auth_token": "tok-old",
            "cookies_json": {"auth_token": "tok-old", "existing_only": "x"},
            "status": 1,
        }
    )

    repo.upsert_account(
        {
            "username": "upgrade_user",
            "auth_token": "tok-new",
            "csrf": "csrf-new",
            "cookies_json": {"auth_token": "tok-new", "ct0": "csrf-new", "keep": "y"},
            "status": 1,
        }
    )

    rows = _read_accounts(db_path)
    assert len(rows) == 1
    row = rows[0]

    assert row["auth_token"] == "tok-new"
    assert row["csrf"] == "csrf-new"
    cookies = json.loads(row["cookies_json"])
    assert cookies["auth_token"] == "tok-new"
    assert cookies["ct0"] == "csrf-new"
    assert cookies["keep"] == "y"
    assert cookies["existing_only"] == "x"
