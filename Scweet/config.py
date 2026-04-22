from __future__ import annotations

import json
from enum import Enum
from typing import Any, Optional, Union

from pydantic import BaseModel, Field, field_validator


class ApiHttpMode(str, Enum):
    AUTO = "auto"
    ASYNC = "async"
    SYNC = "sync"


class ScweetConfig(BaseModel):
    # Core
    db_path: str = "scweet_state.db"
    proxy: Optional[Union[dict[str, Any], str]] = None
    concurrency: int = Field(default=5, ge=1)

    # Output
    save_dir: str = "outputs"
    save_format: str = "csv"  # "csv" | "json" | "both"

    # HTTP tuning
    api_http_mode: ApiHttpMode = ApiHttpMode.AUTO
    api_http_impersonate: Optional[str] = None
    api_user_agent: Optional[str] = None

    # Rate limiting
    daily_requests_limit: int = Field(default=30, ge=1)
    daily_tweets_limit: int = Field(default=600, ge=1)
    max_empty_pages: int = Field(default=1, ge=1)
    api_page_size: int = Field(default=20, ge=1, le=100)
    min_delay_s: float = Field(default=2.0, ge=0.0)

    # Advanced
    enable_wal: bool = True
    busy_timeout_ms: int = Field(default=5000, ge=0)
    lease_ttl_s: int = Field(default=120, ge=1)
    lease_heartbeat_s: float = Field(default=30.0, ge=0.0)
    cooldown_default_s: float = Field(default=120.0, ge=0.0)
    transient_cooldown_s: float = Field(default=120.0, ge=0.0)
    auth_cooldown_s: float = Field(default=30 * 24 * 60 * 60, ge=0.0)
    cooldown_jitter_s: float = Field(default=10.0, ge=0.0)
    requests_per_min: int = Field(default=30, ge=1)
    task_retry_base_s: int = Field(default=1, ge=0)
    task_retry_max_s: int = Field(default=30, ge=0)
    max_task_attempts: int = Field(default=3, ge=1)
    max_fallback_attempts: int = Field(default=3, ge=1)
    max_account_switches: int = Field(default=2, ge=0)
    scheduler_min_interval_s: int = Field(default=300, ge=1)
    scheduler_max_interval_s: Optional[int] = Field(default=None, ge=1)
    scheduler_exponential_count: int = Field(default=10, ge=1)
    scheduler_exponential_growth: float = Field(default=2.0, gt=1.0)
    scheduler_exponential_min_s: int = Field(default=900, ge=1)
    scheduler_exponential_max_s: int = Field(default=432000, ge=1)
    n_splits: int = Field(default=5, ge=1)
    priority: int = 1
    proxy_check_on_lease: bool = True
    proxy_check_url: str = "https://x.com/robots.txt"
    proxy_check_timeout_s: float = Field(default=10.0, ge=0.0)
    profile_timeline_allow_anonymous: bool = False

    # Manifest
    manifest_url: Optional[str] = None
    manifest_ttl_s: int = Field(default=3600, ge=1)
    manifest_update_on_init: bool = False
    manifest_scrape_on_init: bool = False

    @field_validator("api_http_mode", mode="before")
    @classmethod
    def _normalize_http_mode(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower()
        return value

    @field_validator("api_http_impersonate", mode="before")
    @classmethod
    def _normalize_http_impersonate(cls, value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        return text if text else None

    @field_validator("proxy", mode="before")
    @classmethod
    def _normalize_proxy(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if stripped.startswith("{") or stripped.startswith("[") or stripped.startswith('"'):
                try:
                    decoded = json.loads(stripped)
                except Exception:
                    return stripped
                return decoded
            return stripped
        return value

    @field_validator("proxy", mode="after")
    @classmethod
    def _validate_proxy(cls, value: Any) -> Any:
        if value is None:
            return None
        from .http_utils import normalize_http_proxies

        proxies = normalize_http_proxies(value)
        if proxies is None:
            raise ValueError(
                "Invalid proxy format. Expected one of: "
                "URL string ('http://host:port' or 'host:port'), "
                "dict with {'http': '...', 'https': '...'}, "
                "or dict with {'host': '...', 'port': 8080, optional 'scheme', 'username', 'password'}."
            )
        return value
