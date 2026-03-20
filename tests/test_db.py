from __future__ import annotations

import json

from sqlalchemy import select

from Scweet import ScweetDB
from Scweet.repos import AccountsRepo
from Scweet.schema import AccountTable
from Scweet.storage import session_scope


def test_scweet_db_accounts_lifecycle(tmp_path):
    db_path = tmp_path / "state.db"
    db = ScweetDB(str(db_path))

    summary = db.accounts_summary()
    assert summary["total"] == 0
    assert summary["eligible"] == 0

    result = db.import_accounts_from_sources(cookies={"auth_token": "token-a", "ct0": "csrf-a"})
    assert result["processed"] == 1
    assert result["eligible"] == 1

    accounts = db.list_accounts(limit=10, include_cookies=True)
    assert len(accounts) == 1
    assert accounts[0]["username"]
    assert "auth_token" not in accounts[0]
    assert accounts[0]["auth_token_fp"] != "-"
    assert isinstance(accounts[0]["cookies_keys"], list)

    username = accounts[0]["username"]
    assert db.get_account(username) is not None

    updated = db.mark_account_unusable(username, reason="test")["updated"]
    assert updated == 1

    db.reset_account_cooldowns(include_unusable=True)
    refreshed = db.get_account(username)
    assert refreshed is not None
    assert int(refreshed["status"] or 0) != 0

    deleted = db.delete_account(username)["deleted"]
    assert deleted == 1


def test_collapse_duplicates_by_auth_token_merges_and_renames(tmp_path):
    db_path = str(tmp_path / "dedup.db")
    repo = AccountsRepo(db_path)

    with session_scope(db_path) as session:
        session.add(
            AccountTable(
                username="auth_deadbeef",
                auth_token="tok-dup",
                csrf="csrf-dup",
                cookies_json=json.dumps(
                    {"auth_token": "tok-dup", "ct0": "csrf-dup", "foo": "bar"},
                    separators=(",", ":"),
                ),
                status=1,
                last_used=10.0,
            )
        )
        session.add(
            AccountTable(
                username="realuser",
                auth_token="tok-dup",
                csrf="csrf-dup",
                cookies_json=json.dumps(
                    {"auth_token": "tok-dup", "ct0": "csrf-dup", "guest_id": "g"},
                    separators=(",", ":"),
                ),
                status=1,
                last_used=1.0,
            )
        )
        session.flush()

    dry = repo.collapse_duplicates_by_auth_token(dry_run=True)
    assert dry["groups"] == 1
    assert dry["rows_to_delete"] == 1
    assert dry["plan"][0]["rename_to"] == "realuser"

    applied = repo.collapse_duplicates_by_auth_token(dry_run=False)
    assert applied["deleted_rows"] == 1
    assert applied["updated_rows"] == 1
    assert applied["renamed_rows"] == 1

    with session_scope(db_path) as session:
        rows = list(session.execute(select(AccountTable)).scalars().all())
        assert len(rows) == 1
        row = rows[0]
        assert row.username == "realuser"
        cookies = json.loads(row.cookies_json)
        assert cookies["auth_token"] == "tok-dup"
        assert cookies["ct0"] == "csrf-dup"
        assert cookies["foo"] == "bar"
        assert cookies["guest_id"] == "g"
