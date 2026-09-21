# Changelog

> The reference of each version: **[altimis.github.io/Scweet](https://altimis.github.io/Scweet/)**

All notable changes to this project are documented in this file.

## [5.8.0] - 2026-09-15

This release removes the silent failures that a user could meet, makes the first run obvious, and adds the newest versions of Python. Every change is additive: no method, no field and no default of 5.7.x changes.

### Fixed

- **A run no longer fails silently when the request signature cannot build.** X answers HTTP 404 for a GraphQL request without the `x-client-transaction-id` header, and that 404 describes the request, not the account. The build of that header needs a live page of X; a transient network failure of that page left the header absent, and the run then rested the accounts one by one until it ended with no clear cause. Now the build retries with a backoff, a 404 rebuilds the header and retries the request on the same account before any cooldown, and a request that still cannot carry the header logs the reason.
- **A wrong or expired `auth_token` now reports at once.** Before, the constructor gave no warning and the first call failed with a message about cooldowns. The provisioning now counts the usable accounts, and the constructor warns when none is usable and names the likely cause.
- **A `cookies_file` accepts every shape that an inline `cookies=` accepts**, including a file exported by a browser cookie extension. The two paths now share one loader, so the same data gives the same accounts.
- **`get_tweet_info`, `get_trending` and `get_user_info(user_ids=...)` raise a clear error on a refusal.** A missing or deleted item still gives no row and no error, but a transport failure or a non-200 status no longer returns a silent empty list.

### Added

- **Python 3.13 and 3.14 are supported and tested.** The test suite runs on Python 3.9 through 3.14.
- **The package ships `py.typed`.** A type checker of a project that uses Scweet now reads the type hints of the library.
- New `ScweetConfig` fields for the request signature: `transaction_init_attempts` (3), `transaction_init_backoff_s` (1.5), and `request_404_retries` (1). A `TransactionIdProvider.refresh()` method rebuilds the header on demand.

### Changed

- The README quickstart and the documentation teach the same first path: one `auth_token`, one call, one result. The quickstart code block runs as written, with no placeholder proxy. A test pins the two documents to the same first path.

## [5.7.0] - 2026-09-14

The read surface grows from 6 operations to 13, and the query-id refresh now covers every one of them. Every change is additive.

### Added

- **`get_tweet_info(tweet_ids)`** — full tweet records for ids you already hold, up to 50 ids in one request. A deleted id gives no row and no error.
- **`get_tweet_replies(tweet_id, limit=...)`** — the replies under one tweet, as full tweet records, without the focal tweet itself.
- **`get_reposters(tweet_id, limit=...)`** — the accounts that reposted one tweet, as user records.
- **`get_user_info(user_ids=[...])`** — profile lookup by numeric id, up to 100 ids in one request; combines with lookup by username. When X refuses the id endpoint for a connection (it answers HTTP 403 there at times), the call raises an error that names the refusal and the username alternative, instead of returning an empty list.
- **`search_users(query, limit=...)`** — the "People" tab of a search, as user records.
- **`get_trending()`** — the trends of the explore page: the name, the context line with the post count, and the raw item.
- **`get_profile_media(users, limit=...)`** — only the tweets of a profile that carry an image or a video.
- **`get_profile_tweets(..., include_replies=True)`** — the timeline with the replies of the profile included.
- **`refresh_manifest()`** and the CLI command **`scweet refresh-manifest`** — read fresh GraphQL query ids from the live bundles of X at any moment, and report each id that rotated. A stale id answers 404 for every request, so call this when requests start to fail.
- Every new method has an async twin and a CLI subcommand: `tweet-info`, `tweet-replies`, `reposters`, `search-users`, `trending`, `profile-media`, `profile-tweets --include-replies`, `user-info --ids`.

### Changed

- **The query-id scrape now reaches the operations that `main.js` does not carry.** Some operations live in lazy chunk files. The scrape reads the chunk maps that the page of X embeds, sweeps the likely chunks first, and stops at the find — measured: the missing id was found within 9 small fetches. Before, an id outside `main.js` could never heal.
- The bundled default ids were refreshed from the live bundle on 2026-09-13, and each new endpoint ships with its measured request allowance.

## [5.6.0] - 2026-09-13

Every change below is additive. A script written against 5.5.x reads the same values from the same fields.

### Fixed

- **A profile reported 0 followers, 0 following and 0 tweets.** X stopped sending the flat `legacy` object of a user and moved the counts into `relationship_counts`, `tweet_counts` and `action_counts`. The parser read only the old place, so `get_user_info`, `get_followers`, `get_following` and `get_verified_followers` returned a zero for every count. Captured 2026-09-13: one profile with 241,659,598 followers reported 0. The parser now reads the old place first and the new nodes after it, so an older answer of X keeps working. A real zero stays a zero.
- A profile record now carries its banner image again, and the links inside the bio, for the same reason.

### Added

- **`get_verified_followers()` / `aget_verified_followers()` and the CLI command `verified-followers`.** The engine already supported the endpoint of X for the verified followers of a profile, and no public method reached it.
- **A tweet record carries the fields that X already sends:** `views`, `quotes`, `bookmarks`, `lang`, `hashtags`, `mentions`, `urls`, `in_reply_to_tweet_id`, `in_reply_to_user`, `is_quote` and `is_retweet`. No extra request: the data was in the `raw` payload of every row.
- **`quoted_tweet` and `retweeted_tweet`** hold the embedded tweet as a full tweet record, one level deep. `embedded_text` keeps its old value, which is the truncated text that X sends, so it can be shorter than the `text` of the nested record.
- **`media.video_links`** holds the highest-bitrate MP4 of each video. An `m3u8` playlist is a stream index and not a file to save, so it is left out.
- A user record carries `identity_verified`, `pinned_tweet_ids` and `description_urls`.

### Changed

- A count that X does not send reads `None` instead of `0`, so a caller can tell "unknown" from "zero". The counts `likes`, `retweets` and `comments` keep their old default of `0`.

## [5.5.1] - 2026-09-13

### Fixed

- `beautifulsoup4` is now a declared dependency. Two modules import `bs4`, and the package arrived only through a transitive dependency, so one dependency-resolver change could break a fresh install.
- The license badge in the README opens the tracked license file. The old link answered 404.
- The FAQ names the release of the last live verification instead of a fixed month.

### Changed

- The test dependencies are declared in `requirements-dev.txt`. Before, a contributor who installed the package and ran `pytest` saw 5 async tests fail, because `pytest-asyncio` was installed only inside CI. `pip install -e . -r requirements-dev.txt` now installs everything the suite needs.
- The repository no longer tracks IDE settings.

## [5.5.0] - 2026-09-09

A search works again. Released 5.4.0 returned HTTP 404 for every search, from every account, because X
changed the page that the library reads to bootstrap itself. This release repairs that, and it raises the
defaults that made a first run smaller and slower than the accounts allow. Every change below is verified
with a live run against real accounts.

### Fixed

- **A search works again. Upgrade from 5.4.0 and 5.3: in those versions every search returned HTTP 404 from every account, and the library could not repair itself.** Both bootstrap paths read `https://x.com`, which answers a short shell page: it holds no `main.js` reference and no `"ondemand.s"` marker. So the manifest scrape found no bundle and kept a stale query ID, and the transaction-ID bootstrap built no `x-client-transaction-id` header. X answers 404 when that header is absent. Both paths now read `https://x.com/home`, and the six bundled query IDs are refreshed. The failure looks like a dead account, and it is not: a 404 from every account describes the request, not the credentials.
- A proxy URL that carries a `{session}` placeholder works on every path. The proxy check on lease, the transaction-ID bootstrap, and the cookie bootstrap from an `auth_token` each sent the literal text `{session}` as the proxy user name, and a provider answers HTTP 407 for that name. Only the account session builder replaced it.
- A locked account is no longer read as a successful empty page. X locks an account behind a human challenge and answers HTTP 200 with code 326 in the body. The engine now maps that answer to a `locked` status, rests the account for `locked_cooldown_s` (default 1 hour), and logs the unlock page (`https://x.com/account/access`). Before, the locked account stayed in rotation and silently returned nothing.

### Changed

- The daily caps per account rose: `daily_requests_limit` from 30 to 300, `daily_tweets_limit` from 600 to 6,000. The window limiter still bounds the burst rate to X's measured allowance (50 requests per 15 minutes).
- `api_http_impersonate` now defaults to `"chrome"`, which follows the newest Chrome fingerprint that the installed `curl_cffi` supports. Before, the engine pinned `chrome120` (a December 2023 browser), and an old TLS fingerprint next to current cookies is a mismatch that anti-bot systems weigh.
- `min_delay_s` now defaults to `1.0`: a floor between two requests of one account, so a burst does not arrive at wire speed. X counts the window total, so the floor costs little. Set `0` to remove it.
- The followers/following paths now hold their own window budget, `relationship_window_request_limit` (default 45). X allows 50 requests per window at the graph endpoint and restricts an account there more easily than at a search, so the budget keeps a margin of 5 instead of spending the full search budget.
- `search()` sorts by `"Latest"` by default. `"Top"` is a ranked selection: a measured 20,000-tweet Top order returned about 1,900 unique tweets because the ranked pages repeat. `"Latest"` is chronological and fills a volume order. Pass `display_type="Top"` for the old behavior. Note: a resume checkpoint keys on the full query including `display_type`, so a resume started under the old default does not match a run under the new default.

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
