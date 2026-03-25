# Changelog

All notable changes to this project are documented in this file.

## [5.1.0] - 2026-03-25

### Added

- **Command-line interface** — `scweet` command installed automatically with the package. All endpoints available as subcommands: `search`, `profile-tweets`, `followers`, `following`, `user-info`.
- Full filter support in the CLI: all search filters (`--from`, `--hashtag`, `--min-likes`, `--has-images`, etc.), output options (`--save`, `--save-format`, `--save-dir`, `--save-name`, `--pretty`), and global auth/config flags (`--auth-token`, `--cookies-file`, `--env-file`, `--proxy`, `--strict`, `--concurrency`).
- `python -m Scweet` entry point via `__main__.py`.
- 78 unit tests covering the CLI parser, command handlers, output formatting, and `main()` exit codes (`tests/test_cli.py`).

---

## [5.0.0] - 2025

### Added

- Simplified public API: `Scweet`, `ScweetConfig`, `ScweetDB`, `configure_logging`.
- Flat `ScweetConfig` (~35 fields, all with sensible defaults). No nested config sections.
- Structured search filters: `all_words`, `any_words`, `exact_phrases`, `from_users`, `to_users`, `mentioning_users`, `hashtags_any`, `has_images`, `has_videos`, `min_likes`, `min_replies`, `min_retweets`, geo filters, and more.
- Profile tweets: `get_profile_tweets()` / `aget_profile_tweets()`.
- Followers/following: `get_followers()` / `aget_followers()`, `get_following()` / `aget_following()` with optional `raw_json` toggle.
- User info: `get_user_info()` / `aget_user_info()`.
- Output saving: `save=True` + `save_format="csv|json|both"` on all methods.
- Resume interrupted searches: `resume=True` (SQLite cursor checkpoints).
- Auto-updating GraphQL query IDs: `ScweetConfig(manifest_scrape_on_init=True)`.
- Account management via `ScweetDB`: `accounts_summary`, `list_accounts`, `repair_account`, `reset_account_cooldowns`, `clear_leases`, `reset_daily_counters`, and more.
- SQLite-backed account pool with lease/heartbeat lifecycle, daily caps, and cooldown tracking.
- `XClientTransaction` header generation (required by X since late 2024).
- `configure_logging()` helper with `simple` and `detailed` profiles.

### Breaking (vs v4)

- Removed legacy import path `from Scweet.scweet import Scweet`.
- Removed legacy constructor args `n_splits`, `concurrency` (on constructor — use `ScweetConfig(concurrency=...)`).
- Removed legacy query input keys on `scrape`/`ascrape` (`words`, `from_account`, etc.).
- Removed `ResumeMode`, `BootstrapStrategy`, `ApiHttpMode` from public exports.
- Removed nested config sections (`pool.concurrency` -> `concurrency`, `operations.daily_requests_limit` -> `daily_requests_limit`, etc.).
- Config is now a flat `ScweetConfig` Pydantic model (no `from_sources` class method).
- Constructor is now `Scweet(cookies_file=, auth_token=, cookies=, db_path=, config=)`.
- `scrape()`/`ascrape()` replaced by `search()`/`asearch()`.
- Resume mode is `db_cursor` only (CSV-based resume removed).

### Removed

- `nodriver` dependency and browser-based login.
- `requests` HTTP fallback (v5 requires `curl_cffi`).
- Legacy CSV resume mode.
- `DOCUMENTATION.md` (was stale v4 docs; recreated for v5).
