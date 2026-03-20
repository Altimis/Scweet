from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect

from Scweet.repos import ManifestRepo, ResumeRepo, RunsRepo
from Scweet.storage import create_sqlite_engine, init_db


def test_init_db_creates_expected_tables_and_pragmas(tmp_path):
    db_path = tmp_path / "state.db"
    init_db(str(db_path))

    engine = create_sqlite_engine(str(db_path))
    table_names = set(inspect(engine).get_table_names())
    assert {"accounts", "runs", "resume_state", "manifest_cache"}.issubset(table_names)

    with engine.connect() as conn:
        journal_mode = str(conn.exec_driver_sql("PRAGMA journal_mode").scalar()).lower()
        busy_timeout = int(conn.exec_driver_sql("PRAGMA busy_timeout").scalar())
        foreign_keys = int(conn.exec_driver_sql("PRAGMA foreign_keys").scalar())

    assert journal_mode == "wal"
    assert busy_timeout == 5000
    assert foreign_keys == 1


def test_init_db_migrates_accounts_table_adds_proxy_json_column(tmp_path):
    db_path = tmp_path / "migrate.db"
    engine = create_sqlite_engine(str(db_path))

    # Simulate an older accounts table that predates the proxy_json column.
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "\n".join(
                [
                    "CREATE TABLE accounts (",
                    "  id INTEGER PRIMARY KEY,",
                    "  username VARCHAR(255) NOT NULL,",
                    "  auth_token TEXT,",
                    "  csrf TEXT,",
                    "  bearer TEXT,",
                    "  cookies_json TEXT,",
                    "  status INTEGER NOT NULL DEFAULT 1,",
                    "  available_til FLOAT,",
                    "  lease_id VARCHAR(64),",
                    "  lease_run_id VARCHAR(64),",
                    "  lease_worker_id VARCHAR(128),",
                    "  lease_acquired_at FLOAT,",
                    "  lease_expires_at FLOAT,",
                    "  busy BOOLEAN NOT NULL DEFAULT 0,",
                    "  daily_requests INTEGER NOT NULL DEFAULT 0,",
                    "  daily_tweets INTEGER NOT NULL DEFAULT 0,",
                    "  last_reset_date VARCHAR(10),",
                    "  total_tweets INTEGER NOT NULL DEFAULT 0,",
                    "  last_used FLOAT,",
                    "  last_error_code INTEGER,",
                    "  cooldown_reason VARCHAR(128)",
                    ");",
                ]
            )
        )
        conn.exec_driver_sql("CREATE UNIQUE INDEX ux_accounts_username ON accounts(username);")

    init_db(str(db_path))

    columns = {col["name"] for col in inspect(engine).get_columns("accounts")}
    assert "proxy_json" in columns


def test_runs_repo_create_and_finalize(tmp_path):
    db_path = tmp_path / "runs.db"
    runs_repo = RunsRepo(str(db_path))

    run_id = runs_repo.create_run("query-hash", {"words": ["btc"]})
    assert run_id

    runs_repo.finalize_run(run_id, status="finished", tweets_count=42, stats={"pages": 2})


def test_resume_repo_save_get_clear_checkpoint(tmp_path):
    db_path = tmp_path / "resume.db"
    repo = ResumeRepo(str(db_path))

    assert repo.get_checkpoint("q1") is None

    repo.save_checkpoint("q1", "cursor-a", "2025-01-01", "2025-01-02")
    checkpoint = repo.get_checkpoint("q1")
    assert checkpoint is not None
    assert checkpoint["query_hash"] == "q1"
    assert checkpoint["cursor"] == "cursor-a"
    assert checkpoint["since"] == "2025-01-01"
    assert checkpoint["until"] == "2025-01-02"

    repo.save_checkpoint("q1", "cursor-b", "2025-01-03", "2025-01-04")
    checkpoint = repo.get_checkpoint("q1")
    assert checkpoint is not None
    assert checkpoint["cursor"] == "cursor-b"
    assert checkpoint["since"] == "2025-01-03"
    assert checkpoint["until"] == "2025-01-04"

    repo.clear_checkpoint("q1")
    assert repo.get_checkpoint("q1") is None


def test_manifest_repo_cache_ttl_behavior(tmp_path):
    db_path = tmp_path / "manifest.db"
    repo = ManifestRepo(str(db_path))

    assert repo.get_cached("main") is None

    repo.set_cached("main", {"featureFlags": {"x": True}}, ttl_s=10, etag="v1")
    cached = repo.get_cached("main")
    assert cached is not None
    assert cached["manifest"] == {"featureFlags": {"x": True}}
    assert cached["etag"] == "v1"

    repo.set_cached("main", {"featureFlags": {"x": False}}, ttl_s=0, etag="v2")
    assert repo.get_cached("main") is None
