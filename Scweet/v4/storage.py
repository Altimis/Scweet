from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from .schema import Base

_ENGINE_CACHE: dict[str, Engine] = {}


def _normalize_db_path(db_path: str) -> tuple[str, str]:
    if db_path == ":memory:":
        return db_path, "sqlite:///:memory:"

    path = Path(db_path).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = str(path.resolve())
    return normalized, f"sqlite:///{normalized}"


def _apply_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


def create_sqlite_engine(db_path: str) -> Engine:
    key, db_url = _normalize_db_path(db_path)
    if key in _ENGINE_CACHE:
        return _ENGINE_CACHE[key]

    engine = create_engine(
        db_url,
        future=True,
        connect_args={"check_same_thread": False},
    )
    _apply_sqlite_pragmas(engine)
    _ENGINE_CACHE[key] = engine
    return engine


def init_db(db_path: str) -> None:
    engine = create_sqlite_engine(db_path)
    Base.metadata.create_all(engine)
    _ensure_schema(engine)


def _ensure_schema(engine: Engine) -> None:
    """Best-effort, idempotent schema migration for SQLite.

    We avoid introducing a heavyweight migration framework. For additive changes
    (new nullable columns), we use SQLite's ALTER TABLE when a column is missing.
    """

    def _has_column(conn, table: str, column: str) -> bool:
        rows = conn.exec_driver_sql(f"PRAGMA table_info({table})").fetchall()
        # PRAGMA table_info columns: cid, name, type, notnull, dflt_value, pk
        return any(str(row[1]) == column for row in rows)

    with engine.begin() as conn:
        try:
            needs_proxy = not _has_column(conn, "accounts", "proxy_json")
        except Exception:
            # If PRAGMA fails for any reason, don't block library usage.
            return
        if not needs_proxy:
            return

        try:
            conn.exec_driver_sql("ALTER TABLE accounts ADD COLUMN proxy_json TEXT")
        except Exception:
            # Another process may have raced to add the column. Re-check before failing.
            try:
                if _has_column(conn, "accounts", "proxy_json"):
                    return
            except Exception:
                pass
            raise


@contextmanager
def session_scope(db_path: str) -> Iterator[Session]:
    engine = create_sqlite_engine(db_path)
    session = Session(engine)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
