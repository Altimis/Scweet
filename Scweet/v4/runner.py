from __future__ import annotations

import asyncio
from datetime import datetime
import hashlib
import inspect
import json
import logging
from typing import Any, Optional
import uuid

from .cooldown import compute_cooldown
from .exceptions import AccountPoolExhausted, AccountSessionBuildError, EngineError
from .limiter import TokenBucketLimiter
from .models import RunStats, SearchRequest, SearchResult
from .queue import InMemoryTaskQueue
from .scheduler import build_tasks_for_intervals, split_time_intervals

_TS_FMT = "%Y-%m-%d_%H:%M:%S_UTC"
_DATE_FMT = "%Y-%m-%d"
_AUTH_ERROR_CODES = {401, 403, 404}
_TRANSIENT_CODES = {429, 598, 599}
logger = logging.getLogger(__name__)


def _resolve(container: Any, *names: str) -> Any:
    if container is None:
        return None
    if isinstance(container, dict):
        for name in names:
            if name in container:
                return container[name]
        return None
    for name in names:
        if hasattr(container, name):
            return getattr(container, name)
    return None


def _iter_config_sections(config: Any):
    yield config
    section_names = (
        "pool",
        "runtime",
        "engine",
        "storage",
        "accounts",
        "operations",
        "resume",
        "output",
        "manifest",
    )
    if isinstance(config, dict):
        for name in section_names:
            yield config.get(name)
        return
    for name in section_names:
        yield getattr(config, name, None)


def _config_value(config: Any, key: str, default: Any) -> Any:
    for section in _iter_config_sections(config):
        if section is None:
            continue
        if isinstance(section, dict):
            if key in section and section[key] is not None:
                return section[key]
            continue
        if hasattr(section, key):
            value = getattr(section, key)
            if value is not None:
                return value
    return default


def _is_transient_status(status_code: int) -> bool:
    if status_code in _TRANSIENT_CODES:
        return True
    return 500 <= status_code < 600


async def _maybe_await(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _bootstrap_token_async(auth_token: str, timeout_s: int = 30) -> Optional[dict]:
    from .auth import bootstrap_cookies_from_auth_token

    return await asyncio.to_thread(bootstrap_cookies_from_auth_token, auth_token, timeout_s=timeout_s)


async def _bootstrap_creds_async(
    account_record: dict[str, Any], runtime_options: dict[str, Any], timeout_s: int = 180
) -> Optional[dict]:
    from .nodriver_bootstrap import abootstrap_cookies_from_credentials

    return await abootstrap_cookies_from_credentials(
        account_record,
        proxy=runtime_options.get("proxy"),
        user_agent=runtime_options.get("user_agent"),
        headless=bool(runtime_options.get("headless", True)),
        disable_images=bool(runtime_options.get("disable_images", False)),
        code_callback=runtime_options.get("code_callback"),
        timeout_s=int(timeout_s),
    )


class Runner:
    def __init__(self, config, repos, engines, outputs):
        self.config = config
        self.outputs = outputs

        self.accounts_repo = _resolve(repos, "accounts_repo", "accounts")
        self.runs_repo = _resolve(repos, "runs_repo", "runs")
        self.resume_repo = _resolve(repos, "resume_repo", "resume")

        self.search_engine = self._resolve_engine(engines, "search_tweets")
        self.profile_engine = self._resolve_engine(engines, "get_profiles")
        self.follows_engine = self._resolve_engine(engines, "get_follows")
        self.account_session_builder = _resolve(engines, "account_session_builder", "session_builder")

        self.queue_cls = InMemoryTaskQueue
        self._repair_attempted_keys: set[str] = set()
        self._repair_source_records: Optional[list[dict[str, Any]]] = None
        self._repair_policy_logged_none: bool = False

    def _resolve_engine(self, engines: Any, method_name: str):
        direct = engines if hasattr(engines, method_name) else None
        if direct is not None:
            return direct

        for candidate_name in (
            "engine",
            "search_engine",
            "api_engine",
            "browser_engine",
            "api",
            "browser",
            "selected_engine",
        ):
            candidate = _resolve(engines, candidate_name)
            if candidate is not None and hasattr(candidate, method_name):
                return candidate
        return None

    async def run_search(self, search_request):
        # Reset per-run repair state to keep repair attempts bounded.
        self._repair_attempted_keys = set()
        self._repair_source_records = None
        self._repair_policy_logged_none = False

        request = self._coerce_search_request(search_request)
        if self.search_engine is None:
            raise EngineError("No search engine available for run_search")
        if self.accounts_repo is None:
            raise AccountPoolExhausted("No accounts repository available")
        global_limit = self._normalize_global_limit(request.limit)

        normalized_since, normalized_until = self._normalize_bounds(request.since, request.until)
        base_query = request.model_dump()
        base_query["since"] = normalized_since
        base_query["until"] = normalized_until
        hash_payload = dict(base_query)
        hash_payload.pop("query_hash", None)
        hash_payload.pop("initial_cursor", None)

        request_query_hash = request.query_hash if isinstance(request.query_hash, str) else None
        if request_query_hash and request_query_hash.strip():
            query_hash = request_query_hash.strip()
        else:
            query_hash = self._query_hash(hash_payload)

        resume_checkpoint_enabled = bool(
            request.resume
            and query_hash
            and self.resume_repo is not None
            and hasattr(self.resume_repo, "save_checkpoint")
        )

        run_id = str(uuid.uuid4())
        stats = RunStats(tweets_count=0, tasks_total=0, tasks_done=0, tasks_failed=0, retries=0)
        collected_tweets: list[Any] = []
        queue: Optional[InMemoryTaskQueue] = None
        workers: list[asyncio.Task] = []
        worker_results: list[Any] = []
        failure: Optional[BaseException] = None
        stats_lock = asyncio.Lock()
        global_stop_event = asyncio.Event()
        leased_accounts: dict[str, dict[str, Any]] = {}
        handed_off_lease_ids: set[str] = set()

        try:
            if self.runs_repo is not None and hasattr(self.runs_repo, "create_run"):
                created = await _maybe_await(self.runs_repo.create_run(query_hash, base_query))
                if created:
                    run_id = str(created)

            n_intervals = max(1, int(_config_value(self.config, "n_splits", 1)))
            min_interval_s = max(1, int(_config_value(self.config, "scheduler_min_interval_s", 300)))
            intervals = split_time_intervals(
                base_query["since"],
                base_query["until"],
                n_intervals,
                min_interval_s,
            )

            priority = int(_config_value(self.config, "priority", 1))
            tasks = build_tasks_for_intervals(base_query, run_id, priority, intervals)
            if request.initial_cursor and tasks:
                first_query = tasks[0].setdefault("query", {})
                first_query["cursor"] = request.initial_cursor
            stats.tasks_total = len(tasks)

            concurrency = max(1, int(_config_value(self.config, "concurrency", len(tasks) or 1)))
            # Keep standby workers available for account-switch retries even when the initial task
            # count is small.
            workers_requested = concurrency
            accounts = await _maybe_await(
                self.accounts_repo.acquire_leases(
                    workers_requested,
                    run_id=run_id,
                    worker_id_prefix="v4w",
                )
            )
            accounts = list(accounts or [])
            if not accounts:
                stats.tasks_failed = stats.tasks_total
                raise AccountPoolExhausted("No eligible account could be leased")
            for account in accounts:
                lease_id = str(account.get("lease_id") or "").strip()
                if lease_id:
                    leased_accounts[lease_id] = account
                logger.info(
                    "Account leased username=%s id=%s lease_id=%s",
                    account.get("username"),
                    account.get("id"),
                    account.get("lease_id"),
                )

            queue = self.queue_cls(stop_event=global_stop_event)
            await queue.enqueue(tasks)

            seen_tweet_ids: set[str] = set()
            for idx, account in enumerate(accounts):
                lease_id = str(account.get("lease_id") or "").strip()
                if lease_id:
                    handed_off_lease_ids.add(lease_id)
                workers.append(
                    asyncio.create_task(
                        self._run_worker_with_heartbeat(
                            worker_id=f"acct:{idx}",
                            account=account,
                            queue=queue,
                            stats=stats,
                            stats_lock=stats_lock,
                            tweets_out=collected_tweets,
                            seen_tweet_ids=seen_tweet_ids,
                            query_hash=query_hash,
                            checkpoint_enabled=resume_checkpoint_enabled,
                            global_limit=global_limit,
                            stop_event=global_stop_event,
                        )
                    )
                )

            worker_results = list(await asyncio.gather(*workers, return_exceptions=True))
        except BaseException as exc:
            failure = exc
        finally:
            if workers:
                pending = [worker for worker in workers if not worker.done()]
                for worker in pending:
                    worker.cancel()
                if pending:
                    drained = await asyncio.gather(*pending, return_exceptions=True)
                    if not worker_results:
                        worker_results = list(drained)

            await self._emergency_release_leases(
                leased_accounts=leased_accounts,
                handed_off_lease_ids=handed_off_lease_ids,
            )

            if queue is not None:
                queue.cancel_pending()

            stats.tweets_count = len(collected_tweets)
            limit_reached = self._is_limit_reached(global_limit, stats.tweets_count)
            final_status = self._final_status(stats, worker_results, failure, limit_reached=limit_reached)

            if self.runs_repo is not None and hasattr(self.runs_repo, "finalize_run"):
                await _maybe_await(
                    self.runs_repo.finalize_run(
                        run_id,
                        final_status,
                        stats.tweets_count,
                        stats.model_dump(),
                    )
                )
            if (
                resume_checkpoint_enabled
                and final_status == "completed"
                and not limit_reached
                and self.resume_repo is not None
                and hasattr(self.resume_repo, "clear_checkpoint")
            ):
                # Completed run means the planned interval set finished, so the cursor checkpoint
                # is no longer needed for continuation.
                try:
                    await _maybe_await(self.resume_repo.clear_checkpoint(query_hash))
                except Exception:
                    pass

        if failure is not None:
            raise failure

        return SearchResult(tweets=collected_tweets, stats=stats)

    def _runtime_options_for_bootstrap(self) -> dict[str, Any]:
        return {
            "proxy": _config_value(self.config, "proxy", None),
            "user_agent": _config_value(self.config, "user_agent", None),
            "headless": bool(_config_value(self.config, "headless", True)),
            "disable_images": bool(_config_value(self.config, "disable_images", False)),
            "code_callback": _config_value(self.config, "code_callback", None),
        }

    def _load_repair_source_records(self) -> list[dict[str, Any]]:
        if self._repair_source_records is not None:
            return list(self._repair_source_records)

        records: list[dict[str, Any]] = []
        try:
            from .auth import load_accounts_txt, load_env_account

            accounts_file = _config_value(self.config, "accounts_file", None)
            env_path = _config_value(self.config, "env_path", None)
            if isinstance(accounts_file, str) and accounts_file.strip():
                records.extend(load_accounts_txt(accounts_file))
            if isinstance(env_path, str) and env_path.strip():
                records.extend(load_env_account(env_path))
        except Exception:
            records = []

        self._repair_source_records = list(records)
        return list(records)

    async def _attempt_account_repair(self, account: dict[str, Any], status_code: int) -> bool:
        if status_code not in _AUTH_ERROR_CODES:
            return False
        if self.accounts_repo is None or not hasattr(self.accounts_repo, "upsert_account"):
            return False

        strategy_raw = _config_value(self.config, "bootstrap_strategy", "auto")
        strategy_value = getattr(strategy_raw, "value", strategy_raw)
        strategy = str(strategy_value or "auto").strip().lower()
        if strategy == "none":
            if not self._repair_policy_logged_none:
                logger.info("Account repair skipped bootstrap_strategy=none")
                self._repair_policy_logged_none = True
            return False

        allow_token_bootstrap = strategy in {"auto", "token_only"}
        allow_creds_bootstrap = strategy in {"auto", "nodriver_only"}

        username = account.get("username")
        auth_token = account.get("auth_token")
        key = str(username or auth_token or account.get("id") or "")
        if not key:
            return False
        if key in self._repair_attempted_keys:
            return False
        self._repair_attempted_keys.add(key)

        runtime_options = self._runtime_options_for_bootstrap()

        # Token-first repair.
        if allow_token_bootstrap and isinstance(auth_token, str) and auth_token.strip():
            try:
                cookies = await _bootstrap_token_async(auth_token.strip(), timeout_s=30)
            except Exception:
                cookies = None
            if cookies:
                from .auth import normalize_account_record

                normalized = normalize_account_record({"username": username or key, "cookies": cookies})
                try:
                    self.accounts_repo.upsert_account(normalized)
                except Exception:
                    pass
                logger.info("Account repair succeeded via auth_token username=%s", username or "<unknown>")
                return True

        # Credentials repair (if creds are available from current sources).
        if not allow_creds_bootstrap:
            logger.info(
                "Account repair not possible or failed username=%s status_code=%s",
                username or "<unknown>",
                status_code,
            )
            return False

        source_records = self._load_repair_source_records()
        matched: Optional[dict[str, Any]] = None
        if isinstance(auth_token, str) and auth_token.strip():
            for record in source_records:
                if record.get("auth_token") == auth_token:
                    matched = record
                    break
        if matched is None and isinstance(username, str) and username.strip():
            for record in source_records:
                if record.get("username") == username:
                    matched = record
                    break

        if matched and matched.get("password"):
            try:
                cookies = await _bootstrap_creds_async(matched, runtime_options, timeout_s=180)
            except Exception:
                cookies = None
            if cookies:
                from .auth import normalize_account_record

                normalized = normalize_account_record(
                    {"username": matched.get("username") or username or key, "cookies": cookies}
                )
                try:
                    self.accounts_repo.upsert_account(normalized)
                except Exception:
                    pass
                logger.info("Account repair succeeded via credentials username=%s", username or "<unknown>")
                return True

        logger.info(
            "Account repair not possible or failed username=%s status_code=%s",
            username or "<unknown>",
            status_code,
        )
        return False

    async def run_profiles(self, profile_request):
        if self.profile_engine is None:
            raise EngineError("No engine available for run_profiles")
        return await _maybe_await(self.profile_engine.get_profiles(profile_request))

    async def run_follows(self, follows_request):
        if self.follows_engine is None:
            raise EngineError("No engine available for run_follows")
        return await _maybe_await(self.follows_engine.get_follows(follows_request))

    async def _run_worker_with_heartbeat(
        self,
        *,
        worker_id: str,
        account: dict[str, Any],
        queue: InMemoryTaskQueue,
        stats: RunStats,
        stats_lock: asyncio.Lock,
        tweets_out: list[Any],
        seen_tweet_ids: set[str],
        query_hash: Optional[str] = None,
        checkpoint_enabled: bool = False,
        global_limit: Optional[int] = None,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        lease_id = str(account.get("lease_id") or "").strip()
        ttl_s = max(1, int(_config_value(self.config, "account_lease_ttl_s", 120)))
        heartbeat_every_s = max(0.0, float(_config_value(self.config, "account_lease_heartbeat_s", 30.0)))

        heartbeat_stop = asyncio.Event()
        heartbeat_task: Optional[asyncio.Task] = None
        can_heartbeat = (
            bool(lease_id)
            and heartbeat_every_s > 0
            and self.accounts_repo is not None
            and hasattr(self.accounts_repo, "heartbeat")
        )
        if can_heartbeat:
            logger.info(
                "Account heartbeat started username=%s id=%s lease_id=%s interval_s=%s ttl_s=%s",
                account.get("username"),
                account.get("id"),
                lease_id,
                heartbeat_every_s,
                ttl_s,
            )
            heartbeat_task = asyncio.create_task(
                self._lease_heartbeat_loop(
                    lease_id=lease_id,
                    account=account,
                    interval_s=heartbeat_every_s,
                    ttl_s=ttl_s,
                    stop_event=heartbeat_stop,
                )
            )

        try:
            await self._search_worker(
                worker_id=worker_id,
                account=account,
                queue=queue,
                stats=stats,
                stats_lock=stats_lock,
                tweets_out=tweets_out,
                seen_tweet_ids=seen_tweet_ids,
                query_hash=query_hash,
                checkpoint_enabled=checkpoint_enabled,
                global_limit=global_limit,
                stop_event=stop_event,
            )
        finally:
            cancelled = False
            if heartbeat_task is not None:
                heartbeat_stop.set()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    cancelled = True
                except Exception:
                    pass
                logger.info(
                    "Account heartbeat stopped username=%s id=%s lease_id=%s",
                    account.get("username"),
                    account.get("id"),
                    lease_id,
                )
            if cancelled:
                raise asyncio.CancelledError

    async def _lease_heartbeat_loop(
        self,
        *,
        lease_id: str,
        account: dict[str, Any],
        interval_s: float,
        ttl_s: int,
        stop_event: asyncio.Event,
    ) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_s)
            except asyncio.TimeoutError:
                pass
            if stop_event.is_set():
                break

            try:
                renewed = await _maybe_await(self.accounts_repo.heartbeat(lease_id, extend_by_s=ttl_s))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(
                    "Account heartbeat failed username=%s id=%s lease_id=%s detail=%s",
                    account.get("username"),
                    account.get("id"),
                    lease_id,
                    str(exc),
                )
                continue

            if not renewed:
                logger.warning(
                    "Account heartbeat failed username=%s id=%s lease_id=%s detail=lease_not_found",
                    account.get("username"),
                    account.get("id"),
                    lease_id,
                )
                break

    async def _emergency_release_leases(
        self,
        *,
        leased_accounts: dict[str, dict[str, Any]],
        handed_off_lease_ids: set[str],
    ) -> None:
        if self.accounts_repo is None or not hasattr(self.accounts_repo, "release"):
            return

        orphaned = []
        for lease_id, account in leased_accounts.items():
            if lease_id in handed_off_lease_ids:
                continue
            orphaned.append((lease_id, account))

        if not orphaned:
            return

        logger.warning("Emergency lease release path engaged count=%s", len(orphaned))
        for lease_id, account in orphaned:
            try:
                released = await _maybe_await(self.accounts_repo.release(lease_id, fields_to_set={}))
            except Exception as exc:
                logger.warning(
                    "Emergency lease release failed username=%s id=%s lease_id=%s detail=%s",
                    account.get("username"),
                    account.get("id"),
                    lease_id,
                    str(exc),
                )
                continue

            if released:
                logger.info(
                    "Emergency lease released username=%s id=%s lease_id=%s",
                    account.get("username"),
                    account.get("id"),
                    lease_id,
                )
            else:
                logger.warning(
                    "Emergency lease release failed username=%s id=%s lease_id=%s detail=lease_not_found",
                    account.get("username"),
                    account.get("id"),
                    lease_id,
                )

    async def _search_worker(
        self,
        *,
        worker_id: str,
        account: dict[str, Any],
        queue: InMemoryTaskQueue,
        stats: RunStats,
        stats_lock: asyncio.Lock,
        tweets_out: list[Any],
        seen_tweet_ids: set[str],
        query_hash: Optional[str] = None,
        checkpoint_enabled: bool = False,
        global_limit: Optional[int] = None,
        stop_event: Optional[asyncio.Event] = None,
    ) -> None:
        account_status = 1
        last_headers: Optional[dict[str, Any]] = None
        lease_id = account.get("lease_id")
        account_session = None
        session_meta: dict[str, Any] = {}

        requests_per_min = int(_config_value(self.config, "account_requests_per_min", 30))
        min_delay_s = float(_config_value(self.config, "account_min_delay_s", 0.0))
        api_page_size = max(1, min(int(_config_value(self.config, "api_page_size", 20)), 100))
        limiter = TokenBucketLimiter(requests_per_min=requests_per_min, min_delay_s=min_delay_s)

        retry_base_s = max(0, int(_config_value(self.config, "task_retry_base_s", 1)))
        retry_max_s = max(retry_base_s, int(_config_value(self.config, "task_retry_max_s", 30)))
        max_task_attempts = max(1, int(_config_value(self.config, "max_task_attempts", 3)))
        max_fallback_attempts = max(1, int(_config_value(self.config, "max_fallback_attempts", 3)))
        max_account_switches = max(0, int(_config_value(self.config, "max_account_switches", 2)))

        try:
            if self.account_session_builder is not None:
                try:
                    session_build_out = await _maybe_await(self.account_session_builder.build(account))
                    if isinstance(session_build_out, tuple) and len(session_build_out) >= 1:
                        account_session = session_build_out[0]
                        if len(session_build_out) > 1 and isinstance(session_build_out[1], dict):
                            session_meta = dict(session_build_out[1])
                    else:
                        account_session = session_build_out
                except AccountSessionBuildError as exc:
                    account_status = int(exc.status_code)
                    logger.warning(
                        "Account session build classified username=%s id=%s lease_id=%s category=%s code=%s reason=%s status_code=%s",
                        account.get("username"),
                        account.get("id"),
                        lease_id,
                        exc.category,
                        exc.code,
                        exc.reason,
                        exc.status_code,
                    )
                    return
                except Exception as exc:
                    account_status = 599
                    logger.warning(
                        "Account session build classified username=%s id=%s lease_id=%s category=%s code=%s reason=%s status_code=%s",
                        account.get("username"),
                        account.get("id"),
                        lease_id,
                        "transient",
                        "session_build_unexpected_error",
                        exc.__class__.__name__,
                        account_status,
                    )
                    return
                logger.info(
                    "Account session ready username=%s id=%s lease_id=%s cookie_count=%s session_mode=%s",
                    account.get("username"),
                    account.get("id"),
                    lease_id,
                    session_meta.get("cookie_count", "n/a"),
                    session_meta.get("session_mode", "unknown"),
                )

            while True:
                task = await queue.lease(worker_id)
                if task is None:
                    break

                if global_limit is not None:
                    async with stats_lock:
                        limit_reached_before_request = len(tweets_out) >= global_limit
                    if limit_reached_before_request:
                        if stop_event is not None:
                            stop_event.set()
                        break

                task_query = task.get("query") or {}
                request_payload = dict(task_query.get("raw") or {})
                request_payload["since"] = task_query.get("since")
                request_payload["until"] = task_query.get("until")
                request_payload["_page_size"] = api_page_size
                request_payload["_leased_account"] = {
                    "id": account.get("id"),
                    "username": account.get("username"),
                    "lease_id": lease_id,
                }
                if account_session is not None:
                    request_payload["_account_session"] = account_session
                if task_query.get("cursor"):
                    request_payload["cursor"] = task_query["cursor"]

                await limiter.acquire()

                try:
                    response = await _maybe_await(self.search_engine.search_tweets(request_payload))
                except Exception:
                    response = {
                        "result": SearchResult(),
                        "cursor": task_query.get("cursor"),
                        "status_code": 599,
                        "headers": {},
                    }

                status_code = int((response or {}).get("status_code") or 200)
                last_headers = (response or {}).get("headers") or last_headers
                next_cursor = (response or {}).get("cursor")

                tweets = self._extract_tweets(response)
                tweets_count = len(tweets)

                if lease_id and hasattr(self.accounts_repo, "record_usage"):
                    await _maybe_await(self.accounts_repo.record_usage(lease_id, pages=1, tweets=tweets_count))

                if status_code == 200:
                    limit_reached = False
                    unique_added = 0
                    async with stats_lock:
                        for tweet in tweets:
                            tweet_id = self._tweet_id(tweet)
                            if tweet_id and tweet_id in seen_tweet_ids:
                                continue
                            if tweet_id:
                                seen_tweet_ids.add(tweet_id)
                            tweets_out.append(tweet)
                            unique_added += 1
                        if global_limit is not None and len(tweets_out) >= global_limit:
                            limit_reached = True
                    if limit_reached and stop_event is not None:
                        stop_event.set()

                    if (
                        checkpoint_enabled
                        and query_hash
                        and self.resume_repo is not None
                        and hasattr(self.resume_repo, "save_checkpoint")
                    ):
                        task_since = task_query.get("since")
                        task_until = task_query.get("until")
                        if isinstance(task_since, str) and isinstance(task_until, str):
                            try:
                                await _maybe_await(
                                    self.resume_repo.save_checkpoint(
                                        query_hash,
                                        next_cursor,
                                        task_since,
                                        task_until,
                                    )
                                )
                            except Exception:
                                pass

                    should_continue_with_cursor = bool((response or {}).get("continue_with_cursor")) and bool(next_cursor)
                    continuation_task = None
                    if should_continue_with_cursor and not limit_reached:
                        continuation_task = self._build_continuation_task(task, next_cursor=str(next_cursor))
                    if continuation_task is not None:
                        await queue.enqueue([continuation_task])
                        account_status = 1
                        continue

                    await queue.ack(task, stats={"pages": 1, "tweets": unique_added})
                    async with stats_lock:
                        stats.tasks_done += 1
                    account_status = 1
                    if limit_reached:
                        break
                    continue

                account_status = status_code
                attempt = int(task.get("attempt", 0))
                fallback_attempts = int(task.get("fallback_attempts", 0))
                account_switches = int(task.get("account_switches", 0))

                if status_code in _AUTH_ERROR_CODES:
                    repaired = False
                    try:
                        repaired = await self._attempt_account_repair(account, status_code=status_code)
                    except Exception:
                        repaired = False
                    if repaired:
                        # Keep the account usable after repair; the current worker will still exit to
                        # allow the task retry flow to rebuild a session.
                        account_status = 1

                can_retry = attempt < max_task_attempts and fallback_attempts < max_fallback_attempts
                retry_reason = "transient_or_rate_limit"
                retry_delay = retry_base_s
                fallback_inc = 1
                account_switch_inc = 0

                if status_code in _AUTH_ERROR_CODES:
                    retry_reason = "account_auth_error"
                    account_switch_inc = 1
                    can_retry = can_retry and account_switches < max_account_switches
                elif _is_transient_status(status_code):
                    retry_delay = min(retry_max_s, retry_base_s * (2 ** min(attempt, 6)))
                else:
                    retry_reason = "fatal_error"
                    can_retry = False

                if can_retry:
                    await queue.retry(
                        task,
                        delay_s=retry_delay,
                        reason=retry_reason,
                        cursor=next_cursor,
                        last_error_code=status_code,
                        fallback_inc=fallback_inc,
                        account_switch_inc=account_switch_inc,
                    )
                    async with stats_lock:
                        stats.retries += 1
                else:
                    fail_reason = "retry_limit_exceeded" if retry_reason != "fatal_error" else "fatal_error"
                    await queue.fail(task, reason=fail_reason, last_error_code=status_code)
                    async with stats_lock:
                        stats.tasks_failed += 1

                # Non-success exits this account worker to allow cooldown/account-switch flow.
                break
        finally:
            if lease_id and hasattr(self.accounts_repo, "release"):
                status_value, available_til, cooldown_reason = compute_cooldown(
                    account_status,
                    last_headers,
                    self.config,
                )
                release_fields = {
                    "status": status_value,
                    "available_til": available_til,
                    "cooldown_reason": cooldown_reason,
                    "last_error_code": None if account_status == 1 else account_status,
                }
                logger.info(
                    "Account cooldown decision username=%s id=%s lease_id=%s status_code=%s next_status=%s reason=%s",
                    account.get("username"),
                    account.get("id"),
                    lease_id,
                    account_status,
                    status_value,
                    cooldown_reason,
                )
                released = await _maybe_await(
                    self.accounts_repo.release(
                        lease_id,
                        fields_to_set=release_fields,
                    )
                )
                logger.info(
                    "Account release outcome username=%s id=%s lease_id=%s released=%s",
                    account.get("username"),
                    account.get("id"),
                    lease_id,
                    bool(released),
                )
            if account_session is not None:
                await self._close_account_session(account_session)

    @staticmethod
    def _coerce_search_request(search_request: Any) -> SearchRequest:
        if isinstance(search_request, SearchRequest):
            return search_request
        if isinstance(search_request, dict):
            return SearchRequest.model_validate(search_request)
        return SearchRequest.model_validate(search_request)

    @staticmethod
    def _query_hash(payload: dict[str, Any]) -> str:
        raw = json.dumps(payload or {}, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize_timestamp(value: Optional[str], *, end_of_day: bool) -> Optional[str]:
        if not value:
            return None
        if isinstance(value, str):
            value = value.strip()
        try:
            parsed = datetime.strptime(value, _TS_FMT)
            return parsed.strftime(_TS_FMT)
        except Exception:
            pass
        try:
            parsed = datetime.strptime(value, _DATE_FMT)
            if end_of_day:
                parsed = parsed.replace(hour=23, minute=59, second=59)
            return parsed.strftime(_TS_FMT)
        except Exception:
            return value

    def _normalize_bounds(self, since: str, until: Optional[str]) -> tuple[str, str]:
        normalized_since = self._normalize_timestamp(since, end_of_day=False)
        normalized_until = self._normalize_timestamp(until, end_of_day=True)
        if normalized_since is None:
            raise ValueError("`since` is required for run_search")
        if normalized_until is None:
            normalized_until = datetime.utcnow().strftime(_TS_FMT)
        return normalized_since, normalized_until

    @staticmethod
    def _extract_tweets(response: Optional[dict[str, Any]]) -> list[Any]:
        if not isinstance(response, dict):
            return []
        result = response.get("result")
        if isinstance(result, SearchResult):
            return list(result.tweets or [])
        if isinstance(result, dict):
            tweets = result.get("tweets")
            if isinstance(tweets, list):
                return list(tweets)
        tweets = response.get("tweets")
        if isinstance(tweets, list):
            return list(tweets)
        return []

    @staticmethod
    def _tweet_id(tweet: Any) -> Optional[str]:
        if tweet is None:
            return None
        if isinstance(tweet, dict):
            value = tweet.get("tweet_id") or tweet.get("id")
            return str(value) if value else None
        value = getattr(tweet, "tweet_id", None)
        return str(value) if value else None

    @staticmethod
    def _final_status(
        stats: RunStats,
        worker_results: list[Any],
        failure: Optional[BaseException],
        *,
        limit_reached: bool = False,
    ) -> str:
        if failure is not None:
            return "failed"
        if any(isinstance(item, BaseException) for item in worker_results):
            return "failed"
        if limit_reached:
            return "completed"
        unresolved = max(0, stats.tasks_total - stats.tasks_done - stats.tasks_failed)
        if unresolved > 0:
            return "failed"
        return "completed"

    @staticmethod
    def _normalize_global_limit(limit_value: Any) -> Optional[int]:
        if limit_value is None:
            return None
        try:
            parsed = int(limit_value)
        except Exception:
            return None
        if parsed <= 0:
            return None
        return parsed

    @staticmethod
    def _is_limit_reached(global_limit: Optional[int], tweets_count: int) -> bool:
        return bool(global_limit is not None and tweets_count >= global_limit)

    @staticmethod
    def _build_continuation_task(task: dict[str, Any], next_cursor: str) -> Optional[dict[str, Any]]:
        query = task.get("query") or {}
        if not isinstance(query, dict):
            return None
        current_cursor = query.get("cursor")
        normalized_next_cursor = str(next_cursor).strip()
        if not normalized_next_cursor:
            return None
        if current_cursor is not None and str(current_cursor) == normalized_next_cursor:
            return None

        cursor_history = task.get("cursor_history") or []
        seen_cursors = {str(item) for item in cursor_history if item is not None}
        if current_cursor is not None:
            seen_cursors.add(str(current_cursor))
        if normalized_next_cursor in seen_cursors:
            return None

        continuation = dict(task)
        next_query = dict(query)
        next_query["cursor"] = normalized_next_cursor
        continuation["query"] = next_query
        continuation["cursor_history"] = list(seen_cursors)
        continuation.pop("lease_id", None)
        continuation.pop("lease_worker_id", None)
        return continuation

    async def _close_account_session(self, session: Any) -> None:
        if self.account_session_builder is not None and hasattr(self.account_session_builder, "close"):
            try:
                await _maybe_await(self.account_session_builder.close(session))
                return
            except Exception:
                pass

        close_fn = getattr(session, "close", None)
        if close_fn is None:
            return
        try:
            if inspect.iscoroutinefunction(close_fn):
                await close_fn()
                return
            maybe_awaitable = close_fn()
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable
        except Exception:
            pass
