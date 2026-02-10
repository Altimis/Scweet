from __future__ import annotations

"""
Scweet v4 API-only: User Guide + Smoke Script

This file is intentionally comment-heavy. It is meant to be READ as a guide,
and optionally RUN as a small smoke test.

Key points (v4):
- Tweet search scraping is API-only.
- Account provisioning is DB-first (SQLite); sources are imported into the DB.
- nodriver is used internally only for optional login/bootstrap to obtain cookies.

What this guide covers:
- All constructor parameters (legacy + v4 keyword-only)
- All supported account provisioning sources and cookies formats
- All public methods available on the `Scweet` facade
- Sync and async usage patterns

Safety:
- No secrets are included; placeholder values are used.
- Running "scrape" requires usable account auth material and network access.
"""

import argparse
import asyncio
import json
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Optional

from Scweet import Scweet


# ---------------------------------------------------------------------------
# Examples: cookie payload forms (placeholders; replace with real values)
# ---------------------------------------------------------------------------

# 1) Cookie dict (recommended "already normalized" form)
EXAMPLE_COOKIES_DICT: dict[str, str] = {
    "auth_token": "REPLACE_ME_AUTH_TOKEN",
    "ct0": "REPLACE_ME_CT0",
    # Any other cookies are accepted; name/value only are used:
    # "guest_id": "...",
}

# 2) Cookie list (common in selenium-style exports)
EXAMPLE_COOKIES_LIST: list[dict[str, str]] = [
    {"name": "auth_token", "value": "REPLACE_ME_AUTH_TOKEN"},
    {"name": "ct0", "value": "REPLACE_ME_CT0"},
]

# 3) Cookie header string (common when copying from browser devtools)
EXAMPLE_COOKIE_HEADER_STRING = "auth_token=REPLACE_ME_AUTH_TOKEN; ct0=REPLACE_ME_CT0"

# 4) Raw auth_token string (convenience)
EXAMPLE_AUTH_TOKEN_STRING = "REPLACE_ME_AUTH_TOKEN"

# 5) JSON string containing any accepted cookies payload form
EXAMPLE_COOKIES_JSON_STRING = json.dumps(EXAMPLE_COOKIES_DICT)

# 6) File path string to cookies.json or Netscape cookies.txt
EXAMPLE_COOKIES_FILE_PATH_STRING = "cookies.json"  # or "cookies.txt"


# ---------------------------------------------------------------------------
# Examples: provisioning sources (filenames are placeholders)
# ---------------------------------------------------------------------------

EXAMPLE_ACCOUNTS_TXT = "accounts.txt"  # format: username:password:email:email_password:2fa:auth_token
EXAMPLE_COOKIES_JSON = "cookies.json"  # list/object mapping forms supported (see README)
EXAMPLE_COOKIES_TXT = "cookies.txt"  # Netscape cookies.txt export supported
EXAMPLE_ENV_PATH = ".env"  # legacy single-account env (AUTH_TOKEN/CT0 or EMAIL/PASSWORD...)


# ---------------------------------------------------------------------------
# Provisioning formats (quick reference)
# ---------------------------------------------------------------------------
#
# accounts.txt (one account per line, ":" separated):
#   username:password:email:email_password:2fa:auth_token
#
# cookies.json accepted shapes:
# - list of account records:
#     [{"username": "...", "cookies": {"auth_token": "...", "ct0": "..."}}]
# - object with accounts list:
#     {"accounts": [...]}  # same record shapes as above
# - single account object:
#     {"username": "...", "cookies": {...}}
# - mapping username -> cookies/account payload:
#     {"alice": {"auth_token": "...", "ct0": "..."}, "bob": [{"name": "...", "value": "..."}]}
#
# cookies.txt (Netscape export):
# - comments and blanks ignored
# - 7 columns per cookie line:
#     domain<TAB>flag<TAB>path<TAB>secure<TAB>expiry<TAB>name<TAB>value
# - output used by Scweet is just {name: value}
#
# .env (single account):
# - Recommended keys for API auth material:
#     AUTH_TOKEN=...
#     CT0=...   (or CSRF=...)
# - Legacy credential keys (for optional nodriver bootstrap):
#     EMAIL=... EMAIL_PASSWORD=...
#     USERNAME=... PASSWORD=...
#     TWO_FA=... (or OTP_SECRET / OTP)
#
# bootstrap_strategy meanings:
# - auto: allow token bootstrap + creds bootstrap
# - token_only: allow token bootstrap only (skip nodriver creds)
# - nodriver_only: allow creds bootstrap only (skip token bootstrap)
# - none: do not bootstrap missing auth; accounts without required material are marked unusable
#


# ---------------------------------------------------------------------------
# Examples: proxy dict
# - used for nodriver bootstrap (credentials login)
# - also used for API HTTP requests (proxy is applied to per-account HTTP sessions)
# ---------------------------------------------------------------------------

EXAMPLE_PROXY: dict[str, Any] = {
    "host": "127.0.0.1",
    "port": 8080,
    # Optional proxy auth:
    # "username": "proxyuser",
    # "password": "proxypass",
}

# ---------------------------------------------------------------------------
# Examples: full config dict (all top-level sections and fields)
# ---------------------------------------------------------------------------
#
# You can pass this into Scweet(..., config=EXAMPLE_CONFIG_ALL_KNOBS).
# Unknown keys are ignored (pydantic extra handling), so you can also keep
# other app-specific settings in your config dict without breaking Scweet.
#
EXAMPLE_CONFIG_ALL_KNOBS: dict[str, Any] = {
    "engine": {
        "kind": "api",  # kind is effectively ignored for search (API-only)
        "api_http_mode": "auto",
        # curl_cffi Session fingerprint (optional):
        # - examples: "chrome124", "chrome120", "safari17_0"
        # - if unset, curl_cffi defaults (or SCWEET_HTTP_IMPERSONATE env) are used
        "api_http_impersonate": None,
    },
    "storage": {"db_path": "scweet_state.db", "enable_wal": True, "busy_timeout_ms": 5000},
    "accounts": {
        "accounts_file": "accounts.txt",
        "cookies_file": "cookies.json",  # can also be cookies.txt (Netscape)
        "cookies_path": None,  # legacy (accepted; not used for v4 API search)
        "env_path": ".env",
        "cookies": None,  # direct cookies= payload (any accepted form)
        "provision_on_init": True,
        "bootstrap_strategy": "auto",  # auto|token_only|nodriver_only|none
    },
    "pool": {"n_splits": 5, "concurrency": 5},
    "runtime": {
        "proxy": None,  # used for nodriver bootstrap + API HTTP proxying
        "user_agent": None,  # nodriver login UA
        "api_user_agent": None,  # API UA override (curl_cffi uses its own UA if unset)
        "disable_images": False,
        "headless": True,
        "scroll_ratio": 30,  # legacy (kept for signature compatibility)
        "code_callback": None,  # async callable for confirmation code flows
        "strict": False,
    },
    "operations": {
        "account_lease_ttl_s": 120,
        "account_lease_heartbeat_s": 30.0,
        "cooldown_default_s": 120.0,
        "transient_cooldown_s": 120.0,
        "auth_cooldown_s": 30 * 24 * 60 * 60,
        "cooldown_jitter_s": 10.0,
        "account_requests_per_min": 30,
        "account_min_delay_s": 0.0,
        "api_page_size": 20,
        "task_retry_base_s": 1,
        "task_retry_max_s": 30,
        "max_task_attempts": 3,
        "max_fallback_attempts": 3,
        "max_account_switches": 2,
        "scheduler_min_interval_s": 300,
        "priority": 1,
    },
    "resume": {"mode": "hybrid_safe"},  # legacy_csv|db_cursor|hybrid_safe
    "output": {"save_dir": "outputs", "format": "csv"},
    "manifest": {"manifest_url": None, "ttl_s": 3600},
}


async def example_code_callback(email: str, _email_password: str) -> str:
    """Example async code callback for confirmation-code login flows (nodriver bootstrap)."""

    return input(f"Enter the confirmation code for {email}: ").strip()


# ---------------------------------------------------------------------------
# Example: exhaustive constructor call (all args)
# ---------------------------------------------------------------------------
#
# scweet = Scweet(
#     # Legacy args (still accepted for v3 compatibility):
#     proxy=EXAMPLE_PROXY,
#     cookies=EXAMPLE_COOKIES_DICT,  # or any accepted cookies payload
#     cookies_path="cookies_dir",  # legacy (accepted; not used for v4 API search)
#     user_agent="Mozilla/5.0 ...",
#     disable_images=True,
#     env_path=".env",
#     n_splits=5,              # deprecated (prefer config.pool.n_splits)
#     concurrency=5,           # deprecated (prefer config.pool.concurrency)
#     headless=True,
#     scroll_ratio=30,         # legacy
#     mode="API",              # deprecated/compat; search is API-only regardless
#     code_callback=example_code_callback,
#     # Preferred v4 config:
#     config=EXAMPLE_CONFIG_ALL_KNOBS,  # dict or ScweetConfig model
#     # Optional convenience kwargs (accepted, but recommended to move into config):
#     # engine="api",
#     # db_path="scweet_state.db",
#     # accounts_file="accounts.txt",
#     # cookies_file="cookies.json",  # or cookies.txt (Netscape)
#     # manifest_url="https://example.com/manifest.json",
# )
#

def _maybe_existing(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    candidate = Path(path)
    return str(candidate) if candidate.exists() else None


def _env_flag(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "y", "on"}


# ---------------------------------------------------------------------------
# Constructor guide (public interface)
# ---------------------------------------------------------------------------
#
# Recommended import:
#   from Scweet import Scweet
#
# Deprecated import path (still supported in v4.x, but emits FutureWarning):
#   from Scweet.scweet import Scweet
# Notes:
# - When importing from Scweet.scweet, resume mode is forced to legacy CSV semantics.
#
# Public constructor signature (legacy + v4 keyword-only):
#
#   Scweet(
#       proxy=None,
#       cookies=None,
#       cookies_path=None,
#       user_agent=None,
#       disable_images=False,
#       env_path=None,
#       n_splits=5,
#       concurrency=5,
#       headless=True,
#       scroll_ratio=30,
#       mode="BROWSER",
#       code_callback=None,
#       *,
#       config=None,  # dict or ScweetConfig
#       # Convenience kwargs (accepted, but recommended to move into config):
#       # engine=None, db_path=None, accounts_file=None, cookies_file=None, manifest_url=None
#   )
#
# Notes on "legacy" args:
# - env_path is supported (not deprecated anymore); it's a provisioning source (.env file).
# - cookies_path is legacy/unused for v4 API-only scraping; keep it only for old scripts.
# - mode/engine are accepted for compatibility; tweet search scraping is API-only.
#
# Notes on config:
# - config can be a dict or a ScweetConfig model.
# - config dicts can include extra keys; pydantic will ignore unknown fields.
#


def build_client(
    *,
    db_path: str,
    accounts_file: Optional[str],
    cookies_file: Optional[str],
    env_path: Optional[str],
    cookies_payload: Any,
    bootstrap_strategy: str,
    provision_on_init: bool,
    strict: bool,
    resume_mode: str,
    api_http_mode: str,
    api_http_impersonate: Optional[str] = None,
) -> Scweet:
    """
    Build a client using the preferred v4 import path (from Scweet import Scweet).

    All parameters are optional; missing sources just mean fewer/zero accounts.
    """

    return Scweet.from_sources(
        db_path=db_path,
        accounts_file=accounts_file,
        cookies_file=cookies_file,
        env_path=env_path,
        cookies=cookies_payload,
        bootstrap_strategy=bootstrap_strategy,
        provision_on_init=bool(provision_on_init),
        strict=bool(strict),
        resume_mode=resume_mode,
        api_http_mode=api_http_mode,
        api_http_impersonate=api_http_impersonate,
    )


def run_provisioning_examples(scweet: Scweet, *, accounts_file: Optional[str], cookies_file: Optional[str], env_path: Optional[str], cookies_payload: Any) -> None:
    """
    Public methods related to provisioning:
    - provision_accounts(...)
    - import_accounts(...)  (alias)
    - add_account(...)
    """

    # Manual DB-first provisioning:
    result = scweet.provision_accounts(
        accounts_file=accounts_file,
        cookies_file=cookies_file,
        env_path=env_path,
        cookies=cookies_payload,
        # Optional:
        # db_path="other.db",
        # bootstrap_timeout_s=30,
        # creds_bootstrap_timeout_s=180,
    )
    print("provision_accounts:", result)

    # Alias (same behavior):
    # result2 = scweet.import_accounts(accounts_file=accounts_file, cookies_file=cookies_file, env_path=env_path)
    # print("import_accounts:", result2)

    # Upsert a single account record directly (no scraping required).
    #
    # Accepted keys are flexible; normalize_account_record derives a stable username if missing.
    # scweet.add_account(
    #     username="acct1",
    #     cookies={"auth_token": "REPLACE_ME", "ct0": "REPLACE_ME"},
    # )


def run_scrape_example(scweet: Scweet) -> None:
    """
    Public methods related to tweet search scraping:
    - scrape(...)   (sync wrapper)
    - ascrape(...)  (async)

    scrape/ascrape signature (v3-compatible):
      since, until, words, to_account, from_account, mention_account, lang, limit, display_type,
      resume, hashtag, save_dir, filter_replies, proximity, geocode, minreplies, minlikes,
      minretweets, custom_csv_name
    """

    # Example date window.
    since = (date.today() - timedelta(days=2)).strftime("%Y-%m-%d")
    until = (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")

    # Output settings (curated CSV: important fields; stable header).
    save_dir = "outputs"
    custom_csv_name = "smoke_v4_api_only.csv"

    # Words can be a list OR a string split by "//" for legacy compatibility.
    # words = "bitcoin//ethereum"
    words = ["openai"]

    # display_type must be one of: "Top", "Latest", "Image"
    tweets = scweet.scrape(
        since=since,
        until=until,
        words=words,
        # Optional filters:
        # from_account="someuser",
        # to_account="someuser",
        # mention_account="someuser",
        # hashtag="somehashtag",
        # lang="en",
        # display_type="Latest",
        # filter_replies=True,
        # proximity=False,
        # geocode="48.8584,2.2945,10km",
        # minreplies=10,
        # minlikes=10,
        # minretweets=10,
        # Limit can be int, float("inf"), or omitted.
        limit=10,
        # Resume controls both DB cursor checkpoints and legacy CSV behavior (depending on resume mode).
        resume=True,
        save_dir=save_dir,
        custom_csv_name=custom_csv_name,
    )

    print("tweets_count:", len(tweets))
    if tweets:
        first = tweets[0] if isinstance(tweets, list) else None
        if isinstance(first, dict):
            tweet_id = first.get("rest_id") or (first.get("tweet") or {}).get("rest_id") or (first.get("legacy") or {}).get("id_str")
            handle = (
                (((first.get("core") or {}).get("user_results") or {}).get("result") or {}).get("legacy") or {}
            ).get("screen_name")
            if handle is None:
                handle = (
                    (((((first.get("tweet") or {}).get("core") or {}).get("user_results") or {}).get("result") or {}).get("legacy") or {})
                ).get("screen_name")
            print("first_tweet_id:", tweet_id)
            print("first_tweet_handle:", handle)
    print("csv_path:", str(Path(save_dir) / custom_csv_name))


async def run_async_examples(scweet: Scweet) -> None:
    """
    Async usage:
    - await scweet.ascrape(...)
    - await scweet.aget_user_information(...)
    - await scweet.aget_follows(...)
    - await scweet.aclose()

    Note: close() cannot be called from inside an event loop; use await aclose().
    """

    # Minimal async scrape example:
    _ = await scweet.ascrape(
        since=(date.today() - timedelta(days=2)).strftime("%Y-%m-%d"),
        until=(date.today() - timedelta(days=1)).strftime("%Y-%m-%d"),
        words=["openai"],
        limit=5,
        save_dir="outputs",
        custom_csv_name="smoke_v4_api_only_async.csv",
        resume=True,
    )

    # Profiles/follows endpoints are stubbed (currently 501 in ApiEngine); facade returns {} / [].
    profiles = await scweet.aget_user_information(handles=["openai"], login=False)
    follows = await scweet.aget_followers(handle="openai", login=False)
    print("profiles:", profiles)
    print("followers:", follows)

    await scweet.aclose()


def run_non_scrape_methods(scweet: Scweet) -> None:
    """
    Other public helpers:
    - build_search_url(...) (legacy URL builder)
    - get_last_date_from_csv(path) (legacy CSV resume helper)
    """

    urls = scweet.build_search_url(
        since="2026-02-01",
        until="2026-02-03",
        words=["openai", "chatgpt"],
        display_type="Latest",
        lang="en",
        filter_replies=True,
        n=3,
    )
    print("example_search_urls_count:", len(urls))

    # last_ts = scweet.get_last_date_from_csv("outputs/some.csv")
    # print("last_timestamp:", last_ts)


def run_profiles_and_follows_examples(scweet: Scweet) -> None:
    """
    Public profile/follow methods (sync wrappers around async calls):
    - get_user_information(...)
    - get_follows(...)
    - get_followers(...)
    - get_following(...)
    - get_verified_followers(...)

    Note: ApiEngine returns 501 for these endpoints today, so you should expect
    empty outputs until those endpoints are implemented.
    """

    profiles = scweet.get_user_information(handles=["openai"], login=False)
    print("get_user_information:", profiles)

    follows = scweet.get_follows(handle="openai", type="following", login=False)
    print("get_follows(following):", follows)

    followers = scweet.get_followers(handle="openai", login=False)
    print("get_followers:", followers)

    following = scweet.get_following(handle="openai", login=False)
    print("get_following:", following)

    verified_followers = scweet.get_verified_followers(handle="openai", login=False)
    print("get_verified_followers:", verified_followers)


def run_maintenance_example(scweet: Scweet, *, dry_run: bool) -> None:
    """
    Opt-in maintenance API:
    - maintenance_collapse_duplicates(dry_run=True|False)

    This collapses duplicate DB rows that share the same auth_token.
    It is NEVER run automatically.
    """

    out = scweet.maintenance_collapse_duplicates(dry_run=bool(dry_run))
    print("maintenance_collapse_duplicates:", out)


def run_guide_output() -> None:
    print("Scweet v4 API-only guide script")
    print("")
    print("Read this file for full examples and comments.")
    print("")
    print("Cookie payload forms accepted by cookies= (examples; placeholders):")
    print("  dict:", EXAMPLE_COOKIES_DICT)
    print("  list:", EXAMPLE_COOKIES_LIST)
    print("  header:", EXAMPLE_COOKIE_HEADER_STRING)
    print("  auth_token:", EXAMPLE_AUTH_TOKEN_STRING)
    print("  json_string:", EXAMPLE_COOKIES_JSON_STRING)
    print("  file_path_string:", EXAMPLE_COOKIES_FILE_PATH_STRING)
    print("")
    print("Provisioning sources:")
    print("  accounts_file:", EXAMPLE_ACCOUNTS_TXT)
    print("  cookies_file:", EXAMPLE_COOKIES_JSON, "or", EXAMPLE_COOKIES_TXT)
    print("  env_path:", EXAMPLE_ENV_PATH)
    print("")
    print("Actions you can run:")
    print("  --action guide")
    print("  --action provision")
    print("  --action scrape")
    print("  --action async")
    print("  --action profiles_follows")
    print("  --action maintenance_dry_run")
    print("  --action maintenance_apply")
    print("")
    print("Tip: start with --action provision and verify eligible accounts > 0.")
    print("Tip: if you want provisioning to persist across separate runs, set --db-path to a file (default).")


def _print_effective_inputs(
    *,
    db_path: str,
    accounts_file: Optional[str],
    cookies_file: Optional[str],
    env_path: Optional[str],
    cookies_payload: Any,
    bootstrap_strategy: str,
    resume_mode: str,
    api_http_mode: str,
    api_http_impersonate: Optional[str],
    provision_on_init: bool,
) -> None:
    print("db_path:", db_path)
    print("accounts_file:", accounts_file)
    print("cookies_file:", cookies_file)
    print("env_path:", env_path)
    print("cookies_payload_type:", None if cookies_payload is None else type(cookies_payload).__name__)
    print("bootstrap_strategy:", bootstrap_strategy)
    print("resume_mode:", resume_mode)
    print("api_http_mode:", api_http_mode)
    print("api_http_impersonate:", api_http_impersonate)
    print("provision_on_init:", provision_on_init)


def main(argv: Optional[list[str]] = None) -> None:
    parser = argparse.ArgumentParser(
        prog="smoke_v4_api_only.py",
        description="Scweet v4 API-only user guide + optional smoke runner (read the file for full examples).",
    )
    parser.add_argument(
        "--action",
        choices=[
            "guide",
            "provision",
            "scrape",
            "async",
            "maintenance_dry_run",
            "maintenance_apply",
            "non_scrape_methods",
            "profiles_follows",
        ],
        default="guide",
    )
    parser.add_argument(
        "--db-path",
        default="scweet_state.db",
        help="SQLite DB path. Use ':memory:' for ephemeral runs.",
    )
    parser.add_argument("--accounts-file", default=None, help="Path to accounts.txt (optional)")
    parser.add_argument("--cookies-file", default=None, help="Path to cookies.json or cookies.txt (optional)")
    parser.add_argument("--env-path", default=None, help="Path to .env (optional)")
    parser.add_argument(
        "--cookies",
        default=None,
        help=(
            "cookies= payload (string form). If this string is an existing filepath, it is loaded as cookies file; "
            "else JSON string -> decoded; else Cookie header string -> parsed; else treated as raw auth_token."
        ),
    )
    parser.add_argument(
        "--bootstrap-strategy",
        default="auto",
        choices=["auto", "token_only", "nodriver_only", "none"],
        help="Provisioning bootstrap policy.",
    )
    parser.add_argument(
        "--provision-on-init",
        action="store_true",
        default=False,
        help="If set, provisioning will run during Scweet(...) construction when sources are provided.",
    )
    parser.add_argument("--strict", action="store_true", default=False, help="If set, no-accounts becomes an error.")
    parser.add_argument(
        "--resume-mode",
        default="hybrid_safe",
        choices=["legacy_csv", "db_cursor", "hybrid_safe"],
        help="Resume policy (preferred import path honors this).",
    )
    parser.add_argument(
        "--api-http-mode",
        default="auto",
        choices=["auto", "async", "sync"],
        help="HTTP backend selection for GraphQL calls.",
    )
    parser.add_argument(
        "--api-http-impersonate",
        default=None,
        help=(
            "curl_cffi Session impersonate string (optional). Examples: chrome124, chrome120, safari17_0. "
            "If unset, curl_cffi defaults (or SCWEET_HTTP_IMPERSONATE env) are used."
        ),
    )

    args = parser.parse_args(argv)

    if args.action == "guide":
        run_guide_output()
        return

    accounts_file = _maybe_existing(args.accounts_file)
    cookies_file = _maybe_existing(args.cookies_file)
    env_path = _maybe_existing(args.env_path)

    cookies_payload: Any = None
    if args.cookies is not None:
        cookies_payload = args.cookies

    # For convenience when running this script locally without editing args:
    # set SCWEET_SMOKE_AUTODETECT=1 to auto-detect accounts.txt/cookies.json/cookies.txt/.env if present.
    if _env_flag("SCWEET_SMOKE_AUTODETECT"):
        accounts_file = accounts_file or _maybe_existing(EXAMPLE_ACCOUNTS_TXT)
        cookies_file = cookies_file or _maybe_existing(EXAMPLE_COOKIES_JSON) or _maybe_existing(EXAMPLE_COOKIES_TXT)
        env_path = env_path or _maybe_existing(EXAMPLE_ENV_PATH)

    scweet = build_client(
        db_path=str(args.db_path),
        accounts_file=accounts_file,
        cookies_file=cookies_file,
        env_path=env_path,
        cookies_payload=cookies_payload,
        bootstrap_strategy=str(args.bootstrap_strategy),
        provision_on_init=bool(args.provision_on_init),
        strict=bool(args.strict),
        resume_mode=str(args.resume_mode),
        api_http_mode=str(args.api_http_mode),
        api_http_impersonate=args.api_http_impersonate,
    )

    _print_effective_inputs(
        db_path=str(args.db_path),
        accounts_file=accounts_file,
        cookies_file=cookies_file,
        env_path=env_path,
        cookies_payload=cookies_payload,
        bootstrap_strategy=str(args.bootstrap_strategy),
        resume_mode=str(args.resume_mode),
        api_http_mode=str(args.api_http_mode),
        api_http_impersonate=args.api_http_impersonate,
        provision_on_init=bool(args.provision_on_init),
    )

    if args.action == "provision":
        run_provisioning_examples(
            scweet,
            accounts_file=accounts_file,
            cookies_file=cookies_file,
            env_path=env_path,
            cookies_payload=cookies_payload,
        )
        return

    if args.action == "scrape":
        # Convenience: if the user provided sources (args or autodetect), provision first so the same
        # command can be used as a smoke test (especially when using ':memory:' DB).
        if accounts_file or cookies_file or env_path or cookies_payload is not None:
            run_provisioning_examples(
                scweet,
                accounts_file=accounts_file,
                cookies_file=cookies_file,
                env_path=env_path,
                cookies_payload=cookies_payload,
            )
        run_scrape_example(scweet)
        return

    if args.action == "async":
        if accounts_file or cookies_file or env_path or cookies_payload is not None:
            run_provisioning_examples(
                scweet,
                accounts_file=accounts_file,
                cookies_file=cookies_file,
                env_path=env_path,
                cookies_payload=cookies_payload,
            )
        asyncio.run(run_async_examples(scweet))
        return

    if args.action == "non_scrape_methods":
        run_non_scrape_methods(scweet)
        return

    if args.action == "profiles_follows":
        run_profiles_and_follows_examples(scweet)
        return

    if args.action == "maintenance_dry_run":
        run_maintenance_example(scweet, dry_run=True)
        return

    if args.action == "maintenance_apply":
        run_maintenance_example(scweet, dry_run=False)
        return


if __name__ == "__main__":
    main()
