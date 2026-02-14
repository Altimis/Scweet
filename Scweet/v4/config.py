from __future__ import annotations

import json
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator


class EngineKind(str, Enum):
    API = "api"
    BROWSER = "browser"
    AUTO = "auto"


class ApiHttpMode(str, Enum):
    AUTO = "auto"
    ASYNC = "async"
    SYNC = "sync"


class ResumeMode(str, Enum):
    LEGACY_CSV = "legacy_csv"
    DB_CURSOR = "db_cursor"
    HYBRID_SAFE = "hybrid_safe"


class BootstrapStrategy(str, Enum):
    AUTO = "auto"
    TOKEN_ONLY = "token_only"
    NODRIVER_ONLY = "nodriver_only"
    NONE = "none"


class EngineConfig(BaseModel):
    kind: EngineKind = EngineKind.BROWSER
    api_http_mode: ApiHttpMode = ApiHttpMode.AUTO
    # curl_cffi "impersonate" value for API HTTP sessions (and transaction-id bootstrap).
    # If unset, curl_cffi defaults (or SCWEET_HTTP_IMPERSONATE env) are used.
    api_http_impersonate: Optional[str] = None

    @field_validator("kind", mode="before")
    @classmethod
    def _normalize_kind(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower()
        return value

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


class StorageConfig(BaseModel):
    db_path: str = "scweet_state.db"
    enable_wal: bool = True
    busy_timeout_ms: int = Field(default=5000, ge=0)


class AccountsConfig(BaseModel):
    accounts_file: Optional[str] = None
    cookies_file: Optional[str] = None
    cookies_path: Optional[str] = None
    env_path: Optional[str] = None
    # Accept the legacy `cookies=` payload without forcing a particular shape.
    # Normalization is handled by v4 auth loaders (load_cookies_payload/normalize_account_record).
    cookies: Any = None
    provision_on_init: bool = True
    bootstrap_strategy: BootstrapStrategy = BootstrapStrategy.AUTO

    @field_validator("bootstrap_strategy", mode="before")
    @classmethod
    def _normalize_bootstrap_strategy(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower()
        return value


class PoolConfig(BaseModel):
    n_splits: int = Field(default=5, ge=1)
    concurrency: int = Field(default=5, ge=1)


class RuntimeConfig(BaseModel):
    # Used for:
    # - nodriver bootstrap (dict host/port[/username/password])
    # - API HTTP proxying (string URL or requests-style proxies dict)
    proxy: Optional[dict[str, Any] | str] = None
    # Used by nodriver bootstrap/login only.
    user_agent: Optional[str] = None
    # Used by API HTTP requests. If unset, curl_cffi uses its built-in UA/impersonation defaults.
    api_user_agent: Optional[str] = None
    disable_images: bool = False
    headless: bool = True
    scroll_ratio: int = Field(default=30, ge=1)
    code_callback: Optional[Any] = None
    strict: bool = False

    @field_validator("proxy", mode="before")
    @classmethod
    def _normalize_proxy(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            # Allow passing JSON-encoded proxy dicts as strings.
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


class OperationalConfig(BaseModel):
    account_lease_ttl_s: int = Field(default=120, ge=1)
    account_lease_heartbeat_s: float = Field(default=30.0, ge=0.0)
    # Optional proxy smoke-check when leasing/building account sessions (helps fail fast on bad proxies).
    proxy_check_on_lease: bool = True
    # Default points to an IP-echo endpoint to validate proxy egress is working.
    proxy_check_url: str = "https://x.com/robots.txt"
    proxy_check_timeout_s: float = Field(default=10.0, ge=0.0)
    # Per-account daily caps (used for lease eligibility). These reset by UTC date.
    account_daily_requests_limit: int = Field(default=30, ge=1)
    account_daily_tweets_limit: int = Field(default=600, ge=1)
    cooldown_default_s: float = Field(default=120.0, ge=0.0)
    transient_cooldown_s: float = Field(default=120.0, ge=0.0)
    auth_cooldown_s: float = Field(default=30 * 24 * 60 * 60, ge=0.0)
    cooldown_jitter_s: float = Field(default=10.0, ge=0.0)
    account_requests_per_min: int = Field(default=30, ge=1)
    account_min_delay_s: float = Field(default=2.0, ge=0.0)
    api_page_size: int = Field(default=20, ge=1, le=100)
    max_empty_pages: int = Field(default=1, ge=1)
    task_retry_base_s: int = Field(default=1, ge=0)
    task_retry_max_s: int = Field(default=30, ge=0)
    max_task_attempts: int = Field(default=3, ge=1)
    max_fallback_attempts: int = Field(default=3, ge=1)
    max_account_switches: int = Field(default=2, ge=0)
    # Allow unauthenticated profile timeline scraping (best-effort, typically limited depth/pages).
    profile_timeline_allow_anonymous: bool = False
    scheduler_min_interval_s: int = Field(default=300, ge=1)
    priority: int = 1


class ResumeConfig(BaseModel):
    mode: ResumeMode = ResumeMode.HYBRID_SAFE

    @field_validator("mode", mode="before")
    @classmethod
    def _normalize_mode(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.lower()
        return value


class OutputConfig(BaseModel):
    save_dir: str = "outputs"
    format: str = "csv"
    dedupe_on_resume_by_tweet_id: bool = False


class ManifestConfig(BaseModel):
    manifest_url: Optional[str] = None
    ttl_s: int = Field(default=3600, ge=1)
    update_on_init: bool = False


class ScweetConfig(BaseModel):
    engine: EngineConfig = Field(default_factory=EngineConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    accounts: AccountsConfig = Field(default_factory=AccountsConfig)
    pool: PoolConfig = Field(default_factory=PoolConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    operations: OperationalConfig = Field(default_factory=OperationalConfig)
    resume: ResumeConfig = Field(default_factory=ResumeConfig)
    output: OutputConfig = Field(default_factory=OutputConfig)
    manifest: ManifestConfig = Field(default_factory=ManifestConfig)

    @classmethod
    def from_sources(
        cls,
        *,
        db_path: str = "scweet_state.db",
        accounts_file: Optional[str] = None,
        cookies_file: Optional[str] = None,
        env_path: Optional[str] = None,
        cookies: Any = None,
        manifest_url: Optional[str] = None,
        update_manifest: bool = False,
        bootstrap_strategy: BootstrapStrategy | str = BootstrapStrategy.AUTO,
        provision_on_init: bool = True,
        strict: bool = False,
        proxy: Any = None,
        user_agent: Optional[str] = None,
        api_user_agent: Optional[str] = None,
        resume_mode: ResumeMode | str = ResumeMode.HYBRID_SAFE,
        output_format: Optional[str] = None,
        api_http_mode: ApiHttpMode | str = ApiHttpMode.AUTO,
        api_http_impersonate: Optional[str] = None,
        n_splits: Optional[int] = None,
        concurrency: Optional[int] = None,
        overrides: Any = None,
    ) -> "ScweetConfig":
        """Build a ScweetConfig from common sources and a small set of knobs.

        This is the recommended "clean" entrypoint for v4 configuration. For advanced
        tuning (lease params, cooldowns, scheduler knobs, etc.) pass an `overrides` dict
        (or a ScweetConfig) with nested fields, for example:

            cfg = ScweetConfig.from_sources(
                db_path="state.db",
                cookies_file="cookies.json",
                api_http_impersonate="chrome124",
                overrides={"operations": {"account_lease_ttl_s": 600}},
            )
        """

        def _deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
            out = dict(base or {})
            for key, value in (patch or {}).items():
                if isinstance(value, dict) and isinstance(out.get(key), dict):
                    out[key] = _deep_merge(out[key], value)
                else:
                    out[key] = value
            return out

        def _enum_value(value: Any) -> Any:
            return getattr(value, "value", value)

        base = cls().model_dump()

        patch: dict[str, Any] = {
            # Tweet search scraping is API-only; keep config reflective of runtime behavior.
            "engine": {
                "kind": EngineKind.API,
                "api_http_mode": _enum_value(api_http_mode),
            },
            "storage": {"db_path": db_path},
            "accounts": {
                "provision_on_init": bool(provision_on_init),
                "bootstrap_strategy": _enum_value(bootstrap_strategy),
            },
            "runtime": {"strict": bool(strict)},
            "resume": {"mode": _enum_value(resume_mode)},
        }

        if accounts_file is not None:
            patch["accounts"]["accounts_file"] = accounts_file
        if cookies_file is not None:
            patch["accounts"]["cookies_file"] = cookies_file
        if env_path is not None:
            patch["accounts"]["env_path"] = env_path
        if cookies is not None:
            patch["accounts"]["cookies"] = cookies
        if manifest_url is not None:
            patch["manifest"] = {"manifest_url": manifest_url}
        if update_manifest:
            patch["manifest"] = dict(patch.get("manifest") or {})
            patch["manifest"]["update_on_init"] = True
        if output_format is not None and str(output_format).strip():
            patch["output"] = dict(patch.get("output") or {})
            patch["output"]["format"] = str(output_format).strip().lower()
        if proxy is not None:
            patch["runtime"]["proxy"] = proxy
        if user_agent is not None and str(user_agent).strip():
            patch["runtime"]["user_agent"] = str(user_agent).strip()
        if api_user_agent is not None and str(api_user_agent).strip():
            patch["runtime"]["api_user_agent"] = str(api_user_agent).strip()
        if n_splits is not None:
            patch["pool"] = dict(patch.get("pool") or {})
            patch["pool"]["n_splits"] = n_splits
        if concurrency is not None:
            patch["pool"] = dict(patch.get("pool") or {})
            patch["pool"]["concurrency"] = concurrency
        if api_http_impersonate is not None and str(api_http_impersonate).strip():
            patch["engine"]["api_http_impersonate"] = str(api_http_impersonate).strip()

        merged = _deep_merge(base, patch)

        if overrides is not None:
            if isinstance(overrides, cls):
                overrides_data = overrides.model_dump()
            elif isinstance(overrides, dict):
                overrides_data = dict(overrides)
            else:
                raise TypeError("overrides must be a dict, ScweetConfig, or None")
            merged = _deep_merge(merged, overrides_data)

        return cls.model_validate(merged)


def _parse_config_input(config_input: Any) -> ScweetConfig:
    if config_input is None:
        return ScweetConfig()
    if isinstance(config_input, ScweetConfig):
        return config_input.model_copy(deep=True)
    if isinstance(config_input, dict):
        return ScweetConfig.model_validate(config_input)
    raise TypeError("config must be ScweetConfig, dict, or None")


def _engine_kind_from_legacy_mode(mode_value: Any) -> EngineKind:
    if mode_value is None:
        return EngineKind.BROWSER
    mode_str = str(mode_value).strip().lower()
    if mode_str == "api":
        return EngineKind.API
    if mode_str == "browser":
        return EngineKind.BROWSER
    return EngineKind.AUTO


def _with_warning_if_needed(warnings_out: list[str], condition: bool, message: str) -> None:
    if condition:
        warnings_out.append(message)


def build_config_from_legacy_init_kwargs(**kwargs) -> tuple[ScweetConfig, list[str]]:
    """Build a deterministic v4 config from legacy/new constructor kwargs."""

    warnings_out: list[str] = []
    config = _parse_config_input(kwargs.get("config"))

    legacy_mode = kwargs.get("mode")
    legacy_env_path = kwargs.get("env_path")
    legacy_n_splits = kwargs.get("n_splits")
    legacy_concurrency = kwargs.get("concurrency")

    _with_warning_if_needed(
        warnings_out,
        legacy_mode is not None and str(legacy_mode).strip().upper() != "BROWSER",
        "`mode` is deprecated in v4.x, planned removal in v5.0. Use `engine` instead.",
    )
    _with_warning_if_needed(
        warnings_out,
        legacy_n_splits is not None and legacy_n_splits != 5,
        "`n_splits` is deprecated in v4.x, planned removal in v5.0. Use `config.pool.n_splits` instead.",
    )
    _with_warning_if_needed(
        warnings_out,
        legacy_concurrency is not None and legacy_concurrency != 5,
        "`concurrency` is deprecated in v4.x, planned removal in v5.0. Use `config.pool.concurrency` instead.",
    )

    engine_data = config.engine.model_dump()
    engine_kind = config.engine.kind
    engine_http_mode = config.engine.api_http_mode
    if legacy_mode is not None:
        engine_kind = _engine_kind_from_legacy_mode(legacy_mode)
    if kwargs.get("engine") is not None:
        engine_kind = EngineKind(str(kwargs["engine"]).lower())
    if kwargs.get("api_http_mode") is not None:
        engine_http_mode = ApiHttpMode(str(kwargs["api_http_mode"]).lower())

    engine_data["kind"] = engine_kind
    engine_data["api_http_mode"] = engine_http_mode
    if kwargs.get("api_http_impersonate") is not None:
        engine_data["api_http_impersonate"] = kwargs["api_http_impersonate"]
    engine = EngineConfig.model_validate(engine_data)

    storage_data = config.storage.model_dump()
    if kwargs.get("db_path") is not None:
        storage_data["db_path"] = kwargs["db_path"]
    storage = StorageConfig.model_validate(storage_data)

    accounts_data = config.accounts.model_dump()
    if kwargs.get("accounts_file") is not None:
        accounts_data["accounts_file"] = kwargs["accounts_file"]
    if kwargs.get("cookies_file") is not None:
        accounts_data["cookies_file"] = kwargs["cookies_file"]
    if kwargs.get("cookies_path") is not None:
        accounts_data["cookies_path"] = kwargs["cookies_path"]
    if kwargs.get("env_path") is not None:
        accounts_data["env_path"] = kwargs["env_path"]
    if kwargs.get("cookies") is not None:
        accounts_data["cookies"] = kwargs["cookies"]
    accounts = AccountsConfig.model_validate(accounts_data)

    pool_data = config.pool.model_dump()
    if kwargs.get("n_splits") is not None:
        pool_data["n_splits"] = kwargs["n_splits"]
    if kwargs.get("concurrency") is not None:
        pool_data["concurrency"] = kwargs["concurrency"]
    pool = PoolConfig.model_validate(pool_data)

    runtime_data = config.runtime.model_dump()
    if kwargs.get("proxy") is not None:
        runtime_data["proxy"] = kwargs["proxy"]
    if kwargs.get("user_agent") is not None:
        runtime_data["user_agent"] = kwargs["user_agent"]
    if kwargs.get("disable_images") is not None:
        runtime_data["disable_images"] = kwargs["disable_images"]
    if kwargs.get("headless") is not None:
        runtime_data["headless"] = kwargs["headless"]
    if kwargs.get("scroll_ratio") is not None:
        runtime_data["scroll_ratio"] = kwargs["scroll_ratio"]
    if kwargs.get("code_callback") is not None:
        runtime_data["code_callback"] = kwargs["code_callback"]
    runtime = RuntimeConfig.model_validate(runtime_data)

    operations_data = config.operations.model_dump()
    for key in (
        "account_lease_ttl_s",
        "account_lease_heartbeat_s",
        "cooldown_default_s",
        "transient_cooldown_s",
        "auth_cooldown_s",
        "cooldown_jitter_s",
        "account_requests_per_min",
        "account_min_delay_s",
        "api_page_size",
        "max_empty_pages",
        "task_retry_base_s",
        "task_retry_max_s",
        "max_task_attempts",
        "max_fallback_attempts",
        "max_account_switches",
        "scheduler_min_interval_s",
        "priority",
    ):
        if kwargs.get(key) is not None:
            operations_data[key] = kwargs[key]
    operations = OperationalConfig.model_validate(operations_data)

    resume_data = config.resume.model_dump()
    if kwargs.get("resume_mode") is not None:
        resume_data["mode"] = kwargs["resume_mode"]
    resume = ResumeConfig.model_validate(resume_data)

    output_data = config.output.model_dump()
    output = OutputConfig.model_validate(output_data)

    manifest_data = config.manifest.model_dump()
    if kwargs.get("manifest_url") is not None:
        manifest_data["manifest_url"] = kwargs["manifest_url"]
    if kwargs.get("update_manifest") is not None:
        manifest_data["update_on_init"] = bool(kwargs["update_manifest"])
    manifest = ManifestConfig.model_validate(manifest_data)

    try:
        built = ScweetConfig(
            engine=engine,
            storage=storage,
            accounts=accounts,
            pool=pool,
            runtime=runtime,
            operations=operations,
            resume=resume,
            output=output,
            manifest=manifest,
        )
    except ValidationError:
        raise

    return built, warnings_out
