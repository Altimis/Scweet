# Changelog

All notable changes to this project are documented in this file.

## [5.1.0] - 2026-03-25

### Added

- **Command-line interface** — `scweet` command installed with the package. Subcommands: `search`, `profile-tweets`, `followers`, `following`, `user-info`. Full filter, auth, and output options. Use `--pretty` to print to stdout or `--save` to write files.
- **`embedded_text`** field — populated for quote tweets (quoted tweet text) and retweets (full retweet text), extracted from the GraphQL response.
- **`RateLimitError` / `AuthError`** — targeted exception subclasses of `RunFailed`, raised automatically based on dominant HTTP error codes (429 → `RateLimitError`, 401/403 → `AuthError`). Both exported from the top-level package.
- **Canonical CSV column order** — `TWEET_COLUMN_ORDER` / `USER_COLUMN_ORDER` constants ensure consistent, human-readable column ordering. User and media fields are flattened to `user_screen_name`, `user_name`, `image_links` in CSV; Python/JSON output preserves nested structure.
- Progress logging — human-readable start message with query/dates/limit; per-batch "Collected N / limit" updates; internal noise demoted to DEBUG.
- Output schema tables, method docstrings, troubleshooting guide, and full error hierarchy in `DOCUMENTATION.md`.

### Fixed

- `strict` removed from `ScweetConfig` — errors always raise exceptions (was silently swallowed by default).
- `--tweet-type` CLI choices corrected to `originals-only`, `replies-only`, `retweets-only`, `exclude-replies`, `exclude-retweets`.
- `--hashtag` renamed to `--hashtags-any`, `--exclude` renamed to `--exclude-words` to match library parameter names.
- Default search window extended from 7 to 30 days when `since` is omitted.
- `configure_logging` removed from public exports (still used internally by the CLI).
- `AccountPoolExhausted` message now includes account counts (total, unusable, cooling down).
- `db_path` constructor argument now always takes precedence over `ScweetConfig(db_path=...)`.
- Fixed `query=''` in runner logs (was reading wrong field from `SearchRequest`).

---

## [5.0.0] - 2025

> **Why the rewrite?** The migration from browser automation to direct GraphQL API calls began in v3. Twitter/X progressively restricted anonymous access from 2023 onwards, making the browser-based approach increasingly brittle. v5 completed the transition by removing the browser dependency entirely. Scweet now calls X's internal GraphQL API directly — the same one the web app uses — authenticated with browser cookies. The result is faster, leaner (no headless browser), and maintainable as X's API evolves.

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
