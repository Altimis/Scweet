from __future__ import annotations

import asyncio
import csv
import logging
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union, List

from .v4.api_engine import ApiEngine
from .v4.account_session import AccountSessionBuilder
from .v4.auth import import_accounts_to_db
from .v4.config import ScweetConfig, build_config_from_legacy_init_kwargs
from .v4.exceptions import AccountPoolExhausted
from .v4.manifest import ManifestProvider
from .v4.flatten import flatten_for_csv
from .v4.mappers import build_legacy_csv_filename
from .v4.models import FollowsRequest, ProfileRequest, SearchRequest
from .v4.outputs import write_csv, write_csv_auto_header
from .v4.resume import compute_query_hash, resolve_resume_start
from .v4.repos import AccountsRepo, ResumeRepo, RunsRepo
from .v4.runner import Runner
from .v4.transaction import TransactionIdProvider
from .v4.warnings import warn_deprecated, warn_legacy_import_path

logger = logging.getLogger(__name__)


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

    def _init_v4_core(self) -> None:
        db_path = self._v4_config.storage.db_path
        lease_ttl_s = max(1, int(getattr(self._v4_config.operations, "account_lease_ttl_s", 120)))
        self._accounts_repo = AccountsRepo(
            db_path,
            lease_ttl_s=lease_ttl_s,
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

        # Phase 5: Tweet search scraping is API-only regardless of legacy mode/engine selection.
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
            repo = AccountsRepo(effective_db_path, require_auth_material=True)
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

    def scrape(self, **scrape_kwargs):
        return asyncio.run(self.ascrape(**scrape_kwargs))

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
    ):
        if not until:
            until = date.today().strftime("%Y-%m-%d")

        if words and isinstance(words, str):
            words = words.split("//")

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
        query_hash = compute_query_hash(
            {
                "since": requested_since,
                "until": until,
                "words": words,
                "to_account": to_account,
                "from_account": from_account,
                "mention_account": mention_account,
                "hashtag": hashtag,
                "lang": lang,
                "display_type": display_type,
                "save_dir": save_dir,
                "custom_csv_name": custom_csv_name,
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

        _, logged_in, _, _ = await self.login()
        if not logged_in:
            return {}

        request_limit: Optional[int]
        if limit in (None, float("inf")):
            request_limit = None
        else:
            try:
                request_limit = int(limit)
            except Exception:
                request_limit = None

        search_request = SearchRequest(
            since=since,
            until=until,
            words=words,
            to_account=to_account,
            from_account=from_account,
            mention_account=mention_account,
            hashtag=hashtag,
            lang=lang,
            limit=request_limit,
            display_type=display_type,
            resume=resume,
            save_dir=save_dir,
            custom_csv_name=custom_csv_name,
            initial_cursor=initial_cursor,
            query_hash=query_hash,
        )

        tweets = []
        try:
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
        except Exception:
            tweets = []

        raw_tweets: list[dict[str, Any]] = []
        flat_rows: list[dict[str, Any]] = []
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
            flat_rows.append(flatten_for_csv(raw))

        write_mode = "a" if (resume and os.path.exists(csv_filename)) else "w"
        write_csv_auto_header(csv_filename, flat_rows, mode=write_mode)

        await self.aclose()
        return raw_tweets

    def get_follows(self, **scrape_kwargs):
        return asyncio.run(self.aget_follows(**scrape_kwargs))

    def get_followers(self, **scrape_kwargs):
        return asyncio.run(self.aget_followers(**scrape_kwargs))

    def get_following(self, **scrape_kwargs):
        return asyncio.run(self.aget_following(**scrape_kwargs))

    def get_verified_followers(self, **scrape_kwargs):
        return asyncio.run(self.aget_verified_followers(**scrape_kwargs))

    async def aget_followers(self, handle, login=True, stay_logged_in=True, sleep=2):
        return await self.aget_follows(
            handle=handle,
            type="followers",
            login=login,
            stay_logged_in=stay_logged_in,
            sleep=sleep,
        )

    async def aget_following(self, handle, login=True, stay_logged_in=True, sleep=2):
        return await self.aget_follows(
            handle=handle,
            type="following",
            login=login,
            stay_logged_in=stay_logged_in,
            sleep=sleep,
        )

    async def aget_verified_followers(self, handle, login=True, stay_logged_in=True, sleep=2):
        return await self.aget_follows(
            handle=handle,
            type="verified_followers",
            login=login,
            stay_logged_in=stay_logged_in,
            sleep=sleep,
        )

    async def aget_follows(self, handle, type="following", login=True, stay_logged_in=True, sleep=2):
        assert type in ["followers", "verified_followers", "following"]
        response = await self._runner.run_follows(
            FollowsRequest(
                handle=handle,
                type=type,
                login=login,
                stay_logged_in=stay_logged_in,
                sleep=sleep,
            )
        )
        if isinstance(response, dict):
            follows = response.get("follows")
            if isinstance(follows, list):
                return follows
        return []

    def get_user_information(self, **profiles_kwargs):
        return asyncio.run(self.aget_user_information(**profiles_kwargs))

    async def aget_user_information(self, handles, login=False):
        response = await self._runner.run_profiles(
            ProfileRequest(
                handles=list(handles),
                login=login,
            )
        )
        if isinstance(response, dict):
            if isinstance(response.get("profiles"), dict):
                return response["profiles"]
            if all(isinstance(key, str) for key in response.keys()) and "status_code" not in response:
                return response
        return {}

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
