from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Union

from .scweet import Scweet as LegacyScweet
from .v4.config import ApiHttpMode, BootstrapStrategy, ResumeMode, ScweetConfig, build_config_from_legacy_init_kwargs
from .v4.warnings import warn_deprecated


class Scweet(LegacyScweet):
    """Preferred v4 client with compatibility signatures and v4-core routing."""

    def __init__(
        self,
        proxy=None,
        cookies=None,
        cookies_path=None,
        user_agent=None,
        disable_images=False,
        env_path=None,
        n_splits=5,
        concurrency=5,
        headless=True,
        scroll_ratio=30,
        mode="BROWSER",
        code_callback: Optional[Callable[[str, str], Awaitable[str]]] = None,
        *,
        config: Optional[Union[ScweetConfig, dict[str, Any]]] = None,
        **kwargs,
    ):
        allowed_extras = {"engine", "db_path", "accounts_file", "cookies_file", "manifest_url", "update_manifest"}
        unknown = set(kwargs.keys()) - allowed_extras
        if unknown:
            unknown_str = ", ".join(sorted(unknown))
            raise TypeError(f"Unexpected keyword argument(s): {unknown_str}")

        config_provided = config is not None
        build_kwargs: dict[str, Any] = dict(kwargs)
        build_kwargs["config"] = config

        # Config should win over legacy defaults. Only apply legacy args when:
        # - no config was provided, or
        # - the caller passed a non-default value.
        if (not config_provided) or proxy is not None:
            build_kwargs["proxy"] = proxy
        if (not config_provided) or cookies is not None:
            build_kwargs["cookies"] = cookies
        if (not config_provided) or cookies_path is not None:
            build_kwargs["cookies_path"] = cookies_path
        if (not config_provided) or user_agent is not None:
            build_kwargs["user_agent"] = user_agent
        if (not config_provided) or disable_images is not False:
            build_kwargs["disable_images"] = disable_images
        if (not config_provided) or env_path is not None:
            build_kwargs["env_path"] = env_path
        if (not config_provided) or n_splits != 5:
            build_kwargs["n_splits"] = n_splits
        if (not config_provided) or concurrency != 5:
            build_kwargs["concurrency"] = concurrency
        if (not config_provided) or headless is not True:
            build_kwargs["headless"] = headless
        if (not config_provided) or scroll_ratio != 30:
            build_kwargs["scroll_ratio"] = scroll_ratio
        if (not config_provided) or mode != "BROWSER":
            build_kwargs["mode"] = mode
        if (not config_provided) or code_callback is not None:
            build_kwargs["code_callback"] = code_callback

        self._v4_config, self._v4_init_warnings = build_config_from_legacy_init_kwargs(**build_kwargs)

        effective_proxy = self._v4_config.runtime.proxy
        effective_cookies = getattr(self._v4_config.accounts, "cookies", None)
        effective_cookies_path = getattr(self._v4_config.accounts, "cookies_path", None)
        effective_user_agent = self._v4_config.runtime.user_agent
        effective_disable_images = self._v4_config.runtime.disable_images
        effective_env_path = self._v4_config.accounts.env_path
        effective_n_splits = self._v4_config.pool.n_splits
        effective_concurrency = self._v4_config.pool.concurrency
        effective_headless = self._v4_config.runtime.headless
        effective_scroll_ratio = self._v4_config.runtime.scroll_ratio
        effective_mode = mode
        effective_code_callback = self._v4_config.runtime.code_callback

        # Let the legacy facade constructor initialize v4 core using this already-mapped config.
        self._v4_prebuilt_config = self._v4_config
        self._v4_prebuilt_warnings = list(self._v4_init_warnings)
        self._v4_emit_legacy_import_warning = False
        self._v4_emit_init_warnings = False

        super().__init__(
            proxy=effective_proxy,
            cookies=effective_cookies,
            cookies_path=effective_cookies_path,
            user_agent=effective_user_agent,
            disable_images=effective_disable_images,
            env_path=effective_env_path,
            n_splits=effective_n_splits,
            concurrency=effective_concurrency,
            headless=effective_headless,
            scroll_ratio=effective_scroll_ratio,
            mode=effective_mode,
            code_callback=effective_code_callback,
        )

        for message in self._v4_init_warnings:
            warn_deprecated(message)

    @property
    def config(self) -> ScweetConfig:
        return self._v4_config

    @property
    def init_warnings(self) -> list[str]:
        return list(self._v4_init_warnings)

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
    ) -> "Scweet":
        cfg = ScweetConfig.from_sources(
            db_path=db_path,
            accounts_file=accounts_file,
            cookies_file=cookies_file,
            env_path=env_path,
            cookies=cookies,
            manifest_url=manifest_url,
            update_manifest=bool(update_manifest),
            bootstrap_strategy=bootstrap_strategy,
            provision_on_init=provision_on_init,
            strict=strict,
            proxy=proxy,
            user_agent=user_agent,
            api_user_agent=api_user_agent,
            resume_mode=resume_mode,
            output_format=output_format,
            api_http_mode=api_http_mode,
            api_http_impersonate=api_http_impersonate,
            n_splits=n_splits,
            concurrency=concurrency,
            overrides=overrides,
        )
        return cls(config=cfg)
