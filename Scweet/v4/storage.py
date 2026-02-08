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
