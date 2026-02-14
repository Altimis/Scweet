from __future__ import annotations

import asyncio
import csv
import inspect
import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union, List

from .v4.api_engine import ApiEngine
from .v4.account_session import AccountSessionBuilder
from .v4.auth import import_accounts_to_db
from .v4.config import ScweetConfig, build_config_from_legacy_init_kwargs
from .v4.exceptions import AccountPoolExhausted
from .v4.manifest import ManifestProvider
from .v4.mappers import build_legacy_csv_filename
from .v4.models import FollowsRequest, ProfileRequest, ProfileTimelineRequest, SearchRequest
from .v4.outputs import write_csv, write_json_auto_append
from .v4.query import normalize_search_input
from .v4.resume import compute_query_hash, resolve_resume_start
from .v4.repos import AccountsRepo, ResumeRepo, RunsRepo
from .v4.runner import Runner
from .v4.user_identity import normalize_profile_targets_explicit, normalize_user_targets
from .v4.tweet_csv import SUMMARY_CSV_HEADER, tweet_to_csv_rows
from .v4.transaction import TransactionIdProvider
from .v4.warnings import warn_deprecated, warn_legacy_import_path

logger = logging.getLogger(__name__)


def _tweet_rest_id_from_raw(raw: Any) -> Optional[str]:
    if not isinstance(raw, dict):
        return None
    value: Any = raw
    if isinstance(raw.get("tweet"), dict):
        value = raw["tweet"]
    if not isinstance(value, dict):
        return None

    rest_id = value.get("rest_id") or value.get("tweet_id") or value.get("tweetId") or value.get("id")
    if rest_id:
        tid = str(rest_id).strip()
        return tid or None

    legacy = value.get("legacy")
    if isinstance(legacy, dict) and legacy.get("id_str"):
        tid = str(legacy["id_str"]).strip()
        return tid or None
    return None


def _read_existing_tweet_ids_from_csv(path: str) -> set[str]:
    candidates = ("tweet_id", "rest_id", "tweetId", "tweet_id_str", "id", "id_str", "Tweet ID", "TweetId")
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            return set()
    except Exception:
        return set()

    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None) or []
            header = [str(col).lstrip("\ufeff") for col in header]
            id_idx: Optional[int] = None
            for candidate in candidates:
                if candidate in header:
                    id_idx = header.index(candidate)
                    break
            if id_idx is None:
                return set()

            out: set[str] = set()
            for row in reader:
                if not row or id_idx >= len(row):
                    continue
                value = str(row[id_idx]).strip()
                if value:
                    out.add(value)
            return out
    except Exception:
        return set()


def _read_existing_tweet_ids_from_json(path: str) -> set[str]:
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            return set()
    except Exception:
        return set()

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return set()

    if not isinstance(payload, list):
        return set()

    out: set[str] = set()
    for item in payload:
        tid = _tweet_rest_id_from_raw(item)
        if tid:
            out.add(tid)
    return out


FOLLOWS_CSV_HEADER = [
    "follow_key",
    "type",
    "target_username",
    "target_profile_url",
    "target_source",
    "target_raw",
    "user_id",
    "username",
    "name",
    "description",
    "location",
    "created_at",
    "followers_count",
    "following_count",
    "statuses_count",
    "favourites_count",
    "media_count",
    "listed_count",
    "verified",
    "blue_verified",
    "protected",
    "profile_image_url",
    "profile_banner_url",
    "url",
]


PROFILES_CSV_HEADER = [
    "profile_key",
    "input_raw",
    "input_source",
    "user_id",
    "username",
    "name",
    "description",
    "location",
    "created_at",
    "followers_count",
    "following_count",
    "statuses_count",
    "favourites_count",
    "media_count",
    "listed_count",
    "verified",
    "blue_verified",
    "protected",
    "profile_image_url",
    "profile_banner_url",
    "url",
]


def _follow_record_key(value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    explicit = str(value.get("follow_key") or "").strip()
    if explicit:
        return explicit
    follow_type = str(value.get("type") or "").strip().lower()
    target = value.get("target") if isinstance(value.get("target"), dict) else {}
    target_username = str(target.get("username") or "").strip().lstrip("@").lower()
    target_profile_url = str(target.get("profile_url") or "").strip().lower()
    target_raw = str(target.get("raw") or "").strip().lower()
    identity = str(value.get("user_id") or "").strip()
    if not identity:
        identity = str(value.get("username") or "").strip().lower()
    if not identity:
        raw_user = value.get("raw") if isinstance(value.get("raw"), dict) else {}
        legacy = raw_user.get("legacy") if isinstance(raw_user.get("legacy"), dict) else {}
        identity = str(
            raw_user.get("rest_id")
            or raw_user.get("id")
            or legacy.get("id_str")
            or legacy.get("screen_name")
            or ""
        ).strip()
        if identity and str(legacy.get("screen_name") or "").strip().lower() == identity.lower():
            identity = identity.lower()
    if not identity:
        return None
    target_ref = target_username or target_profile_url or target_raw or "-"
    follow_ref = follow_type or "following"
    return f"{follow_ref}|{target_ref}|{identity}"


def _read_existing_follow_keys_from_csv(path: str) -> set[str]:
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            return set()
    except Exception:
        return set()

    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None) or []
            header = [str(col).lstrip("\ufeff") for col in header]
            if "follow_key" not in header:
                return set()
            idx = header.index("follow_key")
            out: set[str] = set()
            for row in reader:
                if not row or idx >= len(row):
                    continue
                value = str(row[idx]).strip()
                if value:
                    out.add(value)
            return out
    except Exception:
        return set()


def _read_existing_follow_keys_from_json(path: str) -> set[str]:
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            return set()
    except Exception:
        return set()

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return set()
    if not isinstance(payload, list):
        return set()

    out: set[str] = set()
    for row in payload:
        key = _follow_record_key(row)
        if key:
            out.add(key)
    return out


def _profile_record_key(value: Any) -> Optional[str]:
    if not isinstance(value, dict):
        return None
    input_node = value.get("input") if isinstance(value.get("input"), dict) else {}
    target_ref = (
        str(input_node.get("raw") or "").strip()
        or str(input_node.get("source") or "").strip()
        or "-"
    ).lower()

    identity = str(value.get("user_id") or "").strip()
    if not identity:
        identity = str(value.get("username") or "").strip().lower()
    if not identity:
        return None
    return f"{target_ref}|{identity}"


def _read_existing_profile_keys_from_csv(path: str) -> set[str]:
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            return set()
    except Exception:
        return set()

    try:
        with open(path, "r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None) or []
            header = [str(col).lstrip("\ufeff") for col in header]
            if "profile_key" not in header:
                return set()
            idx = header.index("profile_key")
            out: set[str] = set()
            for row in reader:
                if not row or idx >= len(row):
                    continue
                value = str(row[idx]).strip()
                if value:
                    out.add(value)
            return out
    except Exception:
        return set()


def _read_existing_profile_keys_from_json(path: str) -> set[str]:
    try:
        if not os.path.exists(path) or os.path.getsize(path) <= 0:
            return set()
    except Exception:
        return set()

    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception:
        return set()
    if not isinstance(payload, list):
        return set()

    out: set[str] = set()
    for row in payload:
        key = _profile_record_key(row)
        if key:
            out.add(key)
    return out


class Scweet:
    """Compatibility facade with legacy signatures routed to v4 core."""

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
    ):
        # Keep legacy instance attributes available for compatibility.
        self.driver = None
        self.main_tab = None
        self.logged_in = False
        self.suspended = False
        self.display = None

        self.proxy = proxy
        self.cookies = cookies
        self.cookies_path = cookies_path
        self.user_agent = user_agent
        self.disable_images = disable_images
        self.env_path = env_path
        self.n_splits = n_splits
        self.concurrency = concurrency
        self.headless = headless
        self.scroll_ratio = scroll_ratio
        self.mode = mode
        self.code_callback = code_callback

        prebuilt_config = getattr(self, "_v4_prebuilt_config", None)
        prebuilt_warnings = getattr(self, "_v4_prebuilt_warnings", None)
        if prebuilt_config is None:
            config, init_warnings = build_config_from_legacy_init_kwargs(
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
        else:
            config = prebuilt_config
            init_warnings = list(prebuilt_warnings or [])

        self._v4_config = config
        self._v4_init_warnings = list(init_warnings)

        emit_init_warnings = bool(getattr(self, "_v4_emit_init_warnings", True))
        if emit_init_warnings:
            for message in self._v4_init_warnings:
                warn_deprecated(message)

        emit_legacy_import_warning = bool(getattr(self, "_v4_emit_legacy_import_warning", True))
        if emit_legacy_import_warning and self.__class__.__module__ == __name__:
            warn_legacy_import_path()

        self._init_v4_core()

    @property
    def config(self) -> ScweetConfig:
        return self._v4_config

    @property
    def init_warnings(self) -> list[str]:
        return list(self._v4_init_warnings)

    @property
    def db(self):
        """Convenience accessor for DB maintenance APIs (ScweetDB)."""
        from .v4.db import ScweetDB

        ops = getattr(self._v4_config, "operations", None)
        return ScweetDB(
            self._v4_config.storage.db_path,
            account_daily_requests_limit=int(getattr(ops, "account_daily_requests_limit", 30) or 30),
            account_daily_tweets_limit=int(getattr(ops, "account_daily_tweets_limit", 600) or 600),
        )

    def _init_v4_core(self) -> None:
        db_path = self._v4_config.storage.db_path
        lease_ttl_s = max(1, int(getattr(self._v4_config.operations, "account_lease_ttl_s", 120)))
        daily_requests_limit = max(1, int(getattr(self._v4_config.operations, "account_daily_requests_limit", 30)))
        daily_tweets_limit = max(1, int(getattr(self._v4_config.operations, "account_daily_tweets_limit", 600)))
        self._accounts_repo = AccountsRepo(
            db_path,
            lease_ttl_s=lease_ttl_s,
            daily_pages_limit=daily_requests_limit,
            daily_tweets_limit=daily_tweets_limit,
            require_auth_material=True,
        )
        self._runs_repo = RunsRepo(db_path)
        self._resume_repo = ResumeRepo(db_path)

        provision_on_init = bool(getattr(self._v4_config.accounts, "provision_on_init", True))
        if provision_on_init:
            accounts_file = self._v4_config.accounts.accounts_file
            cookies_file = self._v4_config.accounts.cookies_file
            env_path = self._v4_config.accounts.env_path
            cookies_payload = self.cookies
            if cookies_payload is None:
                cookies_payload = getattr(self._v4_config.accounts, "cookies", None)

            has_sources = bool(accounts_file or cookies_file or env_path or cookies_payload is not None)
            if has_sources:
                runtime_options = {
                    "proxy": getattr(self._v4_config.runtime, "proxy", None),
                    "user_agent": getattr(self._v4_config.runtime, "user_agent", None),
                    "headless": bool(getattr(self._v4_config.runtime, "headless", True)),
                    "disable_images": bool(getattr(self._v4_config.runtime, "disable_images", False)),
                    "code_callback": getattr(self._v4_config.runtime, "code_callback", None),
                }
                try:
                    import_accounts_to_db(
                        db_path,
                        accounts_file=accounts_file,
                        cookies_file=cookies_file,
                        env_path=env_path,
                        cookies_payload=cookies_payload,
                        bootstrap_strategy=getattr(self._v4_config.accounts, "bootstrap_strategy", "auto"),
                        runtime=runtime_options,
                    )
                except Exception:
                    # Provisioning is best-effort by default; scraping will surface "no usable accounts"
                    # unless strict mode is enabled.
                    logger.exception("Account provisioning failed (best-effort); continuing")

        self._manifest_provider = ManifestProvider(
            db_path=db_path,
            manifest_url=self._v4_config.manifest.manifest_url,
            ttl_s=self._v4_config.manifest.ttl_s,
        )
        if bool(getattr(self._v4_config.manifest, "update_on_init", False)):
            strict = bool(getattr(self._v4_config.runtime, "strict", False))
            try:
                self._manifest_provider.refresh_sync(strict=strict)
            except Exception:
                if strict:
                    raise
                logger.exception("Manifest refresh failed (best-effort); continuing")
        tx_provider_kwargs: dict[str, Any] = {
            "proxy": getattr(self._v4_config.runtime, "proxy", None),
            "user_agent": getattr(self._v4_config.runtime, "api_user_agent", None),
        }
        configured_impersonate = getattr(getattr(self._v4_config, "engine", None), "api_http_impersonate", None)
        if isinstance(configured_impersonate, str) and configured_impersonate.strip():
            tx_provider_kwargs["impersonate"] = configured_impersonate.strip()
        self._transaction_id_provider = TransactionIdProvider(**tx_provider_kwargs)
        self._api_engine = ApiEngine(
            config=self._v4_config,
            accounts_repo=self._accounts_repo,
            manifest_provider=self._manifest_provider,
            transaction_id_provider=self._transaction_id_provider,
        )
        configured_http_mode = getattr(self._v4_config.engine.api_http_mode, "value", self._v4_config.engine.api_http_mode)
        session_builder_kwargs: dict[str, Any] = {
            "api_http_mode": str(configured_http_mode or "auto"),
            "proxy": getattr(self._v4_config.runtime, "proxy", None),
        }
        if isinstance(configured_impersonate, str) and configured_impersonate.strip():
            session_builder_kwargs["impersonate"] = configured_impersonate.strip()
        configured_api_user_agent = getattr(self._v4_config.runtime, "api_user_agent", None)
        if isinstance(configured_api_user_agent, str) and configured_api_user_agent.strip():
            session_builder_kwargs["user_agent"] = configured_api_user_agent.strip()
        self._account_session_builder = AccountSessionBuilder(**session_builder_kwargs)

        # Tweet search scraping is API-only regardless of legacy mode/engine selection.
        self._browser_engine = None
        self._selected_engine = self._api_engine

        self._runner = Runner(
            config=self._v4_config,
            repos={
                "accounts_repo": self._accounts_repo,
                "runs_repo": self._runs_repo,
                "resume_repo": self._resume_repo,
            },
            engines={
                "api_engine": self._api_engine,
                "browser_engine": self._browser_engine,
                "engine": self._api_engine,
                "account_session_builder": self._account_session_builder,
            },
            outputs={
                "write_csv": write_csv,
            },
        )

    def provision_accounts(
        self,
        *,
        accounts_file: Optional[str] = None,
        cookies_file: Optional[str] = None,
        env_path: Optional[str] = None,
        cookies: Any = None,
        db_path: Optional[str] = None,
        bootstrap_timeout_s: int = 30,
        creds_bootstrap_timeout_s: int = 180,
    ) -> dict[str, int]:
        """Import accounts into SQLite from the provided sources (optionally bootstrapping).

        This is a manual provisioning API; it does not require scraping.
        """

        effective_db_path = db_path or self._v4_config.storage.db_path
        effective_accounts_file = accounts_file if accounts_file is not None else self._v4_config.accounts.accounts_file
        effective_cookies_file = cookies_file if cookies_file is not None else self._v4_config.accounts.cookies_file
        effective_env_path = env_path if env_path is not None else self._v4_config.accounts.env_path

        if cookies is not None:
            cookies_payload = cookies
        else:
            cookies_payload = self.cookies
            if cookies_payload is None:
                cookies_payload = getattr(self._v4_config.accounts, "cookies", None)

        runtime_options = {
            "proxy": getattr(self._v4_config.runtime, "proxy", None),
            "user_agent": getattr(self._v4_config.runtime, "user_agent", None),
            "headless": bool(getattr(self._v4_config.runtime, "headless", True)),
            "disable_images": bool(getattr(self._v4_config.runtime, "disable_images", False)),
            "code_callback": getattr(self._v4_config.runtime, "code_callback", None),
        }

        processed = import_accounts_to_db(
            effective_db_path,
            accounts_file=effective_accounts_file,
            cookies_file=effective_cookies_file,
            env_path=effective_env_path,
            cookies_payload=cookies_payload,
            bootstrap_strategy=getattr(self._v4_config.accounts, "bootstrap_strategy", "auto"),
            bootstrap_timeout_s=int(bootstrap_timeout_s),
            creds_bootstrap_timeout_s=int(creds_bootstrap_timeout_s),
            runtime=runtime_options,
        )

        if getattr(self._accounts_repo, "db_path", None) == effective_db_path:
            repo = self._accounts_repo
        else:
            ops = getattr(self._v4_config, "operations", None)
            repo = AccountsRepo(
                effective_db_path,
                require_auth_material=True,
                lease_ttl_s=max(1, int(getattr(ops, "account_lease_ttl_s", 120) or 120)),
                daily_pages_limit=max(1, int(getattr(ops, "account_daily_requests_limit", 30) or 30)),
                daily_tweets_limit=max(1, int(getattr(ops, "account_daily_tweets_limit", 600) or 600)),
            )
        eligible = int(repo.count_eligible())

        if bool(getattr(self._v4_config.runtime, "strict", False)) and eligible <= 0:
            raise AccountPoolExhausted(
                "No usable accounts available after provisioning. "
                "Provide accounts via `accounts_file` (accounts.txt), `cookies_file` (cookies.json), "
                "`env_path` (.env), or `cookies=` (cookie dict/list/header/token)."
            )

        return {"processed": int(processed), "eligible": eligible}

    def import_accounts(self, **kwargs) -> dict[str, int]:
        """Alias for provision_accounts for readability."""

        return self.provision_accounts(**kwargs)

    def maintenance_collapse_duplicates(
        self,
        *,
        dry_run: bool = True,
        db_path: Optional[str] = None,
    ) -> dict[str, Any]:
        """Opt-in DB maintenance: collapse duplicate rows sharing the same auth_token."""

        effective_db_path = db_path or self._v4_config.storage.db_path
        repo = AccountsRepo(effective_db_path)
        return repo.collapse_duplicates_by_auth_token(dry_run=bool(dry_run))

    def add_account(self, account: Optional[dict[str, Any]] = None, *, db_path: Optional[str] = None, **kwargs) -> dict[str, Any]:
        """Upsert a single account record into SQLite (no scraping required)."""

        from .v4.auth import normalize_account_record

        payload: dict[str, Any] = {}
        if account:
            payload.update(dict(account))
        payload.update(kwargs)
        normalized = normalize_account_record(payload)
        if not normalized.get("username"):
            raise ValueError("Account record must include username/email/auth_token/cookies to derive a stable username")

        effective_db_path = db_path or self._v4_config.storage.db_path
        if getattr(self._accounts_repo, "db_path", None) == effective_db_path:
            repo = self._accounts_repo
        else:
            repo = AccountsRepo(effective_db_path, require_auth_material=True)
        repo.upsert_account(normalized)
        return normalized

    def repair_account(
        self,
        username: str,
        *,
        refresh_from_auth_token: bool = True,
        force_refresh: bool = False,
        bootstrap_timeout_s: int = 30,
        clear_leases: bool = True,
        include_unusable: bool = True,
        reset_daily: bool = True,
        mark_unusable_if_still_invalid: bool = False,
    ) -> dict[str, Any]:
        """Repair a specific account username (state reset + optional token refresh)."""

        return self.db.repair_account(
            username,
            refresh_from_auth_token=bool(refresh_from_auth_token),
            force_refresh=bool(force_refresh),
            bootstrap_timeout_s=int(bootstrap_timeout_s),
            clear_leases=bool(clear_leases),
            include_unusable=bool(include_unusable),
            reset_daily=bool(reset_daily),
            mark_unusable_if_still_invalid=bool(mark_unusable_if_still_invalid),
        )

    async def init_nodriver(self):
        """Legacy no-op hook retained for compatibility."""
        self.driver = self.driver or object()
        return self.driver

    async def login(self):
        """Legacy-compatible login hook used by old facade flow."""
        return self.main_tab, True, "", None

    async def aclose(self):
        try:
            if self._selected_engine is not None and hasattr(self._selected_engine, "close"):
                await self._selected_engine.close()
        except Exception:
            pass

    def close(self):
        """Synchronous close entrypoint for standard script usage."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.aclose())
        raise RuntimeError("close() cannot be called from an active event loop; use `await aclose()` instead.")

    async def __aenter__(self):
        await self.init_nodriver()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.aclose()

    def _effective_resume_mode(self) -> str:
        # `Scweet.scweet.Scweet` import path must keep legacy CSV resume semantics.
        if self.__class__.__module__ == __name__:
            return "legacy_csv"
        config_mode = getattr(getattr(self._v4_config, "resume", None), "mode", None)
        mode_value = getattr(config_mode, "value", config_mode)
        if isinstance(mode_value, str) and mode_value.strip():
            return mode_value.strip().lower()
        return "hybrid_safe"

    @staticmethod
    def _coerce_request_limit(limit: Any) -> Optional[int]:
        if limit in (None, float("inf")):
            return None
        try:
            return int(limit)
        except Exception:
            return None

    @staticmethod
    def _coerce_max_empty_pages(value: Any) -> int:
        try:
            parsed = int(value)
        except Exception:
            return 1
        return max(1, parsed)

    def _resolve_max_empty_pages(self, value: Any) -> int:
        if value is not None:
            return self._coerce_max_empty_pages(value)
        operations = getattr(self._v4_config, "operations", None)
        configured = getattr(operations, "max_empty_pages", 1)
        return self._coerce_max_empty_pages(configured)

    @staticmethod
    def _coerce_save_format(value: Any) -> Optional[str]:
        if value is None:
            return None
        fmt = str(value).strip().lower()
        if fmt in {"csv", "json", "both", "none"}:
            return fmt
        return None

    def _resolve_save_format(self, value: Any, *, save: bool = False) -> str:
        if not self._coerce_bool_flag(save, default=False):
            return "none"
        explicit = self._coerce_save_format(value)
        if explicit is not None:
            return explicit
        configured = getattr(getattr(self._v4_config, "output", None), "format", None)
        cfg = self._coerce_save_format(configured)
        if cfg is not None:
            return cfg
        return "none"

    @staticmethod
    def _coerce_bool_flag(value: Any, *, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return bool(value)
        text = str(value).strip().lower()
        if not text:
            return default
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
        return default

    @staticmethod
    def _merge_input_values(*values: Any) -> Optional[list[Any]]:
        out: list[Any] = []
        for value in values:
            if value is None:
                continue
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    if item is None:
                        continue
                    text = str(item).strip()
                    if text:
                        out.append(item)
                continue
            text = str(value).strip()
            if text:
                out.append(value)
        if out:
            return out
        return None

    @staticmethod
    def _supports_kwarg(func: Any, arg_name: str) -> bool:
        try:
            signature = inspect.signature(func)
        except Exception:
            return False
        if arg_name in signature.parameters:
            return True
        for parameter in signature.parameters.values():
            if parameter.kind == inspect.Parameter.VAR_KEYWORD:
                return True
        return False

    def _persist_tweet_outputs(
        self,
        *,
        tweets: list[Any],
        csv_filename: str,
        resume: bool,
        save_format: Optional[str] = None,
        write_state: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        state = write_state if isinstance(write_state, dict) else {}
        raw_tweets: list[dict[str, Any]] = []
        csv_rows_summary: list[dict[str, Any]] = []
        csv_rows_compat: list[dict[str, Any]] = []
        for tweet in tweets:
            raw: Any = None
            if isinstance(tweet, dict):
                raw = tweet
            else:
                raw = getattr(tweet, "raw", None)
                if not isinstance(raw, dict) and hasattr(tweet, "model_dump"):
                    try:
                        raw = tweet.model_dump(mode="json")  # type: ignore[attr-defined]
                    except Exception:
                        raw = None
            if not isinstance(raw, dict):
                raw = {"value": str(tweet)}
            raw_tweets.append(raw)
            mapped = tweet_to_csv_rows(raw)
            csv_rows_summary.append(mapped.summary)
            csv_rows_compat.append(mapped.compat)

        fmt = self._coerce_save_format(save_format) or "none"

        dedupe_on_resume = bool(
            getattr(getattr(self._v4_config, "output", None), "dedupe_on_resume_by_tweet_id", False)
        )
        if resume and dedupe_on_resume and fmt != "none":
            seen_ids = state.get("tweet_dedupe_seen_ids")
            if not isinstance(seen_ids, set):
                existing_ids: set[str] = set()
                if fmt in {"csv", "both"}:
                    existing_ids.update(_read_existing_tweet_ids_from_csv(csv_filename))
                if fmt in {"json", "both"}:
                    json_path_for_dedupe = str(Path(csv_filename).with_suffix(".json"))
                    existing_ids.update(_read_existing_tweet_ids_from_json(json_path_for_dedupe))
                seen_ids = set(existing_ids)
                state["tweet_dedupe_seen_ids"] = seen_ids

            filtered_raw: list[dict[str, Any]] = []
            filtered_summary: list[dict[str, Any]] = []
            filtered_compat: list[dict[str, Any]] = []
            for raw, summary, compat in zip(raw_tweets, csv_rows_summary, csv_rows_compat):
                tid: Optional[str] = None
                try:
                    tid = summary.get("tweet_id")  # type: ignore[assignment]
                except Exception:
                    tid = None
                if tid is not None and not isinstance(tid, str):
                    tid = str(tid)
                if isinstance(tid, str):
                    tid = tid.strip() or None
                if not tid:
                    tid = _tweet_rest_id_from_raw(raw)

                if tid and tid in seen_ids:
                    continue
                if tid:
                    seen_ids.add(tid)

                filtered_raw.append(raw)
                filtered_summary.append(summary)
                filtered_compat.append(compat)

            raw_tweets = filtered_raw
            csv_rows_summary = filtered_summary
            csv_rows_compat = filtered_compat

        if fmt in {"csv", "both"}:
            if state.get("tweet_csv_initialized"):
                write_mode = "a"
            else:
                write_mode = "a" if (resume and os.path.exists(csv_filename)) else "w"
                state["tweet_csv_initialized"] = True
            if write_mode == "a":
                try:
                    if (not os.path.exists(csv_filename)) or os.path.getsize(csv_filename) <= 0:
                        write_mode = "w"
                except Exception:
                    write_mode = "w"

            if not csv_rows_summary:
                if write_mode == "w" and not os.path.exists(csv_filename):
                    Path(csv_filename).parent.mkdir(parents=True, exist_ok=True)
                    Path(csv_filename).touch()
            else:
                existing_header = state.get("tweet_csv_existing_header")
                if (
                    not isinstance(existing_header, list)
                    and write_mode == "a"
                    and os.path.exists(csv_filename)
                    and os.path.getsize(csv_filename) > 0
                ):
                    try:
                        with open(csv_filename, "r", encoding="utf-8", newline="") as handle:
                            reader = csv.reader(handle)
                            existing_header = next(reader, None) or None
                    except Exception:
                        existing_header = None
                    state["tweet_csv_existing_header"] = existing_header

                if existing_header and existing_header != SUMMARY_CSV_HEADER:
                    write_csv(csv_filename, csv_rows_compat, existing_header, mode="a")
                else:
                    write_csv(csv_filename, csv_rows_summary, SUMMARY_CSV_HEADER, mode=write_mode)
                state["tweet_csv_existing_header"] = existing_header or SUMMARY_CSV_HEADER

        if fmt in {"json", "both"}:
            json_path = str(Path(csv_filename).with_suffix(".json"))
            if state.get("tweet_json_initialized"):
                json_mode = "a"
            else:
                json_mode = "a" if (resume and os.path.exists(json_path)) else "w"
                state["tweet_json_initialized"] = True
            write_json_auto_append(json_path, raw_tweets, mode=json_mode)

        return raw_tweets

    def _persist_follows_outputs(
        self,
        *,
        follows: list[Any],
        csv_filename: str,
        resume: bool,
        save_format: Optional[str] = None,
        raw_json: bool = False,
        write_state: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        state = write_state if isinstance(write_state, dict) else {}
        normalized_follows: list[dict[str, Any]] = []
        csv_rows: list[dict[str, Any]] = []

        for item in follows:
            raw: Any = None
            if isinstance(item, dict):
                raw = item
            elif hasattr(item, "model_dump"):
                try:
                    raw = item.model_dump(mode="json")  # type: ignore[attr-defined]
                except Exception:
                    raw = None
            if not isinstance(raw, dict):
                raw = {"value": str(item)}
            normalized_follows.append(raw)

            target = raw.get("target") if isinstance(raw.get("target"), dict) else {}
            csv_rows.append(
                {
                    "follow_key": _follow_record_key(raw) or "",
                    "type": str(raw.get("type") or "").strip(),
                    "target_username": str(target.get("username") or "").strip(),
                    "target_profile_url": str(target.get("profile_url") or "").strip(),
                    "target_source": str(target.get("source") or "").strip(),
                    "target_raw": str(target.get("raw") or "").strip(),
                    "user_id": str(raw.get("user_id") or "").strip(),
                    "username": str(raw.get("username") or "").strip(),
                    "name": raw.get("name"),
                    "description": raw.get("description"),
                    "location": raw.get("location"),
                    "created_at": raw.get("created_at"),
                    "followers_count": raw.get("followers_count"),
                    "following_count": raw.get("following_count"),
                    "statuses_count": raw.get("statuses_count"),
                    "favourites_count": raw.get("favourites_count"),
                    "media_count": raw.get("media_count"),
                    "listed_count": raw.get("listed_count"),
                    "verified": bool(raw.get("verified", False)),
                    "blue_verified": bool(raw.get("blue_verified", False)),
                    "protected": bool(raw.get("protected", False)),
                    "profile_image_url": raw.get("profile_image_url"),
                    "profile_banner_url": raw.get("profile_banner_url"),
                    "url": raw.get("url"),
                }
            )

        fmt = self._coerce_save_format(save_format) or "none"

        dedupe_on_resume = bool(
            getattr(getattr(self._v4_config, "output", None), "dedupe_on_resume_by_tweet_id", False)
        )
        if resume and dedupe_on_resume and fmt != "none":
            seen_keys = state.get("follows_dedupe_seen_keys")
            if not isinstance(seen_keys, set):
                existing_keys: set[str] = set()
                if fmt in {"csv", "both"}:
                    existing_keys.update(_read_existing_follow_keys_from_csv(csv_filename))
                if fmt in {"json", "both"}:
                    json_path_for_dedupe = str(Path(csv_filename).with_suffix(".json"))
                    existing_keys.update(_read_existing_follow_keys_from_json(json_path_for_dedupe))
                seen_keys = set(existing_keys)
                state["follows_dedupe_seen_keys"] = seen_keys

            filtered_raw: list[dict[str, Any]] = []
            filtered_rows: list[dict[str, Any]] = []
            for raw, row in zip(normalized_follows, csv_rows):
                key = str(row.get("follow_key") or "").strip() or (_follow_record_key(raw) or "")
                if key and key in seen_keys:
                    continue
                if key:
                    seen_keys.add(key)
                filtered_raw.append(raw)
                filtered_rows.append(row)
            normalized_follows = filtered_raw
            csv_rows = filtered_rows

        follows_output: list[dict[str, Any]]
        if raw_json:
            follows_output = []
            for row, csv_row in zip(normalized_follows, csv_rows):
                target = row.get("target") if isinstance(row.get("target"), dict) else {}
                raw_payload = row.get("raw")
                if not isinstance(raw_payload, dict):
                    raw_payload = row
                follows_output.append(
                    {
                        "follow_key": str(csv_row.get("follow_key") or "").strip() or (_follow_record_key(row) or ""),
                        "type": str(row.get("type") or "").strip(),
                        "target": dict(target),
                        "raw": raw_payload,
                    }
                )
        else:
            follows_output = list(normalized_follows)

        if fmt in {"csv", "both"}:
            if state.get("follows_csv_initialized"):
                write_mode = "a"
            else:
                write_mode = "a" if (resume and os.path.exists(csv_filename)) else "w"
                state["follows_csv_initialized"] = True
            if write_mode == "a":
                try:
                    if (not os.path.exists(csv_filename)) or os.path.getsize(csv_filename) <= 0:
                        write_mode = "w"
                except Exception:
                    write_mode = "w"

            if not csv_rows:
                if write_mode == "w" and not os.path.exists(csv_filename):
                    Path(csv_filename).parent.mkdir(parents=True, exist_ok=True)
                    Path(csv_filename).touch()
            else:
                existing_header = state.get("follows_csv_existing_header")
                if (
                    not isinstance(existing_header, list)
                    and write_mode == "a"
                    and os.path.exists(csv_filename)
                    and os.path.getsize(csv_filename) > 0
                ):
                    try:
                        with open(csv_filename, "r", encoding="utf-8", newline="") as handle:
                            reader = csv.reader(handle)
                            existing_header = next(reader, None) or None
                    except Exception:
                        existing_header = None
                    state["follows_csv_existing_header"] = existing_header

                if existing_header and existing_header != FOLLOWS_CSV_HEADER:
                    write_csv(csv_filename, csv_rows, existing_header, mode="a")
                else:
                    write_csv(csv_filename, csv_rows, FOLLOWS_CSV_HEADER, mode=write_mode)
                state["follows_csv_existing_header"] = existing_header or FOLLOWS_CSV_HEADER

        if fmt in {"json", "both"}:
            json_path = str(Path(csv_filename).with_suffix(".json"))
            if state.get("follows_json_initialized"):
                json_mode = "a"
            else:
                json_mode = "a" if (resume and os.path.exists(json_path)) else "w"
                state["follows_json_initialized"] = True
            write_json_auto_append(json_path, follows_output, mode=json_mode)

        return follows_output

    def _persist_profiles_outputs(
        self,
        *,
        profiles: list[Any],
        csv_filename: str,
        resume: bool,
        save_format: Optional[str] = None,
        write_state: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        state = write_state if isinstance(write_state, dict) else {}
        raw_profiles: list[dict[str, Any]] = []
        csv_rows: list[dict[str, Any]] = []

        for item in profiles:
            raw: Any = None
            if isinstance(item, dict):
                raw = item
            elif hasattr(item, "model_dump"):
                try:
                    raw = item.model_dump(mode="json")  # type: ignore[attr-defined]
                except Exception:
                    raw = None
            if not isinstance(raw, dict):
                raw = {"value": str(item)}
            raw_profiles.append(raw)

            input_node = raw.get("input") if isinstance(raw.get("input"), dict) else {}
            csv_rows.append(
                {
                    "profile_key": _profile_record_key(raw) or "",
                    "input_raw": str(input_node.get("raw") or "").strip(),
                    "input_source": str(input_node.get("source") or "").strip(),
                    "user_id": str(raw.get("user_id") or "").strip(),
                    "username": str(raw.get("username") or "").strip(),
                    "name": raw.get("name"),
                    "description": raw.get("description"),
                    "location": raw.get("location"),
                    "created_at": raw.get("created_at"),
                    "followers_count": raw.get("followers_count"),
                    "following_count": raw.get("following_count"),
                    "statuses_count": raw.get("statuses_count"),
                    "favourites_count": raw.get("favourites_count"),
                    "media_count": raw.get("media_count"),
                    "listed_count": raw.get("listed_count"),
                    "verified": bool(raw.get("verified", False)),
                    "blue_verified": bool(raw.get("blue_verified", False)),
                    "protected": bool(raw.get("protected", False)),
                    "profile_image_url": raw.get("profile_image_url"),
                    "profile_banner_url": raw.get("profile_banner_url"),
                    "url": raw.get("url"),
                }
            )

        fmt = self._coerce_save_format(save_format) or "none"

        dedupe_on_resume = bool(
            getattr(getattr(self._v4_config, "output", None), "dedupe_on_resume_by_tweet_id", False)
        )
        if resume and dedupe_on_resume and fmt != "none":
            seen_keys = state.get("profiles_dedupe_seen_keys")
            if not isinstance(seen_keys, set):
                existing_keys: set[str] = set()
                if fmt in {"csv", "both"}:
                    existing_keys.update(_read_existing_profile_keys_from_csv(csv_filename))
                if fmt in {"json", "both"}:
                    json_path_for_dedupe = str(Path(csv_filename).with_suffix(".json"))
                    existing_keys.update(_read_existing_profile_keys_from_json(json_path_for_dedupe))
                seen_keys = set(existing_keys)
                state["profiles_dedupe_seen_keys"] = seen_keys

            filtered_raw: list[dict[str, Any]] = []
            filtered_rows: list[dict[str, Any]] = []
            for raw, row in zip(raw_profiles, csv_rows):
                key = str(row.get("profile_key") or "").strip() or (_profile_record_key(raw) or "")
                if key and key in seen_keys:
                    continue
                if key:
                    seen_keys.add(key)
                filtered_raw.append(raw)
                filtered_rows.append(row)
            raw_profiles = filtered_raw
            csv_rows = filtered_rows

        if fmt in {"csv", "both"}:
            if state.get("profiles_csv_initialized"):
                write_mode = "a"
            else:
                write_mode = "a" if (resume and os.path.exists(csv_filename)) else "w"
                state["profiles_csv_initialized"] = True
            if write_mode == "a":
                try:
                    if (not os.path.exists(csv_filename)) or os.path.getsize(csv_filename) <= 0:
                        write_mode = "w"
                except Exception:
                    write_mode = "w"

            if not csv_rows:
                if write_mode == "w" and not os.path.exists(csv_filename):
                    Path(csv_filename).parent.mkdir(parents=True, exist_ok=True)
                    Path(csv_filename).touch()
            else:
                existing_header = state.get("profiles_csv_existing_header")
                if (
                    not isinstance(existing_header, list)
                    and write_mode == "a"
                    and os.path.exists(csv_filename)
                    and os.path.getsize(csv_filename) > 0
                ):
                    try:
                        with open(csv_filename, "r", encoding="utf-8", newline="") as handle:
                            reader = csv.reader(handle)
                            existing_header = next(reader, None) or None
                    except Exception:
                        existing_header = None
                    state["profiles_csv_existing_header"] = existing_header

                if existing_header and existing_header != PROFILES_CSV_HEADER:
                    write_csv(csv_filename, csv_rows, existing_header, mode="a")
                else:
                    write_csv(csv_filename, csv_rows, PROFILES_CSV_HEADER, mode=write_mode)
                state["profiles_csv_existing_header"] = existing_header or PROFILES_CSV_HEADER

        if fmt in {"json", "both"}:
            json_path = str(Path(csv_filename).with_suffix(".json"))
            if state.get("profiles_json_initialized"):
                json_mode = "a"
            else:
                json_mode = "a" if (resume and os.path.exists(json_path)) else "w"
                state["profiles_json_initialized"] = True
            write_json_auto_append(json_path, raw_profiles, mode=json_mode)

        return raw_profiles

    @staticmethod
    def _build_profile_timeline_csv_filename(
        *,
        save_dir: str,
        custom_csv_name: Optional[str],
        targets: list[dict[str, Any]],
    ) -> str:
        if custom_csv_name:
            return os.path.join(save_dir, str(custom_csv_name))

        username = ""
        if len(targets) == 1:
            username = str(targets[0].get("username") or "").strip().lstrip("@")

        stem = f"profile_timeline_{username or 'batch'}"
        stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_") or "profile_timeline_batch"
        return os.path.join(save_dir, f"{stem}.csv")

    @staticmethod
    def _build_follows_csv_filename(
        *,
        save_dir: str,
        custom_csv_name: Optional[str],
        targets: list[dict[str, Any]],
        follow_type: str,
    ) -> str:
        if custom_csv_name:
            return os.path.join(save_dir, str(custom_csv_name))

        username = ""
        if len(targets) == 1:
            username = str(targets[0].get("username") or "").strip().lstrip("@")

        follow_ref = str(follow_type or "following").strip().lower()
        stem = f"follows_{follow_ref}_{username or 'batch'}"
        stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_") or "follows_batch"
        return os.path.join(save_dir, f"{stem}.csv")

    @staticmethod
    def _build_profiles_csv_filename(
        *,
        save_dir: str,
        custom_csv_name: Optional[str],
        targets: list[dict[str, Any]],
    ) -> str:
        if custom_csv_name:
            return os.path.join(save_dir, str(custom_csv_name))

        username = ""
        if len(targets) == 1:
            username = str(targets[0].get("username") or "").strip().lstrip("@")

        stem = f"profiles_{username or 'batch'}"
        stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_") or "profiles_batch"
        return os.path.join(save_dir, f"{stem}.csv")

    def _load_profile_timeline_resume_cursors(self, *, query_hash: str) -> dict[str, str]:
        if not query_hash:
            return {}
        if self._resume_repo is None or not hasattr(self._resume_repo, "get_checkpoint"):
            return {}
        checkpoint = self._resume_repo.get_checkpoint(query_hash)
        if not isinstance(checkpoint, dict):
            return {}
        raw_cursor = checkpoint.get("cursor")
        if isinstance(raw_cursor, dict):
            payload = raw_cursor
        elif isinstance(raw_cursor, str):
            stripped = raw_cursor.strip()
            if not stripped:
                return {}
            try:
                decoded = json.loads(stripped)
            except Exception:
                return {}
            payload = decoded if isinstance(decoded, dict) else {}
        else:
            return {}
        out: dict[str, str] = {}
        for key, value in payload.items():
            cursor_key = str(key or "").strip()
            cursor_value = str(value or "").strip()
            if cursor_key and cursor_value:
                out[cursor_key] = cursor_value
        return out

    def _save_profile_timeline_resume_state(
        self,
        *,
        query_hash: str,
        resume_cursors: dict[str, str],
        completed: bool,
        limit_reached: bool,
    ) -> None:
        if not query_hash:
            return
        if self._resume_repo is None:
            return
        if completed and not limit_reached and not resume_cursors:
            if hasattr(self._resume_repo, "clear_checkpoint"):
                try:
                    self._resume_repo.clear_checkpoint(query_hash)
                except Exception:
                    pass
            return

        if not hasattr(self._resume_repo, "save_checkpoint"):
            return
        cursor_payload = json.dumps(resume_cursors or {}, separators=(",", ":"))
        try:
            self._resume_repo.save_checkpoint(
                query_hash,
                cursor_payload,
                "profile_timeline",
                "profile_timeline",
            )
        except Exception:
            pass

    def _load_follows_resume_cursors(self, *, query_hash: str) -> dict[str, str]:
        if not query_hash:
            return {}
        if self._resume_repo is None or not hasattr(self._resume_repo, "get_checkpoint"):
            return {}
        checkpoint = self._resume_repo.get_checkpoint(query_hash)
        if not isinstance(checkpoint, dict):
            return {}
        raw_cursor = checkpoint.get("cursor")
        if isinstance(raw_cursor, dict):
            payload = raw_cursor
        elif isinstance(raw_cursor, str):
            stripped = raw_cursor.strip()
            if not stripped:
                return {}
            try:
                decoded = json.loads(stripped)
            except Exception:
                return {}
            payload = decoded if isinstance(decoded, dict) else {}
        else:
            return {}
        out: dict[str, str] = {}
        for key, value in payload.items():
            cursor_key = str(key or "").strip()
            cursor_value = str(value or "").strip()
            if cursor_key and cursor_value:
                out[cursor_key] = cursor_value
        return out

    def _save_follows_resume_state(
        self,
        *,
        query_hash: str,
        resume_cursors: dict[str, str],
        completed: bool,
        limit_reached: bool,
        follow_type: str,
    ) -> None:
        if not query_hash:
            return
        if self._resume_repo is None:
            return
        if completed and not limit_reached and not resume_cursors:
            if hasattr(self._resume_repo, "clear_checkpoint"):
                try:
                    self._resume_repo.clear_checkpoint(query_hash)
                except Exception:
                    pass
            return

        if not hasattr(self._resume_repo, "save_checkpoint"):
            return
        cursor_payload = json.dumps(resume_cursors or {}, separators=(",", ":"))
        try:
            self._resume_repo.save_checkpoint(
                query_hash,
                cursor_payload,
                "follows",
                str(follow_type or "following"),
            )
        except Exception:
            pass

    async def _run_search_pipeline(
        self,
        *,
        search_request: SearchRequest,
        csv_filename: str,
        resume: bool,
        save: bool = False,
        save_format: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        _, logged_in, _, _ = await self.login()
        if not logged_in:
            return []

        effective_save_format = self._resolve_save_format(save_format, save=save)
        search_write_state: dict[str, Any] = {}
        runner_supports_stream = self._supports_kwarg(getattr(self._runner, "run_search"), "on_tweets_batch")
        streaming_active = bool(effective_save_format != "none" and runner_supports_stream)

        async def _on_tweets_batch(batch: list[Any]) -> None:
            if not batch:
                return
            self._persist_tweet_outputs(
                tweets=list(batch),
                csv_filename=csv_filename,
                resume=resume,
                save_format=effective_save_format,
                write_state=search_write_state,
            )

        tweets = []
        try:
            if streaming_active:
                run_result = await self._runner.run_search(
                    search_request,
                    on_tweets_batch=_on_tweets_batch,
                )
            else:
                run_result = await self._runner.run_search(search_request)
            tweets = list(getattr(run_result, "tweets", []) or [])
        except AccountPoolExhausted as exc:
            strict = bool(getattr(self._v4_config.runtime, "strict", False))
            detail = (
                "No usable accounts available for API scraping. "
                "Provide accounts via `accounts_file` (accounts.txt), `cookies_file` (cookies.json), "
                "`env_path` (.env), or `cookies=` (cookie dict/list/header/token)."
            )
            if strict:
                raise AccountPoolExhausted(detail) from exc
            logger.error("%s (%s)", detail, str(exc))
            tweets = []
        except Exception as exc:
            strict = bool(getattr(self._v4_config.runtime, "strict", False))
            if strict:
                raise
            logger.error("Scrape failed detail=%s (set strict=True to raise)", str(exc))
            tweets = []

        if streaming_active:
            raw_tweets = self._persist_tweet_outputs(
                tweets=tweets,
                csv_filename=csv_filename,
                resume=resume,
                save_format="none",
            )
        else:
            raw_tweets = self._persist_tweet_outputs(
                tweets=tweets,
                csv_filename=csv_filename,
                resume=resume,
                save_format=effective_save_format,
            )

        await self.aclose()
        return raw_tweets

    async def _run_profile_timeline_pipeline(
        self,
        *,
        profile_timeline_request: ProfileTimelineRequest,
        csv_filename: str,
        resume: bool,
        query_hash: str,
        save: bool = False,
        save_format: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        _, logged_in, _, _ = await self.login()
        if not logged_in:
            return []

        effective_save_format = self._resolve_save_format(save_format, save=save)
        profile_write_state: dict[str, Any] = {}
        runner_supports_stream = self._supports_kwarg(getattr(self._runner, "run_profile_tweets"), "on_tweets_page")
        streaming_active = bool(effective_save_format != "none" and runner_supports_stream)

        async def _on_tweets_page(batch: list[Any]) -> None:
            if not batch:
                return
            self._persist_tweet_outputs(
                tweets=list(batch),
                csv_filename=csv_filename,
                resume=resume,
                save_format=effective_save_format,
                write_state=profile_write_state,
            )

        run_response: dict[str, Any] = {}
        tweets: list[Any] = []
        resume_cursors: dict[str, str] = dict(profile_timeline_request.initial_cursors or {})
        completed = False
        limit_reached = False

        try:
            if streaming_active:
                raw_response = await self._runner.run_profile_tweets(
                    profile_timeline_request,
                    on_tweets_page=_on_tweets_page,
                )
            else:
                raw_response = await self._runner.run_profile_tweets(profile_timeline_request)
            if isinstance(raw_response, dict):
                run_response = dict(raw_response)
            result = run_response.get("result")
            tweets = list(getattr(result, "tweets", []) or [])
            raw_resume = run_response.get("resume_cursors")
            if isinstance(raw_resume, dict):
                resume_cursors = {}
                for key, value in raw_resume.items():
                    cursor_key = str(key or "").strip()
                    cursor_value = str(value or "").strip()
                    if cursor_key and cursor_value:
                        resume_cursors[cursor_key] = cursor_value
            completed = bool(run_response.get("completed", False))
            limit_reached = bool(run_response.get("limit_reached", False))
        except AccountPoolExhausted as exc:
            strict = bool(getattr(self._v4_config.runtime, "strict", False))
            detail = (
                "No usable accounts available for API scraping. "
                "Provide accounts via `accounts_file` (accounts.txt), `cookies_file` (cookies.json), "
                "`env_path` (.env), or `cookies=` (cookie dict/list/header/token)."
            )
            if strict:
                raise AccountPoolExhausted(detail) from exc
            logger.error("%s (%s)", detail, str(exc))
            tweets = []
        except Exception as exc:
            strict = bool(getattr(self._v4_config.runtime, "strict", False))
            if strict:
                raise
            logger.error("Profile timeline scrape failed detail=%s (set strict=True to raise)", str(exc))
            tweets = []

        if resume:
            self._save_profile_timeline_resume_state(
                query_hash=query_hash,
                resume_cursors=resume_cursors,
                completed=completed,
                limit_reached=limit_reached,
            )

        if streaming_active:
            raw_tweets = self._persist_tweet_outputs(
                tweets=tweets,
                csv_filename=csv_filename,
                resume=resume,
                save_format="none",
            )
        else:
            raw_tweets = self._persist_tweet_outputs(
                tweets=tweets,
                csv_filename=csv_filename,
                resume=resume,
                save_format=effective_save_format,
            )

        await self.aclose()
        return raw_tweets

    async def _run_follows_pipeline(
        self,
        *,
        follows_request: FollowsRequest,
        resume: bool,
        query_hash: str,
        csv_filename: str,
        save: bool = False,
        save_format: Optional[str] = None,
        raw_json: bool = False,
    ) -> list[dict[str, Any]]:
        _, logged_in, _, _ = await self.login()
        if not logged_in:
            return []

        effective_save_format = self._resolve_save_format(save_format, save=save)
        follows_write_state: dict[str, Any] = {}
        runner_supports_stream = self._supports_kwarg(getattr(self._runner, "run_follows"), "on_follows_page")
        streaming_active = bool(effective_save_format != "none" and runner_supports_stream)

        async def _on_follows_page(batch: list[Any]) -> None:
            if not batch:
                return
            self._persist_follows_outputs(
                follows=list(batch),
                csv_filename=csv_filename,
                resume=resume,
                save_format=effective_save_format,
                raw_json=raw_json,
                write_state=follows_write_state,
            )

        follows: list[dict[str, Any]] = []
        resume_cursors: dict[str, str] = dict(follows_request.initial_cursors or {})
        completed = False
        limit_reached = False

        try:
            if streaming_active:
                raw_response = await self._runner.run_follows(
                    follows_request,
                    on_follows_page=_on_follows_page,
                )
            else:
                raw_response = await self._runner.run_follows(follows_request)
            if isinstance(raw_response, dict):
                follows = list(raw_response.get("follows") or [])
                raw_resume = raw_response.get("resume_cursors")
                if isinstance(raw_resume, dict):
                    resume_cursors = {}
                    for key, value in raw_resume.items():
                        cursor_key = str(key or "").strip()
                        cursor_value = str(value or "").strip()
                        if cursor_key and cursor_value:
                            resume_cursors[cursor_key] = cursor_value
                completed = bool(raw_response.get("completed", False))
                limit_reached = bool(raw_response.get("limit_reached", False))
            elif isinstance(raw_response, list):
                follows = [row for row in raw_response if isinstance(row, dict)]
                completed = True
        except AccountPoolExhausted as exc:
            strict = bool(getattr(self._v4_config.runtime, "strict", False))
            detail = (
                "No usable accounts available for API scraping. "
                "Provide accounts via `accounts_file` (accounts.txt), `cookies_file` (cookies.json), "
                "`env_path` (.env), or `cookies=` (cookie dict/list/header/token)."
            )
            if strict:
                raise AccountPoolExhausted(detail) from exc
            logger.error("%s (%s)", detail, str(exc))
            follows = []
        except Exception as exc:
            strict = bool(getattr(self._v4_config.runtime, "strict", False))
            if strict:
                raise
            logger.error("Follows scrape failed detail=%s (set strict=True to raise)", str(exc))
            follows = []

        if resume:
            self._save_follows_resume_state(
                query_hash=query_hash,
                resume_cursors=resume_cursors,
                completed=completed,
                limit_reached=limit_reached,
                follow_type=str(follows_request.follow_type),
            )

        if streaming_active:
            raw_follows = self._persist_follows_outputs(
                follows=follows,
                csv_filename=csv_filename,
                resume=resume,
                save_format="none",
                raw_json=raw_json,
            )
        else:
            raw_follows = self._persist_follows_outputs(
                follows=follows,
                csv_filename=csv_filename,
                resume=resume,
                save_format=effective_save_format,
                raw_json=raw_json,
            )

        await self.aclose()
        return raw_follows

    def scrape(self, **scrape_kwargs):
        canonical_keys = {
            "search_query",
            "all_words",
            "any_words",
            "exact_phrases",
            "exclude_words",
            "hashtags_any",
            "hashtags_exclude",
            "from_users",
            "to_users",
            "mentioning_users",
            "tweet_type",
            "verified_only",
            "blue_verified_only",
            "has_images",
            "has_videos",
            "has_links",
            "has_mentions",
            "has_hashtags",
            "min_likes",
            "min_replies",
            "min_retweets",
            "place",
            "near",
            "within",
        }
        if any(key in scrape_kwargs for key in canonical_keys):
            return asyncio.run(self.asearch(**scrape_kwargs))
        return asyncio.run(self.ascrape(**scrape_kwargs))

    def search(self, **search_kwargs):
        return asyncio.run(self.asearch(**search_kwargs))

    async def asearch(
        self,
        *,
        since: str,
        until: str = None,
        search_query: Optional[str] = None,
        all_words: Union[str, list, None] = None,
        any_words: Union[str, list, None] = None,
        exact_phrases: Union[str, list, None] = None,
        exclude_words: Union[str, list, None] = None,
        hashtags_any: Union[str, list, None] = None,
        hashtags_exclude: Union[str, list, None] = None,
        from_users: Union[str, list, None] = None,
        to_users: Union[str, list, None] = None,
        mentioning_users: Union[str, list, None] = None,
        lang: Optional[str] = None,
        tweet_type: str = "all",
        verified_only: bool = False,
        blue_verified_only: bool = False,
        has_images: bool = False,
        has_videos: bool = False,
        has_links: bool = False,
        has_mentions: bool = False,
        has_hashtags: bool = False,
        min_likes: int = 0,
        min_replies: int = 0,
        min_retweets: int = 0,
        place: Optional[str] = None,
        geocode: Optional[str] = None,
        near: Optional[str] = None,
        within: Optional[str] = None,
        limit: float = float("inf"),
        display_type: str = "Top",
        resume: bool = False,
        save_dir: str = "outputs",
        custom_csv_name: Optional[str] = None,
        max_empty_pages: Optional[int] = None,
        save: bool = False,
        save_format: Optional[str] = None,
    ):
        if not until:
            until = date.today().strftime("%Y-%m-%d")

        normalized_query, query_errors, query_warnings = normalize_search_input(
            {
                "since": since,
                "until": until,
                "search_query": search_query,
                "all_words": all_words,
                "any_words": any_words,
                "exact_phrases": exact_phrases,
                "exclude_words": exclude_words,
                "hashtags_any": hashtags_any,
                "hashtags_exclude": hashtags_exclude,
                "from_users": from_users,
                "to_users": to_users,
                "mentioning_users": mentioning_users,
                "lang": lang,
                "tweet_type": tweet_type,
                "verified_only": verified_only,
                "blue_verified_only": blue_verified_only,
                "has_images": has_images,
                "has_videos": has_videos,
                "has_links": has_links,
                "has_mentions": has_mentions,
                "has_hashtags": has_hashtags,
                "min_likes": min_likes,
                "min_replies": min_replies,
                "min_retweets": min_retweets,
                "place": place,
                "geocode": geocode,
                "near": near,
                "within": within,
            }
        )

        if query_warnings:
            for message in query_warnings:
                warn_deprecated(message)
        if query_errors:
            detail = "; ".join(query_errors)
            if bool(getattr(self._v4_config.runtime, "strict", False)):
                raise ValueError(f"Invalid search input: {detail}")
            logger.warning("Search input had validation errors; continuing with normalized values: %s", detail)

        first_from = next(iter(normalized_query.get("from_users") or []), None)
        first_to = next(iter(normalized_query.get("to_users") or []), None)
        first_mention = next(iter(normalized_query.get("mentioning_users") or []), None)
        first_hashtag = next(iter(normalized_query.get("hashtags_any") or []), None)
        filename_words = (
            normalized_query.get("all_words")
            or normalized_query.get("any_words")
            or normalized_query.get("exact_phrases")
            or []
        )
        csv_filename = build_legacy_csv_filename(
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            since=since,
            until=until,
            words=filename_words,
            from_account=first_from,
            to_account=first_to,
            mention_account=first_mention,
            hashtag=first_hashtag,
        )

        requested_since = since
        initial_cursor: Optional[str] = None
        request_max_empty_pages = self._resolve_max_empty_pages(max_empty_pages)

        query_hash = compute_query_hash(
            {
                "since": requested_since,
                "until": until,
                "lang": lang,
                "display_type": display_type,
                "query": normalized_query,
                "save_dir": save_dir,
                "custom_csv_name": custom_csv_name,
                "max_empty_pages": request_max_empty_pages,
            }
        )
        if resume:
            effective_since, initial_cursor = resolve_resume_start(
                mode=self._effective_resume_mode(),
                csv_path=csv_filename,
                requested_since=requested_since,
                resume_repo=self._resume_repo,
                query_hash=query_hash,
            )
            since = effective_since

        request_limit = self._coerce_request_limit(limit)

        search_request = SearchRequest(
            since=since,
            until=until,
            words=filename_words or None,
            to_account=first_to,
            from_account=first_from,
            mention_account=first_mention,
            hashtag=first_hashtag,
            search_query=normalized_query.get("search_query"),
            all_words=normalized_query.get("all_words"),
            any_words=normalized_query.get("any_words"),
            exact_phrases=normalized_query.get("exact_phrases"),
            exclude_words=normalized_query.get("exclude_words"),
            hashtags_any=normalized_query.get("hashtags_any"),
            hashtags_exclude=normalized_query.get("hashtags_exclude"),
            from_users=normalized_query.get("from_users"),
            to_users=normalized_query.get("to_users"),
            mentioning_users=normalized_query.get("mentioning_users"),
            tweet_type=normalized_query.get("tweet_type"),
            verified_only=bool(normalized_query.get("verified_only", False)),
            blue_verified_only=bool(normalized_query.get("blue_verified_only", False)),
            has_images=bool(normalized_query.get("has_images", False)),
            has_videos=bool(normalized_query.get("has_videos", False)),
            has_links=bool(normalized_query.get("has_links", False)),
            has_mentions=bool(normalized_query.get("has_mentions", False)),
            has_hashtags=bool(normalized_query.get("has_hashtags", False)),
            min_likes=int(normalized_query.get("min_likes") or 0),
            min_replies=int(normalized_query.get("min_replies") or 0),
            min_retweets=int(normalized_query.get("min_retweets") or 0),
            place=normalized_query.get("place"),
            geocode=normalized_query.get("geocode"),
            near=normalized_query.get("near"),
            within=normalized_query.get("within"),
            lang=lang,
            limit=request_limit,
            display_type=display_type,
            resume=resume,
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            initial_cursor=initial_cursor,
            query_hash=query_hash,
            max_empty_pages=request_max_empty_pages,
        )

        return await self._run_search_pipeline(
            search_request=search_request,
            csv_filename=csv_filename,
            resume=resume,
            save=save,
            save_format=save_format,
        )

    async def ascrape(
        self,
        since: str,
        until: str = None,
        words: Union[str, list] = None,
        to_account: str = None,
        from_account: str = None,
        mention_account: str = None,
        lang: str = None,
        limit: float = float("inf"),
        display_type: str = "Top",
        resume: bool = False,
        hashtag: str = None,
        save_dir: str = "outputs",
        filter_replies: bool = False,
        proximity: bool = False,
        geocode: str = None,
        minreplies=None,
        minlikes=None,
        minretweets=None,
        custom_csv_name=None,
        max_empty_pages: Optional[int] = None,
        save: bool = False,
        save_format: Optional[str] = None,
    ):
        if not until:
            until = date.today().strftime("%Y-%m-%d")

        legacy_args_used = any(
            [
                words is not None,
                to_account is not None,
                from_account is not None,
                mention_account is not None,
                hashtag is not None,
                bool(filter_replies),
                minreplies is not None,
                minlikes is not None,
                minretweets is not None,
            ]
        )
        if legacy_args_used:
            warn_deprecated(
                "Legacy query args (`words`, `from_account`, `to_account`, `mention_account`, `hashtag`, "
                "`filter_replies`, `minlikes`, `minreplies`, `minretweets`) are deprecated in v4.x. "
                "Use canonical fields via `search()` / `asearch()` (e.g. `search_query`, `all_words`, "
                "`any_words`, `from_users`, `tweet_type`, `min_likes`)."
            )

        if words and isinstance(words, str):
            words = words.split("//")

        normalized_query, _query_errors, _query_warnings = normalize_search_input(
            {
                "since": since,
                "until": until,
                "words": words,
                "to_account": to_account,
                "from_account": from_account,
                "mention_account": mention_account,
                "hashtag": hashtag,
                "lang": lang,
                "filter_replies": filter_replies,
                "geocode": geocode,
                "minlikes": minlikes,
                "minreplies": minreplies,
                "minretweets": minretweets,
            }
        )

        csv_filename = build_legacy_csv_filename(
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            since=since,
            until=until,
            words=words,
            from_account=from_account,
            to_account=to_account,
            mention_account=mention_account,
            hashtag=hashtag,
        )

        requested_since = since
        initial_cursor: Optional[str] = None
        request_max_empty_pages = self._resolve_max_empty_pages(max_empty_pages)

        query_hash = compute_query_hash(
            {
                "since": requested_since,
                "until": until,
                "query": normalized_query,
                "lang": lang,
                "display_type": display_type,
                "save_dir": save_dir,
                "custom_csv_name": custom_csv_name,
                "max_empty_pages": request_max_empty_pages,
            }
        )

        if resume:
            effective_since, initial_cursor = resolve_resume_start(
                mode=self._effective_resume_mode(),
                csv_path=csv_filename,
                requested_since=requested_since,
                resume_repo=self._resume_repo,
                query_hash=query_hash,
            )
            since = effective_since

        # Keep legacy helper invocation behavior intact even though routing is via Runner.
        self.build_search_url(
            since=since,
            until=until,
            lang=lang,
            display_type=display_type,
            words=words,
            to_account=to_account,
            from_account=from_account,
            mention_account=mention_account,
            hashtag=hashtag,
            filter_replies=filter_replies,
            proximity=proximity,
            geocode=geocode,
            minreplies=minreplies,
            minlikes=minlikes,
            minretweets=minretweets,
            n=self.n_splits,
        )

        request_limit = self._coerce_request_limit(limit)

        search_request = SearchRequest(
            since=since,
            until=until,
            words=words,
            to_account=to_account,
            from_account=from_account,
            mention_account=mention_account,
            hashtag=hashtag,
            search_query=normalized_query.get("search_query"),
            all_words=normalized_query.get("all_words"),
            any_words=normalized_query.get("any_words"),
            exact_phrases=normalized_query.get("exact_phrases"),
            exclude_words=normalized_query.get("exclude_words"),
            hashtags_any=normalized_query.get("hashtags_any"),
            hashtags_exclude=normalized_query.get("hashtags_exclude"),
            from_users=normalized_query.get("from_users"),
            to_users=normalized_query.get("to_users"),
            mentioning_users=normalized_query.get("mentioning_users"),
            tweet_type=normalized_query.get("tweet_type"),
            verified_only=bool(normalized_query.get("verified_only", False)),
            blue_verified_only=bool(normalized_query.get("blue_verified_only", False)),
            has_images=bool(normalized_query.get("has_images", False)),
            has_videos=bool(normalized_query.get("has_videos", False)),
            has_links=bool(normalized_query.get("has_links", False)),
            has_mentions=bool(normalized_query.get("has_mentions", False)),
            has_hashtags=bool(normalized_query.get("has_hashtags", False)),
            min_likes=int(normalized_query.get("min_likes") or 0),
            min_replies=int(normalized_query.get("min_replies") or 0),
            min_retweets=int(normalized_query.get("min_retweets") or 0),
            place=normalized_query.get("place"),
            geocode=normalized_query.get("geocode"),
            near=normalized_query.get("near"),
            within=normalized_query.get("within"),
            lang=lang,
            limit=request_limit,
            display_type=display_type,
            resume=resume,
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            initial_cursor=initial_cursor,
            query_hash=query_hash,
            max_empty_pages=request_max_empty_pages,
        )

        return await self._run_search_pipeline(
            search_request=search_request,
            csv_filename=csv_filename,
            resume=resume,
            save=save,
            save_format=save_format,
        )

    def profile_tweets(self, **profile_kwargs):
        return asyncio.run(self.aprofile_tweets(**profile_kwargs))

    def get_profile_timeline(self, **profile_kwargs):
        return asyncio.run(self.aprofile_tweets(**profile_kwargs))

    async def aget_profile_timeline(self, **profile_kwargs):
        return await self.aprofile_tweets(**profile_kwargs)

    async def aprofile_tweets(
        self,
        *,
        usernames=None,
        profile_urls=None,
        limit: float = float("inf"),
        per_profile_limit: Optional[int] = None,
        max_pages_per_profile: Optional[int] = None,
        resume: bool = False,
        save_dir: str = "outputs",
        custom_csv_name: Optional[str] = None,
        cursor_handoff: bool = False,
        max_account_switches: Optional[int] = None,
        offline: Optional[bool] = None,
        max_empty_pages: Optional[int] = None,
        save: bool = False,
        save_format: Optional[str] = None,
        **legacy_kwargs,
    ):
        if legacy_kwargs:
            unsupported = sorted(legacy_kwargs.keys())
            raise TypeError(
                "aprofile_tweets supports only explicit inputs: "
                "`usernames`, `profile_urls`, `limit`, `per_profile_limit`, `max_pages_per_profile`, "
                "`resume`, `save_dir`, `custom_csv_name`, `cursor_handoff`, `max_account_switches`, `offline`, "
                "`max_empty_pages`, `save`, `save_format`"
                f" (unsupported: {', '.join(unsupported)})"
            )

        normalized = normalize_profile_targets_explicit(
            usernames=usernames,
            profile_urls=profile_urls,
            context="profile_timeline",
        )
        targets = list(normalized.get("targets") or [])
        if not targets:
            logger.info("No valid user target provided for profile timeline request")
            return []

        csv_filename = self._build_profile_timeline_csv_filename(
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            targets=targets,
        )

        request_limit = self._coerce_request_limit(limit)
        request_per_profile_limit = self._coerce_request_limit(per_profile_limit)
        request_max_pages = self._coerce_request_limit(max_pages_per_profile)
        request_max_switches = self._coerce_request_limit(max_account_switches)
        request_max_empty_pages = self._resolve_max_empty_pages(max_empty_pages)
        configured_allow_anonymous = bool(getattr(self._v4_config.operations, "profile_timeline_allow_anonymous", False))
        allow_anonymous = bool(configured_allow_anonymous if offline is None else offline)

        query_hash = compute_query_hash(
            {
                "mode": "profile_timeline",
                "targets": targets,
                "limit": request_limit,
                "per_profile_limit": request_per_profile_limit,
                "max_pages_per_profile": request_max_pages,
                "cursor_handoff": bool(cursor_handoff),
                "max_account_switches": request_max_switches,
                "max_empty_pages": request_max_empty_pages,
                "allow_anonymous": allow_anonymous,
                "save_dir": save_dir,
                "custom_csv_name": custom_csv_name,
            }
        )
        initial_cursors: dict[str, str] = {}
        if resume:
            initial_cursors = self._load_profile_timeline_resume_cursors(query_hash=query_hash)

        profile_timeline_request = ProfileTimelineRequest(
            targets=targets,
            limit=request_limit,
            per_profile_limit=request_per_profile_limit,
            max_pages_per_profile=request_max_pages,
            resume=resume,
            query_hash=query_hash,
            initial_cursors=initial_cursors,
            cursor_handoff=bool(cursor_handoff),
            max_account_switches=request_max_switches,
            allow_anonymous=allow_anonymous,
            max_empty_pages=request_max_empty_pages,
        )

        return await self._run_profile_timeline_pipeline(
            profile_timeline_request=profile_timeline_request,
            csv_filename=csv_filename,
            resume=resume,
            query_hash=query_hash,
            save=save,
            save_format=save_format,
        )

    def get_follows(self, **scrape_kwargs):
        return asyncio.run(self.aget_follows(**scrape_kwargs))

    def get_followers(self, **scrape_kwargs):
        return asyncio.run(self.aget_followers(**scrape_kwargs))

    def get_following(self, **scrape_kwargs):
        return asyncio.run(self.aget_following(**scrape_kwargs))

    def get_verified_followers(self, **scrape_kwargs):
        return asyncio.run(self.aget_verified_followers(**scrape_kwargs))

    async def aget_followers(
        self,
        *,
        usernames=None,
        profile_urls=None,
        user_ids=None,
        limit: float = float("inf"),
        per_profile_limit: Optional[int] = None,
        max_pages_per_profile: Optional[int] = None,
        resume: bool = False,
        cursor_handoff: bool = False,
        max_account_switches: Optional[int] = None,
        save_dir: str = "outputs",
        custom_csv_name: Optional[str] = None,
        max_empty_pages: Optional[int] = None,
        save: bool = False,
        save_format: Optional[str] = None,
        raw_json: bool = False,
        **legacy_kwargs,
    ):
        return await self.aget_follows(
            follow_type="followers",
            usernames=usernames,
            profile_urls=profile_urls,
            user_ids=user_ids,
            limit=limit,
            per_profile_limit=per_profile_limit,
            max_pages_per_profile=max_pages_per_profile,
            resume=resume,
            cursor_handoff=cursor_handoff,
            max_account_switches=max_account_switches,
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            max_empty_pages=max_empty_pages,
            save=save,
            save_format=save_format,
            raw_json=raw_json,
            **legacy_kwargs,
        )

    async def aget_following(
        self,
        *,
        usernames=None,
        profile_urls=None,
        user_ids=None,
        limit: float = float("inf"),
        per_profile_limit: Optional[int] = None,
        max_pages_per_profile: Optional[int] = None,
        resume: bool = False,
        cursor_handoff: bool = False,
        max_account_switches: Optional[int] = None,
        save_dir: str = "outputs",
        custom_csv_name: Optional[str] = None,
        max_empty_pages: Optional[int] = None,
        save: bool = False,
        save_format: Optional[str] = None,
        raw_json: bool = False,
        **legacy_kwargs,
    ):
        return await self.aget_follows(
            follow_type="following",
            usernames=usernames,
            profile_urls=profile_urls,
            user_ids=user_ids,
            limit=limit,
            per_profile_limit=per_profile_limit,
            max_pages_per_profile=max_pages_per_profile,
            resume=resume,
            cursor_handoff=cursor_handoff,
            max_account_switches=max_account_switches,
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            max_empty_pages=max_empty_pages,
            save=save,
            save_format=save_format,
            raw_json=raw_json,
            **legacy_kwargs,
        )

    async def aget_verified_followers(
        self,
        *,
        usernames=None,
        profile_urls=None,
        user_ids=None,
        limit: float = float("inf"),
        per_profile_limit: Optional[int] = None,
        max_pages_per_profile: Optional[int] = None,
        resume: bool = False,
        cursor_handoff: bool = False,
        max_account_switches: Optional[int] = None,
        save_dir: str = "outputs",
        custom_csv_name: Optional[str] = None,
        max_empty_pages: Optional[int] = None,
        save: bool = False,
        save_format: Optional[str] = None,
        raw_json: bool = False,
        **legacy_kwargs,
    ):
        return await self.aget_follows(
            follow_type="verified_followers",
            usernames=usernames,
            profile_urls=profile_urls,
            user_ids=user_ids,
            limit=limit,
            per_profile_limit=per_profile_limit,
            max_pages_per_profile=max_pages_per_profile,
            resume=resume,
            cursor_handoff=cursor_handoff,
            max_account_switches=max_account_switches,
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            max_empty_pages=max_empty_pages,
            save=save,
            save_format=save_format,
            raw_json=raw_json,
            **legacy_kwargs,
        )


    async def aget_follows(
        self,
        *,
        follow_type: str = "following",
        usernames=None,
        profile_urls=None,
        user_ids=None,
        handle=None,
        user_id=None,
        profile_url=None,
        users=None,
        type: Optional[str] = None,
        login: bool = True,
        stay_logged_in: bool = True,
        sleep: float = 2,
        limit: float = float("inf"),
        per_profile_limit: Optional[int] = None,
        max_pages_per_profile: Optional[int] = None,
        resume: bool = False,
        cursor_handoff: bool = False,
        max_account_switches: Optional[int] = None,
        save_dir: str = "outputs",
        custom_csv_name: Optional[str] = None,
        max_empty_pages: Optional[int] = None,
        save: bool = False,
        save_format: Optional[str] = None,
        raw_json: bool = False,
        **legacy_kwargs,
    ):
        legacy_users = legacy_kwargs.pop("users", None)
        legacy_handles = legacy_kwargs.pop("handles", None)
        legacy_usernames = legacy_kwargs.pop("usernames", None)
        legacy_user_ids = legacy_kwargs.pop("user_ids", None)
        legacy_profile_urls = legacy_kwargs.pop("profile_urls", None)
        legacy_handle = legacy_kwargs.pop("handle", None)
        legacy_user_id = legacy_kwargs.pop("user_id", None)
        legacy_profile_url = legacy_kwargs.pop("profile_url", None)
        legacy_type = legacy_kwargs.pop("type", None)
        legacy_login = legacy_kwargs.pop("login", None)
        legacy_stay_logged_in = legacy_kwargs.pop("stay_logged_in", None)
        legacy_sleep = legacy_kwargs.pop("sleep", None)

        if legacy_kwargs:
            unsupported = sorted(legacy_kwargs.keys())
            raise TypeError(
                "aget_follows supports only explicit inputs: "
                "`follow_type`, `usernames`, `profile_urls`, `user_ids`, `limit`, `per_profile_limit`, "
                "`max_pages_per_profile`, `resume`, `cursor_handoff`, `max_account_switches`, "
                "`save_dir`, `custom_csv_name`, `max_empty_pages`, `save`, `save_format`, `raw_json`"
                "; also accepts legacy aliases: `handle`, `user_id`, `profile_url`, `users`, `user_ids`, `type`, "
                "`login`, `stay_logged_in`, `sleep`"
                f" (unsupported: {', '.join(unsupported)})"
            )

        _ = login, stay_logged_in, sleep, legacy_login, legacy_stay_logged_in, legacy_sleep
        legacy_follow_type = str(type or legacy_type or "").strip().lower()
        normalized_follow_type = str(follow_type or "following").strip().lower()
        if legacy_follow_type and normalized_follow_type in {"", "following"}:
            normalized_follow_type = legacy_follow_type
        if normalized_follow_type not in {
            "followers",
            "following",
            "verified_followers",
        }:
            raise ValueError(
                "Unsupported follow_type. Expected one of: "
                "`followers`, `following`, `verified_followers`"
            )

        normalized = normalize_user_targets(
            users=self._merge_input_values(users, legacy_users),
            handles=self._merge_input_values(handle, legacy_handle, legacy_handles),
            usernames=self._merge_input_values(usernames, legacy_usernames),
            user_ids=self._merge_input_values(user_ids, user_id, legacy_user_ids, legacy_user_id),
            profile_urls=self._merge_input_values(profile_urls, profile_url, legacy_profile_urls, legacy_profile_url),
            context=f"follows:{normalized_follow_type}",
        )
        targets = list(normalized.get("targets") or [])
        if not targets:
            logger.info("No valid user target provided for follows request type=%s", normalized_follow_type)
            return []

        csv_filename = self._build_follows_csv_filename(
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            targets=targets,
            follow_type=normalized_follow_type,
        )

        request_limit = self._coerce_request_limit(limit)
        request_per_profile_limit = self._coerce_request_limit(per_profile_limit)
        request_max_pages = self._coerce_request_limit(max_pages_per_profile)
        request_max_switches = self._coerce_request_limit(max_account_switches)
        request_max_empty_pages = self._resolve_max_empty_pages(max_empty_pages)

        query_hash = compute_query_hash(
            {
                "mode": "follows",
                "follow_type": normalized_follow_type,
                "targets": targets,
                "limit": request_limit,
                "per_profile_limit": request_per_profile_limit,
                "max_pages_per_profile": request_max_pages,
                "cursor_handoff": bool(cursor_handoff),
                "max_account_switches": request_max_switches,
                "max_empty_pages": request_max_empty_pages,
                "save_dir": save_dir,
                "custom_csv_name": custom_csv_name,
            }
        )

        initial_cursors: dict[str, str] = {}
        if resume:
            initial_cursors = self._load_follows_resume_cursors(query_hash=query_hash)

        follows_request = FollowsRequest(
            targets=targets,
            follow_type=normalized_follow_type,
            limit=request_limit,
            per_profile_limit=request_per_profile_limit,
            max_pages_per_profile=request_max_pages,
            resume=resume,
            query_hash=query_hash,
            initial_cursors=initial_cursors,
            cursor_handoff=bool(cursor_handoff),
            max_account_switches=request_max_switches,
            max_empty_pages=request_max_empty_pages,
            raw_json=self._coerce_bool_flag(raw_json),
        )

        return await self._run_follows_pipeline(
            follows_request=follows_request,
            resume=resume,
            query_hash=query_hash,
            csv_filename=csv_filename,
            save=save,
            save_format=save_format,
            raw_json=bool(follows_request.raw_json),
        )

    def get_user_information(self, **profiles_kwargs):
        return asyncio.run(self.aget_user_information(**profiles_kwargs))

    async def aget_user_information(
        self,
        login=False,
        usernames=None,
        profile_urls=None,
        include_meta: bool = False,
        save_dir: str = "outputs",
        custom_csv_name: Optional[str] = None,
        save: bool = False,
        save_format: Optional[str] = None,
        **legacy_kwargs,
    ):
        if legacy_kwargs:
            unsupported = sorted(legacy_kwargs.keys())
            raise TypeError(
                "aget_user_information supports only explicit inputs: "
                "`usernames`, `profile_urls`, `include_meta`, `save_dir`, `custom_csv_name`, "
                "`save`, `save_format`"
                f" (unsupported: {', '.join(unsupported)})"
            )

        normalized = normalize_profile_targets_explicit(
            usernames=usernames,
            profile_urls=profile_urls,
            context="profiles",
        )
        targets = list(normalized.get("targets") or [])
        if not targets:
            logger.info("No valid user target provided for profiles request")
            if include_meta:
                return {
                    "items": [],
                    "status_code": 400,
                    "meta": {
                        "requested": 0,
                        "resolved": 0,
                        "failed": 0,
                        "skipped": list(normalized.get("skipped") or []),
                        "errors": [],
                    },
                }
            return []

        csv_filename = self._build_profiles_csv_filename(
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            targets=targets,
        )

        effective_save_format = self._resolve_save_format(save_format, save=save)
        profiles_write_state: dict[str, Any] = {}
        run_profiles_fn = getattr(self._runner, "run_profiles")
        runner_supports_stream = self._supports_kwarg(run_profiles_fn, "on_profiles_batch")
        streaming_active = bool(effective_save_format != "none" and runner_supports_stream)

        async def _on_profiles_batch(batch: list[Any]) -> None:
            if not batch:
                return
            self._persist_profiles_outputs(
                profiles=list(batch),
                csv_filename=csv_filename,
                resume=False,
                save_format=effective_save_format,
                write_state=profiles_write_state,
            )

        profile_request = ProfileRequest(
            targets=targets,
            login=login,
        )
        if streaming_active:
            run_kwargs: dict[str, Any] = {
                "on_profiles_batch": _on_profiles_batch,
            }
            response = await self._runner.run_profiles(
                profile_request,
                **run_kwargs,
            )
        else:
            response = await self._runner.run_profiles(profile_request)

        response_items: list[dict[str, Any]] = []
        if isinstance(response, dict):
            raw_items = response.get("items")
            if isinstance(raw_items, list):
                response_items = [item for item in raw_items if isinstance(item, dict)]
        elif isinstance(response, list):
            response_items = [item for item in response if isinstance(item, dict)]

        if streaming_active:
            response_items = self._persist_profiles_outputs(
                profiles=response_items,
                csv_filename=csv_filename,
                resume=False,
                save_format="none",
            )
        else:
            response_items = self._persist_profiles_outputs(
                profiles=response_items,
                csv_filename=csv_filename,
                resume=False,
                save_format=effective_save_format,
            )
        if isinstance(response, dict):
            response["items"] = response_items

        if include_meta and isinstance(response, dict):
            initial_skipped = list(normalized.get("skipped") or [])
            if initial_skipped:
                meta = response.get("meta")
                if not isinstance(meta, dict):
                    meta = {}
                    response["meta"] = meta
                merged_skipped = list(meta.get("skipped") or [])
                merged_skipped.extend(initial_skipped)
                meta["skipped"] = merged_skipped
            return response
        if response_items:
            return response_items
        if isinstance(response, dict):
            if isinstance(response.get("items"), list):
                return response["items"]
        return []

    def get_last_date_from_csv(self, path):
        max_dt = None
        try:
            with open(path, "r", encoding="utf-8") as handle:
                reader = csv.reader(handle)
                header = next(reader, None)
                if not header:
                    return None
                candidates = ["Timestamp", "legacy.created_at", "created_at", "legacy.createdAt", "legacyCreatedAt"]
                ts_idx = None
                for name in candidates:
                    if name in header:
                        ts_idx = header.index(name)
                        break
                if ts_idx is None:
                    return None

                for row in reader:
                    if len(row) <= ts_idx:
                        continue
                    timestamp_str = row[ts_idx].strip()
                    if not timestamp_str:
                        continue
                    try:
                        dt = datetime.fromisoformat(timestamp_str.replace("Z", ""))
                    except Exception:
                        try:
                            dt = datetime.strptime(timestamp_str, "%a %b %d %H:%M:%S %z %Y")
                        except Exception:
                            dt = None
                    if dt and (max_dt is None or dt > max_dt):
                        max_dt = dt
        except Exception:
            return None

        if max_dt:
            return max_dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return None

    def build_search_url(
        self,
        since: str,
        until: str,
        lang: str = None,
        display_type: str = "Top",
        words: Union[str, list] = None,
        to_account: str = None,
        from_account: str = None,
        mention_account: str = None,
        hashtag: str = None,
        filter_replies: bool = False,
        proximity: bool = False,
        geocode: str = None,
        minreplies: int = None,
        minlikes: int = None,
        minretweets: int = None,
        n: int = 10,
    ) -> List[str]:
        display_type_allowed = {"Top", "Latest", "Image"}
        if display_type not in display_type_allowed:
            raise ValueError(f"display_type must be one of {display_type_allowed}")

        def _parse_bound(value: str) -> datetime:
            raw = str(value or "").strip()
            if not raw:
                raise ValueError("date bound cannot be empty")

            for fmt in ("%Y-%m-%d", "%Y-%m-%d_%H:%M:%S_UTC"):
                try:
                    return datetime.strptime(raw, fmt)
                except Exception:
                    pass

            # Accept ISO timestamps such as `2026-02-08T04:40:08.000Z`.
            try:
                return datetime.fromisoformat(raw.replace("Z", ""))
            except Exception:
                pass

            if len(raw) >= 10:
                try:
                    return datetime.strptime(raw[:10], "%Y-%m-%d")
                except Exception:
                    pass

            raise ValueError(
                "date bound must be in one of formats: "
                "`YYYY-MM-DD`, `YYYY-MM-DD_HH:MM:SS_UTC`, or ISO datetime"
            )

        since_dt = _parse_bound(since)
        until_dt = _parse_bound(until)
        total_days = (until_dt - since_dt).days
        if total_days < 1:
            total_days = 1

        if n == -1:
            n = total_days
            interval = 1
        else:
            interval = total_days / n

        from_str = f"(from%3A{from_account})%20" if from_account else ""
        to_str = f"(to%3A{to_account})%20" if to_account else ""
        mention_str = f"(%40{mention_account})%20" if mention_account else ""
        hashtag_str = f"(%23{hashtag})%20" if hashtag else ""

        if words:
            if isinstance(words, list) and len(words) > 1:
                words_str = "(" + "%20OR%20".join(w.strip() for w in words) + ")%20"
            else:
                single_word = words[0] if isinstance(words, list) else words
                words_str = f"({single_word})%20"
        else:
            words_str = ""

        lang_str = f"lang%3A{lang}" if lang else ""

        if display_type.lower() == "latest":
            display_type_str = "&f=live"
        elif display_type.lower() == "image":
            display_type_str = "&f=image"
        else:
            display_type_str = ""

        filter_replies_str = "%20-filter%3Areplies" if filter_replies else ""
        proximity_str = "&lf=on" if proximity else ""
        geocode_str = f"%20geocode%3A{geocode}" if geocode else ""
        minreplies_str = f"%20min_replies%3A{minreplies}" if minreplies is not None else ""
        minlikes_str = f"%20min_faves%3A{minlikes}" if minlikes is not None else ""
        minretweets_str = f"%20min_retweets%3A{minretweets}" if minretweets is not None else ""

        urls = []
        for i in range(n):
            current_since = since_dt + timedelta(days=i * interval)
            current_until = since_dt + timedelta(days=(i + 1) * interval)
            if current_until > until_dt:
                current_until = until_dt

            since_part = f"since%3A{current_since.strftime('%Y-%m-%d')}%20"
            until_part = f"until%3A{current_until.strftime('%Y-%m-%d')}%20"

            path = (
                "https://x.com/search?q="
                + words_str
                + from_str
                + to_str
                + mention_str
                + hashtag_str
                + until_part
                + since_part
                + lang_str
                + filter_replies_str
                + geocode_str
                + minreplies_str
                + minlikes_str
                + minretweets_str
                + "&src=typed_query"
                + display_type_str
                + proximity_str
            )

            urls.append(path)
            if current_until >= until_dt:
                break

        return urls
