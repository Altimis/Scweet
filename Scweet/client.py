from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional, Union

from .scweet import Scweet as LegacyScweet
from .v4.config import ScweetConfig, build_config_from_legacy_init_kwargs
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
        engine=None,
        db_path=None,
        accounts_file=None,
        cookies_file=None,
        manifest_url=None,
        config: Optional[Union[ScweetConfig, dict[str, Any]]] = None,
    ):
        self._v4_config, self._v4_init_warnings = build_config_from_legacy_init_kwargs(
            proxy=proxy,
            cookies=cookies,
            cookies_path=cookies_path,
            user_agent=user_agent,
            disable_images=disable_images,
            env_path=env_path,
            n_splits=n_splits,
            concurrency=concurrency,
            headless=headless,
            scroll_ratio=scroll_ratio,
            mode=mode,
            code_callback=code_callback,
            engine=engine,
            db_path=db_path,
            accounts_file=accounts_file,
            cookies_file=cookies_file,
            manifest_url=manifest_url,
            config=config,
        )

        # Let the legacy facade constructor initialize v4 core using this already-mapped config.
        self._v4_prebuilt_config = self._v4_config
        self._v4_prebuilt_warnings = list(self._v4_init_warnings)
        self._v4_emit_legacy_import_warning = False
        self._v4_emit_init_warnings = False

        super().__init__(
            proxy=proxy,
            cookies=cookies,
            cookies_path=cookies_path,
            user_agent=user_agent,
            disable_images=disable_images,
            env_path=env_path,
            n_splits=n_splits,
            concurrency=concurrency,
            headless=headless,
            scroll_ratio=scroll_ratio,
            mode=mode,
            code_callback=code_callback,
        )

        for message in self._v4_init_warnings:
            warn_deprecated(message)

    @property
    def config(self) -> ScweetConfig:
        return self._v4_config

    @property
    def init_warnings(self) -> list[str]:
        return list(self._v4_init_warnings)
