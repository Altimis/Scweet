from __future__ import annotations

import asyncio
import logging
import os
import warnings
from datetime import date, timedelta
from typing import Any, Optional

from .config import ScweetConfig
from .exceptions import ScweetError

logger = logging.getLogger(__name__)


class Scweet:
    """Scweet v5 client — an API-only reader of X/Twitter.

    The first path uses one value. Copy the ``auth_token`` cookie of a logged-in
    account and pass it; Scweet builds the rest:

        s = Scweet(auth_token="abc123")

    For several accounts, or a proxy per account, list them in a file:

        s = Scweet(cookies_file="cookies.json")

    After the first run the accounts live in a state file, so a later run needs
    no credential:

        s = Scweet()   # reads scweet_state.db

    Args:
        auth_token: The ``auth_token`` cookie of one account. Scweet bootstraps
            the ct0 (CSRF) token from it with a request to x.com. The shortest
            path to a first result.
        cookies_file: Path to a JSON file of accounts. It accepts a list of
            account records, an export of a browser cookie extension (a list of
            ``{"name": ..., "value": ...}`` objects), or a raw cookie mapping.
            Use this for several accounts or a proxy per account.
        cookies: The same shapes as ``cookies_file``, passed inline as a dict,
            a list, or a JSON string.
        accounts_file: Path to a colon-separated ``accounts.txt``
            (``username:password:email:email_password:2fa:auth_token``).
        env_path: Path to a ``.env`` file with AUTH_TOKEN, CT0, USERNAME.
        db_path: Path to the SQLite state file that holds the accounts between
            runs. It is the location of that state, not where the tweets go; a
            run returns the tweets and, with ``save=True``, writes them to the
            output directory. The constructor value wins over ``config``.
            Default: scweet_state.db.
        proxy: A proxy URL for every account, e.g.
            "http://user:pass@proxy.example.com:8000". Optional for a small run,
            recommended for volume. Put ``{session}`` in the URL for one exit IP
            per account. For a proxy per account, set it in each cookies.json
            entry. The constructor value wins over ``config``.
        manifest_scrape_on_init: If True, read fresh GraphQL query IDs from the
            bundle of X at startup, so a run survives a rotation of the IDs
            without a library update. Or call ``refresh_manifest()`` at any time.
            Default: False.
        config: A ScweetConfig for the advanced settings.
        provision: If True (default), import the credentials into the state file
            on init. Set to False to use only the accounts already in the file,
            for example when it is pre-populated. It does not buy or create
            accounts.
    """

    def __init__(
        self,
        *,
        cookies_file: Optional[str] = None,
        auth_token: Optional[str] = None,
        cookies: Any = None,
        accounts_file: Optional[str] = None,
        env_path: Optional[str] = None,
        db_path: str = "scweet_state.db",
        proxy: Optional[str] = None,
        manifest_scrape_on_init: Optional[bool] = None,
        config: Optional[ScweetConfig] = None,
        provision: bool = True,
    ):
        if config is not None:
            self._config = config.model_copy(deep=True)
        else:
            self._config = ScweetConfig()

        # Constructor db_path always wins (predictable precedence)
        self._config.db_path = db_path
        # Constructor proxy always wins over config
        if proxy is not None:
            self._config.proxy = proxy
        # Constructor manifest_scrape_on_init wins over config
        if manifest_scrape_on_init is not None:
            self._config.manifest_scrape_on_init = manifest_scrape_on_init

        self._cookies_file = cookies_file
        self._auth_token = auth_token
        self._cookies = cookies
        self._accounts_file = accounts_file
        self._env_path = env_path

        self._init_core(provision=provision)

    @property
    def config(self) -> ScweetConfig:
        return self._config

    def refresh_manifest(self) -> dict[str, dict[str, str]]:
        """Read fresh GraphQL query ids from the live bundle of X.

        X rotates a query id without notice, and a stale id answers 404 for
        every request. Call this when requests start to fail, or on a schedule.
        Returns the ids that changed: ``{operation: {"old": ..., "new": ...}}``.
        """
        old = {
            key: value
            for key, value in self._manifest_provider.get_manifest_sync().query_ids.items()
        }
        fresh = self._manifest_provider.scrape_from_x_sync(strict=True, force=True)
        changes: dict[str, dict[str, str]] = {}
        for key, new_id in fresh.query_ids.items():
            old_id = old.get(key)
            if old_id != new_id:
                changes[key] = {"old": old_id or "", "new": new_id}
        return changes

    @property
    def db(self):
        from .db import ScweetDB

        return ScweetDB(
            self._config.db_path,
            account_daily_requests_limit=self._config.daily_requests_limit,
            account_daily_tweets_limit=self._config.daily_tweets_limit,
        )

    def _init_core(self, *, provision: bool = True) -> None:
        from .account_session import AccountSessionBuilder
        from .api_engine import ApiEngine
        from .auth import import_accounts_to_db
        from .manifest import ManifestProvider
        from .outputs import write_csv
        from .repos import AccountsRepo, ResumeRepo, RunsRepo
        from .runner import Runner
        from .transaction import TransactionIdProvider

        cfg = self._config
        db_path = cfg.db_path

        self._accounts_repo = AccountsRepo(
            db_path,
            lease_ttl_s=cfg.lease_ttl_s,
            daily_pages_limit=cfg.daily_requests_limit,
            daily_tweets_limit=cfg.daily_tweets_limit,
            require_auth_material=True,
        )
        self._runs_repo = RunsRepo(db_path)
        self._resume_repo = ResumeRepo(db_path)

        # Provision accounts from constructor sources
        if provision:
            cookies_payload = self._cookies
            if cookies_payload is None and self._auth_token:
                cookies_payload = {"auth_token": self._auth_token}

            has_sources = bool(
                self._accounts_file or self._cookies_file or self._env_path or cookies_payload is not None
            )
            if has_sources:
                source_desc = (
                    self._cookies_file or self._accounts_file or self._env_path
                    or ("auth_token" if self._auth_token else "inline cookies")
                )
                logger.info("Provisioning accounts from %s", source_desc)
                runtime_options = {"proxy": cfg.proxy}
                try:
                    imported = import_accounts_to_db(
                        db_path,
                        accounts_file=self._accounts_file,
                        cookies_file=self._cookies_file,
                        env_path=self._env_path,
                        cookies_payload=cookies_payload,
                        bootstrap_strategy="auto",
                        runtime=runtime_options,
                    )
                    if imported == 0:
                        warnings.warn(
                            "Account provisioning produced no usable accounts. "
                            "The auth_token is usually expired or wrong. "
                            "Check the credentials (auth_token, ct0/CSRF); the first "
                            "call will fail until one account is usable.",
                            RuntimeWarning,
                            stacklevel=3,
                        )
                except Exception:
                    logger.exception("Account provisioning failed")
                    warnings.warn(
                        "Account provisioning failed. Check your credentials. "
                        "See logs for details.",
                        RuntimeWarning,
                        stacklevel=3,
                    )

        self._manifest_provider = ManifestProvider(
            db_path=db_path,
            manifest_url=cfg.manifest_url,
            ttl_s=cfg.manifest_ttl_s,
        )
        if cfg.manifest_scrape_on_init:
            try:
                self._manifest_provider.scrape_from_x_sync(strict=True)
            except Exception:
                logger.exception("Live manifest scrape failed; continuing with cached manifest")
        elif cfg.manifest_update_on_init:
            try:
                self._manifest_provider.refresh_sync(strict=True)
            except Exception:
                logger.exception("Manifest refresh failed; continuing with cached manifest")

        tx_kwargs: dict[str, Any] = {
            "proxy": cfg.proxy,
            "user_agent": cfg.api_user_agent,
            "init_attempts": cfg.transaction_init_attempts,
            "init_backoff_s": cfg.transaction_init_backoff_s,
        }
        if cfg.api_http_impersonate:
            tx_kwargs["impersonate"] = cfg.api_http_impersonate
        tx_cookies = self._get_cookies_for_transaction_init()
        if tx_cookies:
            tx_kwargs["cookies"] = tx_cookies
        self._transaction_id_provider = TransactionIdProvider(**tx_kwargs)

        self._api_engine = ApiEngine(
            config=cfg,
            accounts_repo=self._accounts_repo,
            manifest_provider=self._manifest_provider,
            transaction_id_provider=self._transaction_id_provider,
        )

        http_mode = getattr(cfg.api_http_mode, "value", cfg.api_http_mode)
        session_kwargs: dict[str, Any] = {
            "api_http_mode": str(http_mode or "auto"),
            "proxy": cfg.proxy,
        }
        if cfg.api_http_impersonate:
            session_kwargs["impersonate"] = cfg.api_http_impersonate
        if cfg.api_user_agent:
            session_kwargs["user_agent"] = cfg.api_user_agent
        self._account_session_builder = AccountSessionBuilder(**session_kwargs)

        self._runner = Runner(
            config=cfg,
            repos={
                "accounts_repo": self._accounts_repo,
                "runs_repo": self._runs_repo,
                "resume_repo": self._resume_repo,
            },
            engines={
                "engine": self._api_engine,
                "account_session_builder": self._account_session_builder,
            },
            outputs={"write_csv": write_csv},
        )

    def _get_cookies_for_transaction_init(self) -> Optional[dict]:
        """Get cookies from an eligible account for CT bootstrap (only needs auth_token + ct0)."""
        try:
            from .repos import _cookies_to_dict
            from .schema import AccountTable
            from .storage import session_scope
            from sqlalchemy import select

            with session_scope(self._config.db_path) as session:
                stmt = (
                    select(AccountTable)
                    .where(AccountTable.cookies_json.isnot(None))
                    .where(AccountTable.auth_token.isnot(None))
                    .limit(1)
                )
                account = session.execute(stmt).scalar_one_or_none()
                if account is None:
                    return None
                cookies = _cookies_to_dict(account.cookies_json)
                if cookies.get("auth_token"):
                    return cookies
        except Exception:
            pass
        return None

    # ── Search ──────────────────────────────────────────────────────────

    def search(
        self,
        query: str = "",
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        # Structured filters (all optional, merged with query):
        all_words: Optional[list[str]] = None,
        any_words: Optional[list[str]] = None,
        exact_phrases: Optional[list[str]] = None,
        exclude_words: Optional[list[str]] = None,
        hashtags_any: Optional[list[str]] = None,
        hashtags_exclude: Optional[list[str]] = None,
        from_users: Optional[list[str]] = None,
        to_users: Optional[list[str]] = None,
        mentioning_users: Optional[list[str]] = None,
        tweet_type: Optional[str] = None,
        verified_only: Optional[bool] = None,
        blue_verified_only: Optional[bool] = None,
        has_images: Optional[bool] = None,
        has_videos: Optional[bool] = None,
        has_links: Optional[bool] = None,
        has_mentions: Optional[bool] = None,
        has_hashtags: Optional[bool] = None,
        min_likes: Optional[int] = None,
        min_replies: Optional[int] = None,
        min_retweets: Optional[int] = None,
        place: Optional[str] = None,
        geocode: Optional[str] = None,
        near: Optional[str] = None,
        within: Optional[str] = None,
        # Standard params:
        lang: Optional[str] = None,
        display_type: str = "Latest",
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Search tweets. Returns list of tweet dicts. Raises on failure.

        Args:
            query: Raw search string (Twitter advanced search operators supported).
            since: Start date ``YYYY-MM-DD``. Defaults to 30 days ago.
            until: End date ``YYYY-MM-DD``. Defaults to today.
            limit: Max tweets to collect. Always set this — without a limit,
                scraping continues until results are exhausted or daily caps are hit.
            save: Write results to disk (CSV by default).
            save_format: ``"csv"``, ``"json"``, or ``"both"``.
            resume: Resume from the last saved checkpoint for this query.

        Returns:
            List of tweet dicts. Each dict has: ``tweet_id``, ``timestamp``,
            ``user`` (``screen_name``, ``name``), ``text``, ``likes``,
            ``retweets``, ``comments``, ``tweet_url``, ``media``
            (``image_links``), ``raw``. CSV output flattens ``user`` and
            ``media`` into separate columns.
        """
        return asyncio.run(
            self.asearch(
                query,
                since=since,
                until=until,
                all_words=all_words,
                any_words=any_words,
                exact_phrases=exact_phrases,
                exclude_words=exclude_words,
                hashtags_any=hashtags_any,
                hashtags_exclude=hashtags_exclude,
                from_users=from_users,
                to_users=to_users,
                mentioning_users=mentioning_users,
                tweet_type=tweet_type,
                verified_only=verified_only,
                blue_verified_only=blue_verified_only,
                has_images=has_images,
                has_videos=has_videos,
                has_links=has_links,
                has_mentions=has_mentions,
                has_hashtags=has_hashtags,
                min_likes=min_likes,
                min_replies=min_replies,
                min_retweets=min_retweets,
                place=place,
                geocode=geocode,
                near=near,
                within=within,
                lang=lang,
                display_type=display_type,
                limit=limit,
                max_empty_pages=max_empty_pages,
                resume=resume,
                save=save,
                save_format=save_format,
                save_name=save_name,
            )
        )

    async def asearch(
        self,
        query: str = "",
        *,
        since: Optional[str] = None,
        until: Optional[str] = None,
        # Structured filters (all optional, merged with query):
        all_words: Optional[list[str]] = None,
        any_words: Optional[list[str]] = None,
        exact_phrases: Optional[list[str]] = None,
        exclude_words: Optional[list[str]] = None,
        hashtags_any: Optional[list[str]] = None,
        hashtags_exclude: Optional[list[str]] = None,
        from_users: Optional[list[str]] = None,
        to_users: Optional[list[str]] = None,
        mentioning_users: Optional[list[str]] = None,
        tweet_type: Optional[str] = None,
        verified_only: Optional[bool] = None,
        blue_verified_only: Optional[bool] = None,
        has_images: Optional[bool] = None,
        has_videos: Optional[bool] = None,
        has_links: Optional[bool] = None,
        has_mentions: Optional[bool] = None,
        has_hashtags: Optional[bool] = None,
        min_likes: Optional[int] = None,
        min_replies: Optional[int] = None,
        min_retweets: Optional[int] = None,
        place: Optional[str] = None,
        geocode: Optional[str] = None,
        near: Optional[str] = None,
        within: Optional[str] = None,
        # Standard params:
        lang: Optional[str] = None,
        display_type: str = "Latest",
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`search`. See :meth:`search` for full docs."""
        from .models import SearchRequest
        from .resume import compute_query_hash, resolve_resume_start

        if not since:
            since = (date.today() - timedelta(days=30)).strftime("%Y-%m-%d")
        if not until:
            until = date.today().strftime("%Y-%m-%d")

        effective_max_empty = max_empty_pages or self._config.max_empty_pages

        query_hash = compute_query_hash({
            "since": since,
            "until": until,
            "query": query,
            "lang": lang,
            "display_type": display_type,
            "max_empty_pages": effective_max_empty,
        })

        initial_cursor: Optional[str] = None
        if resume:
            since, initial_cursor = resolve_resume_start(
                mode="db_cursor",
                csv_path=None,
                requested_since=since,
                resume_repo=self._resume_repo,
                query_hash=query_hash,
            )

        search_request = SearchRequest(
            since=since,
            until=until,
            search_query=query or None,
            all_words=all_words,
            any_words=any_words,
            exact_phrases=exact_phrases,
            exclude_words=exclude_words,
            hashtags_any=hashtags_any,
            hashtags_exclude=hashtags_exclude,
            from_users=from_users,
            to_users=to_users,
            mentioning_users=mentioning_users,
            tweet_type=tweet_type,
            verified_only=verified_only,
            blue_verified_only=blue_verified_only,
            has_images=has_images,
            has_videos=has_videos,
            has_links=has_links,
            has_mentions=has_mentions,
            has_hashtags=has_hashtags,
            min_likes=min_likes,
            min_replies=min_replies,
            min_retweets=min_retweets,
            place=place,
            geocode=geocode,
            near=near,
            within=within,
            lang=lang,
            limit=limit,
            display_type=display_type,
            resume=resume,
            initial_cursor=initial_cursor,
            query_hash=query_hash,
            max_empty_pages=effective_max_empty,
        )

        result = await self._runner.run_search(search_request)

        tweets = [self._tweet_to_dict(t) for t in (result.tweets or [])]

        if save:
            name = save_name or self._build_save_name("search", query=query, since=since, until=until, from_users=from_users)
            self._save_output(tweets, "search", save_format, save_name=name)

        return tweets

    # ── Profile Tweets ──────────────────────────────────────────────────

    def get_profile_tweets(
        self,
        users: list[str],
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        include_replies: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch tweets from user timelines. Returns list of tweet dicts (same schema as :meth:`search`).

        Pass ``include_replies=True`` to also collect the replies of each user.
        """
        return asyncio.run(
            self.aget_profile_tweets(
                users, limit=limit, max_empty_pages=max_empty_pages,
                resume=resume, include_replies=include_replies,
                save=save, save_format=save_format, save_name=save_name,
            )
        )

    async def aget_profile_tweets(
        self,
        users: list[str],
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        include_replies: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`get_profile_tweets`."""
        return await self._run_profile_timeline(
            users,
            "profile_timeline_with_replies" if include_replies else "profile_timeline",
            save_operation="profile_tweets",
            limit=limit,
            max_empty_pages=max_empty_pages,
            resume=resume,
            save=save,
            save_format=save_format,
            save_name=save_name,
        )

    def get_profile_media(
        self,
        users: list[str],
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch the media tweets of user timelines. Returns list of tweet dicts (same schema as :meth:`search`)."""
        return asyncio.run(
            self.aget_profile_media(
                users, limit=limit, max_empty_pages=max_empty_pages,
                resume=resume, save=save, save_format=save_format, save_name=save_name,
            )
        )

    async def aget_profile_media(
        self,
        users: list[str],
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`get_profile_media`."""
        return await self._run_profile_timeline(
            users,
            "profile_media",
            save_operation="profile_media",
            limit=limit,
            max_empty_pages=max_empty_pages,
            resume=resume,
            save=save,
            save_format=save_format,
            save_name=save_name,
        )

    async def _run_profile_timeline(
        self,
        users: list[str],
        timeline_operation: str,
        *,
        save_operation: str,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        from .models import ProfileTimelineRequest
        from .user_identity import normalize_user_targets

        resolved = normalize_user_targets(users=users)
        targets = resolved.get("targets", [])
        effective_max_empty = max_empty_pages or self._config.max_empty_pages
        request = ProfileTimelineRequest(
            targets=targets,
            limit=limit,
            resume=resume,
            allow_anonymous=self._config.profile_timeline_allow_anonymous,
            max_empty_pages=effective_max_empty,
            timeline_operation=timeline_operation,
        )

        response = await self._runner.run_profile_tweets(request)

        result = response.get("result") if isinstance(response, dict) else response
        tweets = [self._tweet_to_dict(t) for t in (getattr(result, "tweets", None) or [])]

        if save:
            name = save_name or self._build_save_name(save_operation, users=users)
            self._save_output(tweets, save_operation, save_format, save_name=name)

        return tweets

    # ── Followers / Following ───────────────────────────────────────────

    def get_followers(
        self,
        users: list[str],
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch followers of the given users. Returns list of user dicts.

        Pass ``raw_json=True`` to include the full GraphQL payload under a ``raw`` key.
        """
        return asyncio.run(
            self.aget_followers(
                users, limit=limit, max_empty_pages=max_empty_pages,
                resume=resume, raw_json=raw_json, save=save, save_format=save_format,
                save_name=save_name,
            )
        )

    async def aget_followers(
        self,
        users: list[str],
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`get_followers`."""
        return await self._run_follows(
            users, "followers", limit=limit, max_empty_pages=max_empty_pages,
            resume=resume, raw_json=raw_json, save=save, save_format=save_format,
            save_name=save_name,
        )

    def get_following(
        self,
        users: list[str],
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch accounts that the given users follow. Returns list of user dicts.

        Pass ``raw_json=True`` to include the full GraphQL payload under a ``raw`` key.
        """
        return asyncio.run(
            self.aget_following(
                users, limit=limit, max_empty_pages=max_empty_pages,
                resume=resume, raw_json=raw_json, save=save, save_format=save_format,
                save_name=save_name,
            )
        )

    async def aget_following(
        self,
        users: list[str],
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`get_following`."""
        return await self._run_follows(
            users, "following", limit=limit, max_empty_pages=max_empty_pages,
            resume=resume, raw_json=raw_json, save=save, save_format=save_format,
            save_name=save_name,
        )

    def get_verified_followers(
        self,
        users: list[str],
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch the verified followers of the given users. Returns list of user dicts.

        Pass ``raw_json=True`` to include the full GraphQL payload under a ``raw`` key.
        """
        return asyncio.run(
            self.aget_verified_followers(
                users, limit=limit, max_empty_pages=max_empty_pages,
                resume=resume, raw_json=raw_json, save=save, save_format=save_format,
                save_name=save_name,
            )
        )

    async def aget_verified_followers(
        self,
        users: list[str],
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`get_verified_followers`."""
        return await self._run_follows(
            users, "verified_followers", limit=limit, max_empty_pages=max_empty_pages,
            resume=resume, raw_json=raw_json, save=save, save_format=save_format,
            save_name=save_name,
        )

    async def _run_follows(
        self,
        users: list[str],
        follow_type: str,
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        resume: bool = False,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        from .models import FollowsRequest
        from .user_identity import normalize_user_targets

        resolved = normalize_user_targets(users=users)
        targets = resolved.get("targets", [])
        effective_max_empty = max_empty_pages or self._config.max_empty_pages
        request = FollowsRequest(
            targets=targets,
            follow_type=follow_type,
            limit=limit,
            resume=resume,
            raw_json=raw_json,
            max_empty_pages=effective_max_empty,
        )

        response = await self._runner.run_follows(request)

        items = self._extract_follows_items(response)

        if save:
            name = save_name or self._build_save_name(follow_type, users=users)
            self._save_output(items, follow_type, save_format, save_name=name)

        return items

    # ── User Info ───────────────────────────────────────────────────────

    def get_user_info(
        self,
        users: Optional[list[str]] = None,
        *,
        user_ids: Optional[list[str]] = None,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch profile metadata for the given users. Returns list of user dicts.

        Each dict has: ``user_id``, ``username``, ``name``, ``description``,
        ``location``, ``followers_count``, ``following_count``, ``verified``,
        ``blue_verified``, ``profile_image_url``, and more.

        Pass ``user_ids`` to look up numeric rest ids. ``users`` and ``user_ids``
        can combine; the rows keep the input order where possible.
        """
        return asyncio.run(
            self.aget_user_info(
                users, user_ids=user_ids, save=save, save_format=save_format, save_name=save_name,
            )
        )

    async def aget_user_info(
        self,
        users: Optional[list[str]] = None,
        *,
        user_ids: Optional[list[str]] = None,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`get_user_info`."""
        from .models import ProfileRequest, UserIdsRequest
        from .user_identity import normalize_user_targets

        items: list[dict] = []

        if users:
            resolved = normalize_user_targets(users=users)
            targets = resolved.get("targets", [])
            handles = [t.get("username") or t.get("handle") or t.get("raw", "") for t in targets]
            request = ProfileRequest(handles=handles, targets=targets)

            response = await self._runner.run_profiles(request)
            items.extend(self._extract_items(response))

        ids = [str(u).strip() for u in (user_ids or []) if str(u).strip()]
        if ids:
            ids_response = await self._runner.run_users_by_ids(UserIdsRequest(user_ids=ids))
            # X answers 403 with an HTML page for this lookup on some
            # connections. A silent empty list would hide that refusal.
            id_items = self._extract_items_or_raise(
                ids_response,
                operation="the id lookup",
                hint="The block is per connection and usually short. Retry, "
                "or look the profiles up by username instead.",
            )
            items.extend(id_items)

        if save:
            name = save_name or self._build_save_name("user_info", users=users or ids)
            self._save_output(items, "user_info", save_format, save_name=name)

        return items

    # ── Tweet lookup / replies / reposters ──────────────────────────────

    def get_tweet_info(
        self,
        tweet_ids: list[str],
        *,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch tweets by id. Returns list of tweet dicts (same schema as :meth:`search`).

        A missing or deleted tweet gives no row and no error. Pass
        ``raw_json=True`` to return the raw API JSON instead of normalized dicts.
        """
        return asyncio.run(
            self.aget_tweet_info(
                tweet_ids, raw_json=raw_json, save=save, save_format=save_format, save_name=save_name,
            )
        )

    async def aget_tweet_info(
        self,
        tweet_ids: list[str],
        *,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`get_tweet_info`."""
        from .models import TweetLookupRequest

        ids = [str(t).strip() for t in (tweet_ids or []) if str(t).strip()]
        request = TweetLookupRequest(tweet_ids=ids, raw_json=raw_json)

        response = await self._runner.run_tweet_info(request)
        items = self._extract_items_or_raise(
            response,
            operation="the tweet lookup",
            hint="A deleted id gives no row and no error; a refusal raises. Retry.",
        )

        if save:
            name = save_name or self._build_save_name("tweet_info")
            self._save_output(items, "tweet_info", save_format, save_name=name)

        return items

    def get_tweet_replies(
        self,
        tweet_id: str,
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch the replies of a tweet. Returns list of tweet dicts (same schema as :meth:`search`).

        The focal tweet itself is not a reply, so it gives no row. Pass
        ``raw_json=True`` to return the raw API JSON instead of normalized dicts.
        """
        return asyncio.run(
            self.aget_tweet_replies(
                tweet_id, limit=limit, max_empty_pages=max_empty_pages,
                raw_json=raw_json, save=save, save_format=save_format, save_name=save_name,
            )
        )

    async def aget_tweet_replies(
        self,
        tweet_id: str,
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`get_tweet_replies`."""
        from .models import TweetRepliesRequest

        effective_max_empty = max_empty_pages or self._config.max_empty_pages
        request = TweetRepliesRequest(
            tweet_id=str(tweet_id).strip(),
            limit=limit,
            max_empty_pages=effective_max_empty,
            raw_json=raw_json,
        )

        response = await self._runner.run_tweet_replies(request)
        items = self._extract_items(response)

        if save:
            name = save_name or self._build_save_name("tweet_replies")
            self._save_output(items, "tweet_replies", save_format, save_name=name)

        return items

    def get_reposters(
        self,
        tweet_id: str,
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch the users that reposted a tweet. Returns list of user dicts.

        Pass ``raw_json=True`` to return the raw API JSON instead of normalized dicts.
        """
        return asyncio.run(
            self.aget_reposters(
                tweet_id, limit=limit, max_empty_pages=max_empty_pages,
                raw_json=raw_json, save=save, save_format=save_format, save_name=save_name,
            )
        )

    async def aget_reposters(
        self,
        tweet_id: str,
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`get_reposters`."""
        from .models import RepostersRequest

        effective_max_empty = max_empty_pages or self._config.max_empty_pages
        request = RepostersRequest(
            tweet_id=str(tweet_id).strip(),
            limit=limit,
            max_empty_pages=effective_max_empty,
            raw_json=raw_json,
        )

        response = await self._runner.run_reposters(request)
        items = self._extract_items(response)

        if save:
            name = save_name or self._build_save_name("reposters")
            self._save_output(items, "reposters", save_format, save_name=name)

        return items

    # ── User search / trends ────────────────────────────────────────────

    def search_users(
        self,
        query: str,
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Search users. Returns list of user dicts.

        Pass ``raw_json=True`` to return the raw API JSON instead of normalized dicts.
        """
        return asyncio.run(
            self.asearch_users(
                query, limit=limit, max_empty_pages=max_empty_pages,
                raw_json=raw_json, save=save, save_format=save_format, save_name=save_name,
            )
        )

    async def asearch_users(
        self,
        query: str,
        *,
        limit: Optional[int] = None,
        max_empty_pages: Optional[int] = None,
        raw_json: bool = False,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`search_users`."""
        from .models import SearchUsersRequest

        effective_max_empty = max_empty_pages or self._config.max_empty_pages
        request = SearchUsersRequest(
            query=str(query),
            limit=limit,
            max_empty_pages=effective_max_empty,
            raw_json=raw_json,
        )

        response = await self._runner.run_search_users(request)
        items = self._extract_items(response)

        if save:
            name = save_name or self._build_save_name("search_users", query=query)
            self._save_output(items, "search_users", save_format, save_name=name)

        return items

    def get_trending(self) -> list[dict]:
        """Fetch the current trends. Returns list of trend dicts.

        Each dict has: ``name``, ``context``, ``trend_id``, and ``raw``.
        """
        return asyncio.run(self.aget_trending())

    async def aget_trending(self) -> list[dict]:
        """Async variant of :meth:`get_trending`."""
        response = await self._runner.run_trending()
        return self._extract_items_or_raise(
            response, operation="the trends", hint="Retry; the failure is usually short."
        )

    # ── Output helpers ──────────────────────────────────────────────────

    @staticmethod
    def _build_save_name(
        operation: str,
        *,
        query: Optional[str] = None,
        since: Optional[str] = None,
        until: Optional[str] = None,
        from_users: Optional[list[str]] = None,
        users: Optional[list[str]] = None,
    ) -> str:
        """Build a descriptive file name like 'bitcoin_2024-01-01_2024-06-01'."""
        import re

        # Pick the most descriptive part
        if query:
            part = "_".join(query.split()[:3])
        elif from_users:
            part = "_".join(from_users[:3])
        elif users:
            part = "_".join(users[:3])
        else:
            part = operation

        # Sanitize for filesystem
        part = re.sub(r'[^\w\-.]', '_', part).strip('_') or operation

        # Append date range if available
        if since and until:
            return f"{part}_{since}_{until}"
        elif since:
            return f"{part}_{since}"
        return part

    def _save_output(
        self, rows: list[dict], operation: str, save_format: Optional[str],
        save_name: Optional[str] = None,
    ) -> None:
        if not rows:
            logger.warning("save=True but no results to write for operation '%s'", operation)
            return

        fmt = (save_format or self._config.save_format or "csv").lower().strip()
        save_dir = self._config.save_dir or "outputs"
        os.makedirs(save_dir, exist_ok=True)

        if save_name:
            # Strip extension if user provided one
            base_name = save_name.rsplit(".", 1)[0] if "." in save_name else save_name
        else:
            base_name = operation

        base = os.path.join(save_dir, base_name)

        if fmt in ("csv", "both"):
            from .outputs import TWEET_COLUMN_ORDER, USER_COLUMN_ORDER, write_csv_auto_header
            _tweet_ops = {"search", "profile_tweets", "profile_media", "tweet_info", "tweet_replies"}
            _user_ops = {"followers", "following", "user_info", "reposters", "search_users"}
            if operation in _tweet_ops:
                csv_rows = [self._flatten_tweet_for_csv(r) for r in rows]
                preferred_order = TWEET_COLUMN_ORDER
            elif operation in _user_ops:
                csv_rows = rows
                preferred_order = USER_COLUMN_ORDER
            else:
                csv_rows = rows
                preferred_order = None
            path = f"{base}.csv"
            write_csv_auto_header(path, csv_rows, mode="a", preferred_order=preferred_order)
            logger.info("Saved %d rows to %s", len(rows), path)

        if fmt in ("json", "both"):
            from .outputs import write_json_auto_append
            path = f"{base}.json"
            write_json_auto_append(path, rows, mode="a")
            logger.info("Saved %d rows to %s", len(rows), path)

    @staticmethod
    def _tweet_to_dict(tweet: Any) -> dict:
        if isinstance(tweet, dict):
            return tweet
        if hasattr(tweet, "model_dump"):
            return tweet.model_dump()
        return dict(tweet)

    @staticmethod
    def _flatten_tweet_for_csv(d: dict) -> dict:
        """Return a CSV-safe copy of a tweet dict with nested fields flattened.

        user.screen_name → user_screen_name, user.name → user_name
        media.image_links → image_links (list serialized as JSON in the cell)
        """
        out = dict(d)
        user = out.pop("user", None)
        if isinstance(user, dict):
            out["user_screen_name"] = user.get("screen_name") or ""
            out["user_name"] = user.get("name") or ""
        media = out.pop("media", None)
        if isinstance(media, dict):
            out["image_links"] = media.get("image_links") or []
        return out

    @staticmethod
    def _extract_items(response: Any) -> list[dict]:
        if isinstance(response, dict):
            items = response.get("items")
        else:
            items = getattr(response, "items", None)
        if isinstance(items, list):
            return items
        return []

    @staticmethod
    def _extract_items_or_raise(response: Any, *, operation: str, hint: str = "") -> list[dict]:
        """The items of a single-shot answer, or an error that names the refusal.

        An empty list with a non-200 status is a network failure or a refusal
        of X, and a silent empty list reads as "this data does not exist".
        """
        items = Scweet._extract_items(response)
        status = response.get("status_code") if isinstance(response, dict) else None
        if not items and status not in (None, 200):
            from .exceptions import EngineError

            message = f"X refused {operation} (HTTP {status}), and no rows arrived."
            raise EngineError(message + (f" {hint}" if hint else " Retry."))
        return items

    @staticmethod
    def _extract_follows_items(response: Any) -> list[dict]:
        if isinstance(response, dict):
            for key in ("follows", "items"):
                items = response.get(key)
                if isinstance(items, list):
                    return items
            result = response.get("result")
            if result is not None:
                items = getattr(result, "items", None)
                if isinstance(items, list):
                    return items
        items = getattr(response, "items", None)
        if isinstance(items, list):
            return items
        return []
