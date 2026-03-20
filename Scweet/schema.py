from __future__ import annotations

from sqlalchemy import Boolean, Column, Float, Index, Integer, String, Text
from typing import Optional

try:
    from sqlmodel import Field, SQLModel

    SQLMODEL_AVAILABLE = True
except Exception:  # pragma: no cover - exercised only when sqlmodel is missing
    SQLMODEL_AVAILABLE = False
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


if SQLMODEL_AVAILABLE:
    Base = SQLModel

    class AccountTable(SQLModel, table=True):
        __tablename__ = "accounts"
        __table_args__ = (
            Index(
                "ix_accounts_eligibility",
                "status",
                "available_til",
                "lease_expires_at",
                "last_used",
            ),
            Index("ix_accounts_cooldown", "status", "available_til"),
            Index("ix_accounts_lease_lookup", "lease_id"),
        )

        id: Optional[int] = Field(default=None, primary_key=True)
        username: str = Field(
            sa_column=Column(String(255), unique=True, index=True, nullable=False)
        )

        auth_token: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
        csrf: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
        bearer: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
        cookies_json: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
        # Optional per-account proxy override (string URL or JSON-encoded dict).
        proxy_json: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))

        status: int = Field(default=1, sa_column=Column(Integer, index=True, nullable=False))
        available_til: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True, index=True))

        lease_id: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True, index=True))
        lease_run_id: Optional[str] = Field(default=None, sa_column=Column(String(64), nullable=True))
        lease_worker_id: Optional[str] = Field(default=None, sa_column=Column(String(128), nullable=True))
        lease_acquired_at: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
        lease_expires_at: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True, index=True))
        busy: bool = Field(default=False, sa_column=Column(Boolean, index=True, nullable=False))

        daily_requests: int = Field(default=0, sa_column=Column(Integer, nullable=False))
        daily_tweets: int = Field(default=0, sa_column=Column(Integer, nullable=False))
        last_reset_date: Optional[str] = Field(default=None, sa_column=Column(String(10), nullable=True))
        total_tweets: int = Field(default=0, sa_column=Column(Integer, nullable=False))

        last_used: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True, index=True))
        last_error_code: Optional[int] = Field(default=None, sa_column=Column(Integer, nullable=True))
        cooldown_reason: Optional[str] = Field(default=None, sa_column=Column(String(128), nullable=True))


    class RunTable(SQLModel, table=True):
        __tablename__ = "runs"

        id: Optional[int] = Field(default=None, primary_key=True)
        run_id: str = Field(sa_column=Column(String(64), unique=True, index=True, nullable=False))
        status: str = Field(default="running", sa_column=Column(String(32), index=True, nullable=False))
        started_at: float = Field(sa_column=Column(Float, index=True, nullable=False))
        finished_at: Optional[float] = Field(default=None, sa_column=Column(Float, nullable=True))
        query_hash: str = Field(sa_column=Column(String(128), index=True, nullable=False))
        tweets_count: int = Field(default=0, sa_column=Column(Integer, nullable=False))
        input_json: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
        stats_json: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))


    class ResumeStateTable(SQLModel, table=True):
        __tablename__ = "resume_state"
        __table_args__ = (
            Index("ix_resume_lookup", "query_hash", "updated_at"),
        )

        id: Optional[int] = Field(default=None, primary_key=True)
        run_id: str = Field(default="", sa_column=Column(String(64), index=True, nullable=False))
        query_hash: str = Field(sa_column=Column(String(128), unique=True, index=True, nullable=False))
        cursor: Optional[str] = Field(default=None, sa_column=Column(Text, nullable=True))
        since: str = Field(sa_column=Column(String(32), nullable=False))
        until: str = Field(sa_column=Column(String(32), nullable=False))
        updated_at: float = Field(sa_column=Column(Float, index=True, nullable=False))


    class ManifestCacheTable(SQLModel, table=True):
        __tablename__ = "manifest_cache"

        id: Optional[int] = Field(default=None, primary_key=True)
        key: str = Field(sa_column=Column(String(255), unique=True, index=True, nullable=False))
        manifest_json: str = Field(sa_column=Column(Text, nullable=False))
        fetched_at: float = Field(sa_column=Column(Float, index=True, nullable=False))
        expires_at: float = Field(sa_column=Column(Float, index=True, nullable=False))
        etag: Optional[str] = Field(default=None, sa_column=Column(String(255), nullable=True))

else:
    class Base(DeclarativeBase):
        pass


    class AccountTable(Base):
        __tablename__ = "accounts"
        __table_args__ = (
            Index(
                "ix_accounts_eligibility",
                "status",
                "available_til",
                "lease_expires_at",
                "last_used",
            ),
            Index("ix_accounts_cooldown", "status", "available_til"),
            Index("ix_accounts_lease_lookup", "lease_id"),
        )

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        username: Mapped[str] = mapped_column(String(255), unique=True, index=True)

        auth_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        csrf: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        bearer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        cookies_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        proxy_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

        status: Mapped[int] = mapped_column(Integer, default=1, index=True)
        available_til: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)

        lease_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
        lease_run_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
        lease_worker_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
        lease_acquired_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
        lease_expires_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
        busy: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

        daily_requests: Mapped[int] = mapped_column(Integer, default=0)
        daily_tweets: Mapped[int] = mapped_column(Integer, default=0)
        last_reset_date: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
        total_tweets: Mapped[int] = mapped_column(Integer, default=0)

        last_used: Mapped[Optional[float]] = mapped_column(Float, nullable=True, index=True)
        last_error_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
        cooldown_reason: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)


    class RunTable(Base):
        __tablename__ = "runs"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        run_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
        status: Mapped[str] = mapped_column(String(32), default="running", index=True)
        started_at: Mapped[float] = mapped_column(Float, index=True)
        finished_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
        query_hash: Mapped[str] = mapped_column(String(128), index=True)
        tweets_count: Mapped[int] = mapped_column(Integer, default=0)
        input_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        stats_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


    class ResumeStateTable(Base):
        __tablename__ = "resume_state"
        __table_args__ = (
            Index("ix_resume_lookup", "query_hash", "updated_at"),
        )

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        run_id: Mapped[str] = mapped_column(String(64), default="", index=True)
        query_hash: Mapped[str] = mapped_column(String(128), unique=True, index=True)
        cursor: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
        since: Mapped[str] = mapped_column(String(32))
        until: Mapped[str] = mapped_column(String(32))
        updated_at: Mapped[float] = mapped_column(Float, index=True)


    class ManifestCacheTable(Base):
        __tablename__ = "manifest_cache"

        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
        key: Mapped[str] = mapped_column(String(255), unique=True, index=True)
        manifest_json: Mapped[str] = mapped_column(Text)
        fetched_at: Mapped[float] = mapped_column(Float, index=True)
        expires_at: Mapped[float] = mapped_column(Float, index=True)
        etag: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
