from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select

from Scweet.auth import (
    bootstrap_cookies_from_auth_token,
    import_accounts_to_db,
    load_accounts_txt,
    load_cookies_json,
    normalize_account_record,
)
from Scweet.models import SearchRequest, SearchResult, TweetRecord, TweetUser
from Scweet.repos import AccountsRepo
from Scweet.runner import Runner
from Scweet.schema import AccountTable
from Scweet.storage import session_scope


REQUIRED_CANONICAL_KEYS = {
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
}


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def _write_json(path: Path, payload) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _read_account_rows(db_path: str) -> list[dict]:
    with session_scope(db_path) as session:
        rows = session.execute(select(AccountTable).order_by(AccountTable.username.asc())).scalars().all()
        return [
            {
                "username": row.username,
                "auth_token": row.auth_token,
                "cookies_json": row.cookies_json,
                "csrf": row.csrf,
                "bearer": row.bearer,
                "status": row.status,
                "cooldown_reason": row.cooldown_reason,
                "last_error_code": row.last_error_code,
            }
            for row in rows
        ]


def _read_account(db_path: str, username: str) -> dict:
    with session_scope(db_path) as session:
        stmt = select(AccountTable).where(AccountTable.username == username).limit(1)
        row = session.execute(stmt).scalar_one()
        return {column.name: getattr(row, column.name) for column in AccountTable.__table__.columns}


def _read_account_by_auth_token(db_path: str, auth_token: str) -> dict:
    with session_scope(db_path) as session:
        stmt = select(AccountTable).where(AccountTable.auth_token == auth_token).limit(1)
        row = session.execute(stmt).scalar_one()
        return {column.name: getattr(row, column.name) for column in AccountTable.__table__.columns}


# ── Parsing tests ──────────────────────────────────────────────────────


def test_load_accounts_txt_parses_valid_partial_comment_and_empty_lines(tmp_path):
    path = _write(
        tmp_path / "accounts.txt",
        "\n".join(
            [
                "# comment line",
                "",
                "alice:pass:alice@example.com:mailpass:2fa-code:token-alice",
                "bob:::::token-bob",
                "charlie:secret",
                'dave:::::token-dave\t{"host":"127.0.0.1","port":8080}',
                ":::::",
            ]
        ),
    )

    records = load_accounts_txt(str(path))

    assert [record["username"] for record in records] == ["alice", "bob", "charlie", "dave"]
    assert records[0]["auth_token"] == "token-alice"
    assert records[1]["auth_token"] == "token-bob"
    assert records[2].get("password") == "secret"
    assert records[3]["proxy_json"] == {"host": "127.0.0.1", "port": 8080}
    for record in records:
        assert REQUIRED_CANONICAL_KEYS.issubset(record.keys())


def test_load_cookies_json_supports_list_and_object_forms(tmp_path):
    list_path = _write_json(
        tmp_path / "cookies_list.json",
        [
            {"username": "a", "cookies": {"auth_token": "tok-a", "ct0": "csrf-a"}},
            {
                "user": "b",
                "cookies": [
                    {"name": "auth_token", "value": "tok-b"},
                    {"name": "ct0", "value": "csrf-b"},
                ],
            },
        ],
    )
    object_path = _write_json(
        tmp_path / "cookies_object.json",
        {
            "accounts": [{"username": "c", "cookies_json": {"auth_token": "tok-c"}}],
            "ignored": True,
        },
    )
    mapping_path = _write_json(
        tmp_path / "cookies_mapping.json",
        {
            "d": {"cookies": {"auth_token": "tok-d", "ct0": "csrf-d"}},
            "e": [{"name": "auth_token", "value": "tok-e"}],
        },
    )

    list_records = load_cookies_json(str(list_path))
    object_records = load_cookies_json(str(object_path))
    mapping_records = load_cookies_json(str(mapping_path))

    assert [r["username"] for r in list_records] == ["a", "b"]
    assert list_records[0]["auth_token"] == "tok-a"
    assert list_records[0]["csrf"] == "csrf-a"
    assert list_records[1]["auth_token"] == "tok-b"
    assert list_records[1]["csrf"] == "csrf-b"

    assert [r["username"] for r in object_records] == ["c"]
    assert object_records[0]["auth_token"] == "tok-c"

    assert {r["username"] for r in mapping_records} == {"d", "e"}


def test_load_cookies_json_supports_netscape_cookies_txt(tmp_path):
    cookies_txt = _write(
        tmp_path / "cookies.txt",
        "\n".join(
            [
                "# Netscape HTTP Cookie File",
                ".x.com\tTRUE\t/\tTRUE\t0\tauth_token\ttok-n",
                "#HttpOnly_.x.com\tTRUE\t/\tTRUE\t0\tct0\tcsrf-n",
                "",
            ]
        ),
    )

    records = load_cookies_json(str(cookies_txt))
    assert len(records) == 1
    record = records[0]
    assert record["auth_token"] == "tok-n"
    assert record["csrf"] == "csrf-n"
    assert record["cookies_json"]["auth_token"] == "tok-n"
    assert record["cookies_json"]["ct0"] == "csrf-n"
    assert str(record["username"]).startswith("auth_")


def test_normalize_account_record_maps_aliases_and_defaults():
    normalized = normalize_account_record(
        {
            "user": "alias_user",
            "token": "tok-1",
            "cookie_jar": {"auth_token": "tok-cookie", "ct0": "csrf-cookie"},
            "email_pass": "mail-pass",
            "two_fa": "2fa-code",
            "authorization": "Bearer bearer-token",
            "available_until": "1700000123",
            "daily_requests": "4",
            "daily_tweets": "9",
            "total_tweets": "13",
            "busy": "yes",
            "last_used": "1700000000.5",
        }
    )

    assert REQUIRED_CANONICAL_KEYS.issubset(normalized.keys())
    assert normalized["username"] == "alias_user"
    assert normalized["auth_token"] == "tok-1"
    assert normalized["csrf"] == "csrf-cookie"
    assert normalized["bearer"] == "bearer-token"
    assert normalized["available_til"] == 1700000123.0
    assert normalized["daily_requests"] == 4
    assert normalized["daily_tweets"] == 9
    assert normalized["total_tweets"] == 13
    assert normalized["busy"] is True
    assert normalized["last_used"] == 1700000000.5
    assert normalized["email_password"] == "mail-pass"
    assert normalized["two_fa"] == "2fa-code"

    derived = normalize_account_record({"auth_token": "only-token"})
    assert derived["username"].startswith("auth_")


# ── Import tests ───────────────────────────────────────────────────────


def test_import_accounts_to_db_upserts_from_txt_and_cookies_json(tmp_path):
    db_path = str(tmp_path / "auth_import.db")

    accounts_file = _write(
        tmp_path / "accounts.txt",
        "\n".join(["shared:::::tok-old", "solo:::::tok-solo"]),
    )
    cookies_file = _write_json(
        tmp_path / "cookies.json",
        {
            "accounts": [
                {"username": "shared", "cookies": {"auth_token": "tok-new", "ct0": "csrf-new"}},
                {"username": "cookie_only", "cookies": {"auth_token": "tok-cookie"}},
            ]
        },
    )

    processed = import_accounts_to_db(
        db_path,
        accounts_file=str(accounts_file),
        cookies_file=str(cookies_file),
        bootstrap_fn=lambda *_args, **_kwargs: None,
    )

    assert processed == 4

    rows = _read_account_rows(db_path)
    assert [row["username"] for row in rows] == ["cookie_only", "shared", "solo"]

    by_username = {row["username"]: row for row in rows}
    assert by_username["shared"]["auth_token"] == "tok-new"
    assert by_username["solo"]["auth_token"] == "tok-solo"
    assert by_username["cookie_only"]["auth_token"] == "tok-cookie"

    shared_cookies = json.loads(by_username["shared"]["cookies_json"])
    assert shared_cookies["ct0"] == "csrf-new"


# ── Bootstrap tests ────────────────────────────────────────────────────


class _FakeCookieJar:
    def __init__(self, data: dict | None = None):
        self._data = dict(data or {})

    def set(self, name, value, domain=None):
        self._data[name] = value

    def get_dict(self):
        return dict(self._data)


class _FakeResponse:
    def __init__(self, status_code: int, cookies: dict | None = None):
        self.status_code = status_code
        self.cookies = _FakeCookieJar(cookies)


class _FakeSession:
    def __init__(self, response: _FakeResponse, raise_on_get: bool = False):
        self.cookies = _FakeCookieJar()
        self._response = response
        self._raise_on_get = raise_on_get
        self.calls = []
        self.closed = False

    def get(self, url, headers=None, timeout=None, allow_redirects=True):
        self.calls.append({"url": url, "headers": headers, "timeout": timeout, "allow_redirects": allow_redirects})
        if self._raise_on_get:
            raise RuntimeError("boom")
        return self._response

    def close(self):
        self.closed = True


def test_bootstrap_cookies_from_auth_token_success_and_failure(monkeypatch):
    import Scweet.auth as auth_mod

    success_session = _FakeSession(_FakeResponse(status_code=200))
    monkeypatch.setattr(auth_mod, "_SESSION_FACTORY", lambda: success_session)

    cookies = bootstrap_cookies_from_auth_token("token-123", timeout_s=5)
    assert cookies is not None
    assert cookies["auth_token"] == "token-123"
    assert success_session.calls[0]["url"] == "https://x.com/home"
    assert success_session.calls[0]["timeout"] == 5
    assert success_session.closed is True

    failure_status_session = _FakeSession(_FakeResponse(status_code=403))
    monkeypatch.setattr(auth_mod, "_SESSION_FACTORY", lambda: failure_status_session)
    assert bootstrap_cookies_from_auth_token("token-123") is None

    failure_error_session = _FakeSession(_FakeResponse(status_code=200), raise_on_get=True)
    monkeypatch.setattr(auth_mod, "_SESSION_FACTORY", lambda: failure_error_session)
    assert bootstrap_cookies_from_auth_token("token-123") is None


def test_import_accounts_to_db_bootstraps_auth_token_only_accounts(tmp_path):
    db_path = str(tmp_path / "bootstrap_import.db")
    accounts_file = _write(tmp_path / "accounts.txt", "token_only:::::tok-only")

    calls = []

    def _fake_bootstrap(auth_token: str, timeout_s: int = 30):
        calls.append({"auth_token": auth_token, "timeout_s": timeout_s})
        return {"auth_token": auth_token, "ct0": "csrf-boot", "guest_id": "guest-1"}

    processed = import_accounts_to_db(
        db_path,
        accounts_file=str(accounts_file),
        bootstrap_timeout_s=9,
        bootstrap_fn=_fake_bootstrap,
    )

    assert processed == 1
    assert calls == [{"auth_token": "tok-only", "timeout_s": 9}]

    rows = _read_account_rows(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["username"] == "token_only"
    assert row["auth_token"] == "tok-only"
    assert row["csrf"] == "csrf-boot"
    assert row["status"] == 1
    assert row["cooldown_reason"] is None
    assert row["last_error_code"] is None

    cookies = json.loads(row["cookies_json"])
    assert cookies["auth_token"] == "tok-only"
    assert cookies["ct0"] == "csrf-boot"
    assert row["bearer"]


def test_import_accounts_to_db_marks_missing_auth_material_unusable(tmp_path):
    db_path = str(tmp_path / "unusable_import.db")
    accounts_file = _write(tmp_path / "accounts.txt", "broken:::::")

    processed = import_accounts_to_db(db_path, accounts_file=str(accounts_file), bootstrap_fn=lambda *_a, **_k: None)
    assert processed == 1

    rows = _read_account_rows(db_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["username"] == "broken"
    assert row["status"] == 0
    assert str(row["cooldown_reason"]).startswith("unusable:")
    assert row["last_error_code"] == 401


def test_import_accounts_to_db_skips_rebootstrap_when_db_already_has_good_auth(tmp_path):
    db_path = str(tmp_path / "rebootstrap.db")
    accounts_file = _write(tmp_path / "accounts.txt", "token_only:::::tok-only\n")

    calls: list[dict] = []

    def _fake_bootstrap(auth_token: str, timeout_s: int = 30):
        calls.append({"auth_token": auth_token, "timeout_s": timeout_s})
        return {"auth_token": auth_token, "ct0": "csrf-boot", "guest_id": "guest-1"}

    processed = import_accounts_to_db(
        db_path,
        accounts_file=str(accounts_file),
        bootstrap_timeout_s=9,
        bootstrap_fn=_fake_bootstrap,
    )
    assert processed == 1
    assert calls == [{"auth_token": "tok-only", "timeout_s": 9}]

    processed_again = import_accounts_to_db(
        db_path,
        accounts_file=str(accounts_file),
        bootstrap_timeout_s=9,
        bootstrap_fn=_fake_bootstrap,
    )
    assert processed_again == 1
    assert calls == [{"auth_token": "tok-only", "timeout_s": 9}]

    row = _read_account(db_path, "token_only")
    assert row["auth_token"] == "tok-only"
    assert row["csrf"] == "csrf-boot"
    cookies = json.loads(row["cookies_json"])
    assert cookies["ct0"] == "csrf-boot"


def test_import_accounts_to_db_does_not_call_token_bootstrap_when_ct0_present(tmp_path):
    db_path = str(tmp_path / "no_token_bootstrap.db")
    cookies_file = tmp_path / "cookies.json"
    cookies_file.write_text(
        json.dumps({"accounts": [{"username": "a", "cookies": {"auth_token": "tok", "ct0": "csrf"}}]}),
        encoding="utf-8",
    )

    def _should_not_call(*_args, **_kwargs):
        raise AssertionError("token bootstrap should not run when ct0 is already present")

    processed = import_accounts_to_db(
        db_path,
        cookies_file=str(cookies_file),
        bootstrap_fn=_should_not_call,
    )
    assert processed == 1


# ── Runner auth repair test ────────────────────────────────────────────


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_runner_auth_error_triggers_repair_and_updates_db(monkeypatch, tmp_path):
    db_path = str(tmp_path / "repair.db")
    repo = AccountsRepo(db_path)

    repo.upsert_account(
        {
            "username": "acct-a",
            "auth_token": "tok-a",
            "csrf": "old",
            "cookies_json": {"auth_token": "tok-a", "ct0": "old"},
            "status": 1,
            "last_reset_date": _today(),
            "last_used": 1.0,
        }
    )
    repo.upsert_account(
        {
            "username": "acct-b",
            "auth_token": "tok-b",
            "csrf": "ok",
            "cookies_json": {"auth_token": "tok-b", "ct0": "ok"},
            "status": 1,
            "last_reset_date": _today(),
            "last_used": 2.0,
        }
    )

    calls: list[str] = []

    async def _fake_bootstrap_token_async(auth_token: str, timeout_s: int = 30, **_kwargs):
        calls.append(auth_token)
        return {"auth_token": auth_token, "ct0": "csrf-repaired", "guest_id": "guest-9"}

    import Scweet.runner as runner_mod

    monkeypatch.setattr(runner_mod, "_bootstrap_token_async", _fake_bootstrap_token_async)

    class _AuthThenSuccessEngine:
        def __init__(self):
            self.calls = 0

        async def search_tweets(self, request):
            self.calls += 1
            if self.calls == 1:
                return {"result": SearchResult(), "cursor": None, "status_code": 401, "headers": {}}
            return {
                "result": SearchResult(
                    tweets=[
                        TweetRecord(
                            tweet_id="t1",
                            user=TweetUser(screen_name="alice", name="Alice"),
                            timestamp="2026-02-01T00:00:00.000Z",
                            text="ok",
                        )
                    ]
                ),
                "cursor": None,
                "status_code": 200,
                "headers": {},
            }

    runner = Runner(
        config=SimpleNamespace(
            n_splits=1, concurrency=2, scheduler_min_interval_s=300,
            task_retry_base_s=0, task_retry_max_s=0,
            max_task_attempts=2, max_fallback_attempts=2, max_account_switches=1,
            requests_per_min=10_000, min_delay_s=0.0,
            cooldown_default_s=60, transient_cooldown_s=30, auth_cooldown_s=3600,
            cooldown_jitter_s=0, priority=1, proxy=None,
        ),
        repos={"accounts_repo": repo},
        engines={"api_engine": _AuthThenSuccessEngine()},
        outputs=None,
    )

    result = asyncio.run(
        runner.run_search(
            SearchRequest(
                since="2026-02-01_00:00:00_UTC",
                until="2026-02-01_00:10:00_UTC",
                search_query="repair",
                limit=1,
            )
        )
    )

    assert result.stats.tasks_done == 1
    assert len(calls) == 1
    repaired_token = calls[0]

    updated = _read_account_by_auth_token(db_path, repaired_token)
    assert updated["status"] == 1
    assert updated["cooldown_reason"] is None
    assert updated["last_error_code"] is None
    assert updated["csrf"] == "csrf-repaired"
    cookies = json.loads(updated["cookies_json"])
    assert cookies["ct0"] == "csrf-repaired"
    assert cookies["guest_id"] == "guest-9"
