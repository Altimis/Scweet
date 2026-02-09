from __future__ import annotations

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
    store_credentials: bool = False

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
    proxy: Optional[dict[str, Any]] = None
    user_agent: Optional[str] = None
    disable_images: bool = False
    headless: bool = True
    scroll_ratio: int = Field(default=30, ge=1)
    code_callback: Optional[Any] = None
    strict: bool = False


class OperationalConfig(BaseModel):
    account_lease_ttl_s: int = Field(default=120, ge=1)
    account_lease_heartbeat_s: float = Field(default=30.0, ge=0.0)
    cooldown_default_s: float = Field(default=120.0, ge=0.0)
    transient_cooldown_s: float = Field(default=120.0, ge=0.0)
    auth_cooldown_s: float = Field(default=30 * 24 * 60 * 60, ge=0.0)
    cooldown_jitter_s: float = Field(default=10.0, ge=0.0)
    account_requests_per_min: int = Field(default=60, ge=1)
    account_min_delay_s: float = Field(default=0.0, ge=0.0)
    api_page_size: int = Field(default=20, ge=1, le=100)
    task_retry_base_s: int = Field(default=1, ge=0)
    task_retry_max_s: int = Field(default=30, ge=0)
    max_task_attempts: int = Field(default=3, ge=1)
    max_fallback_attempts: int = Field(default=3, ge=1)
    max_account_switches: int = Field(default=2, ge=0)
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


class ManifestConfig(BaseModel):
    manifest_url: Optional[str] = None
    ttl_s: int = Field(default=3600, ge=1)


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
        bool(legacy_env_path),
        "`env_path` is deprecated in v4.x, planned removal in v5.0. Use `accounts_file`/`cookies_file` instead.",
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

    engine_kind = config.engine.kind
    engine_http_mode = config.engine.api_http_mode
    if legacy_mode is not None:
        engine_kind = _engine_kind_from_legacy_mode(legacy_mode)
    if kwargs.get("engine") is not None:
        engine_kind = EngineKind(str(kwargs["engine"]).lower())
    if kwargs.get("api_http_mode") is not None:
        engine_http_mode = ApiHttpMode(str(kwargs["api_http_mode"]).lower())

    engine = EngineConfig(kind=engine_kind, api_http_mode=engine_http_mode)

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
