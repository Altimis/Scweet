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
    """Scweet v5 client — simple API-only Twitter/X scraper.

    Credential options (pick one):
        s = Scweet(cookies_file="cookies.json")       # path to cookies JSON
        s = Scweet(auth_token="abc123")               # single auth_token cookie
        s = Scweet(cookies={"auth_token": "...", "ct0": "..."})  # inline dict
        s = Scweet(env_path=".env")                   # .env file with AUTH_TOKEN/CT0
        s = Scweet(db_path="existing.db")             # reuse a pre-populated state DB

    Args:
        cookies_file: Path to a JSON file containing account cookies.
        auth_token: Single auth_token cookie value. The ct0 (CSRF) token will be
            bootstrapped automatically via a request to x.com.
        cookies: Inline cookies dict, list of account dicts, or JSON string.
        accounts_file: Path to a colon-separated accounts.txt file.
        env_path: Path to a .env file with AUTH_TOKEN, CT0, USERNAME, etc.
        db_path: Path to the SQLite state file. The constructor arg always takes
            precedence over any db_path set in ``config``. Default: scweet_state.db.
        config: Optional ScweetConfig for advanced settings.
        provision: If True (default), import credentials into the DB on init.
            Set to False to skip credential import and use only accounts that
            already exist in the database (useful when the DB is pre-populated).
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
        config: Optional[ScweetConfig] = None,
        provision: bool = True,
    ):
        if config is not None:
            self._config = config.model_copy(deep=True)
        else:
            self._config = ScweetConfig()

        # Constructor db_path always wins (predictable precedence)
        self._config.db_path = db_path

        self._cookies_file = cookies_file
        self._auth_token = auth_token
        self._cookies = cookies
        self._accounts_file = accounts_file
        self._env_path = env_path

        self._init_core(provision=provision)

    @property
    def config(self) -> ScweetConfig:
        return self._config

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
                            "Check your credentials (auth_token, ct0/CSRF).",
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

        tx_kwargs: dict[str, Any] = {"proxy": cfg.proxy, "user_agent": cfg.api_user_agent}
        if cfg.api_http_impersonate:
            tx_kwargs["impersonate"] = cfg.api_http_impersonate
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
        display_type: str = "Top",
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
        display_type: str = "Top",
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
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch tweets from user timelines. Returns list of tweet dicts (same schema as :meth:`search`)."""
        return asyncio.run(
            self.aget_profile_tweets(
                users, limit=limit, max_empty_pages=max_empty_pages,
                resume=resume, save=save, save_format=save_format, save_name=save_name,
            )
        )

    async def aget_profile_tweets(
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
        """Async variant of :meth:`get_profile_tweets`."""
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
        )

        response = await self._runner.run_profile_tweets(request)

        result = response.get("result") if isinstance(response, dict) else response
        tweets = [self._tweet_to_dict(t) for t in (getattr(result, "tweets", None) or [])]

        if save:
            name = save_name or self._build_save_name("profile_tweets", users=users)
            self._save_output(tweets, "profile_tweets", save_format, save_name=name)

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
        users: list[str],
        *,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Fetch profile metadata for the given users. Returns list of user dicts.

        Each dict has: ``user_id``, ``username``, ``name``, ``description``,
        ``location``, ``followers_count``, ``following_count``, ``verified``,
        ``blue_verified``, ``profile_image_url``, and more.
        """
        return asyncio.run(self.aget_user_info(users, save=save, save_format=save_format, save_name=save_name))

    async def aget_user_info(
        self,
        users: list[str],
        *,
        save: bool = False,
        save_format: Optional[str] = None,
        save_name: Optional[str] = None,
    ) -> list[dict]:
        """Async variant of :meth:`get_user_info`."""
        from .models import ProfileRequest
        from .user_identity import normalize_user_targets

        resolved = normalize_user_targets(users=users)
        targets = resolved.get("targets", [])
        handles = [t.get("username") or t.get("handle") or t.get("raw", "") for t in targets]
        request = ProfileRequest(handles=handles, targets=targets)

        response = await self._runner.run_profiles(request)

        if isinstance(response, dict):
            items = response.get("items", [])
        else:
            items = getattr(response, "items", None) or []
        if not isinstance(items, list):
            items = []

        if save:
            name = save_name or self._build_save_name("user_info", users=users)
            self._save_output(items, "user_info", save_format, save_name=name)

        return items

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
            _tweet_ops = {"search", "profile_tweets"}
            _user_ops = {"followers", "following", "user_info"}
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
