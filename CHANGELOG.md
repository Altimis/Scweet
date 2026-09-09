# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Changed

- The daily caps per account rose: `daily_requests_limit` from 30 to 300, `daily_tweets_limit` from 600 to 6,000. The window limiter still bounds the burst rate to X's measured allowance (50 requests per 15 minutes).
- `api_http_impersonate` now defaults to `"chrome"`, which follows the newest Chrome fingerprint that the installed `curl_cffi` supports. Before, the engine pinned `chrome120` (a December 2023 browser), and an old TLS fingerprint next to current cookies is a mismatch that anti-bot systems weigh.
- `min_delay_s` now defaults to `1.0`: a floor between two requests of one account, so a burst does not arrive at wire speed. X counts the window total, so the floor costs little. Set `0` to remove it.
- The followers/following paths now hold their own window budget, `relationship_window_request_limit` (default 45). X allows 50 requests per window at the graph endpoint and restricts an account there more easily than at a search, so the budget keeps a margin of 5 instead of spending the full search budget.
- `search()` sorts by `"Latest"` by default. `"Top"` is a ranked selection: a measured 20,000-tweet Top order returned about 1,900 unique tweets because the ranked pages repeat. `"Latest"` is chronological and fills a volume order. Pass `display_type="Top"` for the old behavior. Note: a resume checkpoint keys on the full query including `display_type`, so a resume started under the old default does not match a run under the new default.

### Fixed

- **A search works again.** Every search returned HTTP 404 from every account, and the library could not repair itself. Both bootstrap paths read `https://x.com`, which answers a short shell page: it holds no `main.js` reference and no `"ondemand.s"` marker. So the manifest scrape found no bundle and kept a stale query ID, and the transaction-ID bootstrap built no `x-client-transaction-id` header. X answers 404 when that header is absent. Both paths now read `https://x.com/home`, and the six bundled query IDs are refreshed.
- A proxy URL that carries a `{session}` placeholder works on every path. The proxy check on lease, the transaction-ID bootstrap, and the cookie bootstrap from an `auth_token` each sent the literal text `{session}` as the proxy user name, and a provider answers HTTP 407 for that name. Only the account session builder replaced it.
- A locked account is no longer read as a successful empty page. X locks an account behind a human challenge and answers HTTP 200 with code 326 in the body. The engine now maps that answer to a `locked` status, rests the account for `locked_cooldown_s` (default 1 hour), and logs the unlock page (`https://x.com/account/access`). Before, the locked account stayed in rotation and silently returned nothing.

## [5.4.0] - 2026-09-07

### Added

- A proxy URL can now contain a `{session}` placeholder, for example `http://user,session-{session}:pass@proxy.example.com:8000`. Each account session replaces it with a unique token, so each account keeps its own exit IP on a rotating proxy. Without it, every account shares one exit IP, and when that exit IP dies, every retry reaches the same dead exit and the run loses data. With it, a session that is built again after a transport failure gets a new token and a new exit IP, so a retry recovers. A proxy without the placeholder works unchanged.

### Changed

- Rate limiting now paces to X's real window (about 50 requests per account per 15 minutes) instead of a fixed delay between requests. A short run bursts its window budget and finishes far faster, and a long run no longer exceeds the window and triggers `429`s that get accounts blocked. New config: `window_request_limit` (50) and `rate_limit_window_s` (900). `min_delay_s` now defaults to `0` (an optional floor); `requests_per_min` is deprecated.

### Fixed

- An account now hands off a margin above its rate-limit window, so a large run meets far fewer `429`s. X returns `x-rate-limit-remaining` on each page, and the count can lag, so X sometimes answers `429` one request before the header reaches zero. A `429` loses the page and forces a retry. The run now stops an account when the header falls to `rate_limit_min_remaining` (2 by default), rests it until its window resets (from `x-rate-limit-reset`), and continues its cursor on a fresh account. A measured live 20,000-tweet order lost about 10% of the data to `429`s that the margin prevents. Set `rate_limit_min_remaining=0` for the old behaviour, which hands off only when the window is fully spent.
- A large `Latest` search over a wide time range now returns far more of the data. A cursor chain of X stops at a depth limit while tweets remain in the range, and the run used to end there and report success. A measured live order of 20,000 tweets over 3 months returned about 21% before and about 90% after. The run now continues the range from the time of the oldest tweet it saw, which re-queries only the older, unfetched part. The run also splits the range into at least one interval per account, so every account does work and no account uses up its request budget on one dense interval. A `Top` search is ranked by engagement, not by time, and the top tweets of a range and of each half are mostly the same tweets, so the run does not continue a `Top` interval; use the `Latest` sort for a large volume. New config: `max_interval_depth` (100) caps the continuation as a safety backstop; the floor `scheduler_min_interval_s` and the result limit are the real bounds. Set `max_interval_depth=0` to turn the continuation off.
- `max_empty_pages` now defaults to `3` instead of `1`. X sends an empty page in the middle of a chain while results remain, so a value of `1` ended the search at the first gap and returned a small part of the data while reporting success. A fixture where empty pages fall singly between data pages collected 2 of 6 tweets at `1` and all 6 at `3`. Set it back to `1` for the old behaviour.
- An account is no longer blocked for 30 days by a routine message from X. A `401` or `403` from a page of tweets is not proof that an account is dead — X sends it for a tweet one account cannot read, while the credentials still work. The worker now confirms with a self-lookup of the account's own handle before the long block. An unconfirmed error gives a short cooldown, so a healthy account returns in minutes instead of a month. Set `pool_wait_max_s` and the cooldown fields in `ScweetConfig` to tune the behaviour.
- A run no longer fails at once when every account is on a cooldown. It waits up to `pool_wait_max_s` (120s by default) for a cooldown to expire and retries, because a cooldown expires. Set `pool_wait_max_s=0` to keep the old immediate failure.
- Account repair no longer reports success when the write fails. `_attempt_account_repair` returned `True` and logged "repair succeeded" even when the database write raised, so an operator believed the pool held a repaired account that was not there. It now returns `False` and logs a warning. A failed account release also logs a warning instead of passing silently, because a failed release drops the account from the pool with no record.

## [5.3.1] - 2026-05-19

### Fixed

- Transaction-id bootstrap failure — Twitter changed the webpack manifest format, breaking the upstream `get_ondemand_file_url` regex (`XClientTransaction` 1.0.2). Replaced with positional string extraction that survives manifest reshuffles.

---

## [5.3.0] - 2026-04-14

### Added

- **`manifest_scrape_on_init=` constructor shorthand** — pass `manifest_scrape_on_init=True` directly to `Scweet()` without needing `ScweetConfig`. Overrides the config value (same pattern as `proxy=`).
- **`--manifest-scrape-on-init` CLI flag** — scrape fresh GraphQL query IDs from X's `main.js` bundle on startup from the command line.
- **`save_name=` parameter** on `search`, `get_profile_tweets`, `get_followers`, `get_following`, and `get_user_info` — set a custom base filename for saved output (without extension).

### Changed

- Documentation now marks `ct0` as optional in cookies examples — Scweet bootstraps it automatically from `auth_token`.
- Manifest scrape docs updated to reflect the new top-level constructor arg and CLI flag.

---

## [5.2.0] - 2026-04-03

### Added

- **`proxy=` constructor shorthand** — pass a proxy URL directly to `Scweet(proxy="http://host:port")` without needing `ScweetConfig`. Overrides any proxy set in config.

### Fixed

- Python 3.9 compatibility — replaced `dict[str, Any] | str` union syntax with `Union[dict[str, Any], str]` in `ScweetConfig`. Pydantic evaluates field annotations at runtime, so the `|` syntax (PEP 604, Python 3.10+) caused a `TypeError` on 3.9.

---

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
