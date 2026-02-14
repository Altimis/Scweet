# Changelog

All notable changes to this project are documented in this file.

## [4.0.0] - Unreleased

### Added

- New v4 internal architecture under `Scweet/v4/`.
- Async runner orchestration with in-memory task queue.
- SQLite-backed state for account lifecycle, runs, resume checkpoints, and manifest cache.
- API-first scraping core (GraphQL) with async runner orchestration.
- DB-first account provisioning and related configuration knobs.
- Public DB/state helper: `ScweetDB` (inspect accounts, reset cooldowns/leases, collapse duplicates).
- Output resume dedupe: `output.dedupe_on_resume_by_tweet_id` (skip writing duplicates on resume for CSV and JSON).
- Per-account proxy override stored in SQLite: `accounts.proxy_json` (set via `cookies.json` / `accounts.txt` / `ScweetDB.set_account_proxy`).
- Per-account daily caps (lease eligibility):
  - `operations.account_daily_requests_limit`
  - `operations.account_daily_tweets_limit`
- Remote manifest support and best-effort refresh on init:
  - `manifest.manifest_url`
  - `manifest.update_on_init` (via `update_manifest=True`)
- Resume modes:
  - `legacy_csv`
  - `db_cursor`
  - `hybrid_safe`
- Output format controls:
  - `config.output.format` (`csv|json|both|none`)
  - per-call `save` + `save_format` controls across methods (`save=False` by default; when `save=True`, format is `csv|json|both|none`)
- Canonical structured search methods:
  - `Scweet.search(...)` (sync)
  - `Scweet.asearch(...)` (async)
- Structured query normalization/builder for SearchTimeline:
  - `search_query`, `all_words`, `any_words`, `exact_phrases`, `exclude_words`
  - `from_users`, `to_users`, `mentioning_users`
  - `hashtags_any`, `hashtags_exclude`
  - `tweet_type`, media/verification filters, min engagement filters, geo filters
- `scrape(...)` now auto-routes to canonical search when canonical query keys are provided.
- Profile information retrieval via `get_user_information(...)` / `aget_user_information(...)`:
  - accepts explicit targets (`usernames`, `profile_urls`)
  - default return is `list[dict]` profile records (`items`)
  - optional response envelope via `include_meta=True` (`{items, meta, status_code}`)
  - supports file persistence with `save_dir`, `custom_csv_name`, and `save_format`
- Follows output enhancements:
  - new per-call `raw_json` toggle on follows methods (`get_followers/get_following/get_verified_followers` and async variants)
  - `raw_json=False` (default): curated follows rows for JSON/output
  - `raw_json=True`: JSON/output rows keep full Twitter user payload under `raw` while CSV stays curated
  - improved field mapping fallbacks from modern user-result nodes (`core`, `verification`, `privacy`, `avatar`, `location`)
- Follows account-health parity with search:
  - per-account pacing limiter now applies to follows requests (`account_requests_per_min`, `account_min_delay_s`)
  - follows sessions now release with search-style cooldown fields (`status`, `available_til`, `cooldown_reason`, `last_error_code`)
  - follows usage accounting now records unique added users per page (for daily cap pressure), not always `tweets=0`
  - preemptive rate-limit handling via `x-rate-limit-remaining` + `x-rate-limit-reset` (effective status `429` on exhausted remaining)
  - long follows runs now keep lease heartbeats active (`account_lease_heartbeat_s`)
- Search preemptive rate-limit handling:
  - when `x-rate-limit-remaining <= 0` on status `200`, the account is treated as rate-limited and cooled down via existing cooldown flow
- Pagination defaults:
  - `max_pages_per_profile` now defaults to unlimited for profile timeline and follows flows
  - runs stop via user caps (`limit`, `per_profile_limit`), cursor exhaustion, or `max_empty_pages` unless an explicit `max_pages_per_profile` is provided
- Profile timeline scraping via:
  - `profile_tweets(...)` / `aprofile_tweets(...)` (primary API)
  - `get_profile_timeline(...)` / `aget_profile_timeline(...)` (aliases)
  - accepts explicit targets (`usernames`, `profile_urls`)
  - supports cursor resume, per-profile/page limits, and optional cursor handoff across accounts
  - supports optional anonymous mode (`offline=True`) for best-effort profile timeline scraping without account leasing
  - returns `list[dict]` raw tweet objects and uses the same output writing path as search APIs
- Empty-page pagination guard for all cursor-based methods:
  - new input + config knob: `max_empty_pages` (default `1`)
  - stops pagination when consecutive pages return `0` results, even if cursor continues to advance
  - adds per-page result logging for `status=200` with total and unique counts
- Streaming output persistence for paginated methods:
  - search/profile timeline/follows now persist incrementally during pagination (not only at run end)
  - profile information requests stream-save records as they resolve
- Account recovery and diagnostics:
  - `repair_account(username, ...)` for targeted per-account recovery (optional auth_token cookie refresh + state reset)
  - richer lease-failure diagnostics in logs when no account is eligible (blocked reason counts + sample rows)
- Manifest schema extension for operation-specific GraphQL flags:
  - `operation_features`
  - `operation_field_toggles` (serialized as `fieldToggles`)

### Breaking (vs v3)

- `scrape` / `ascrape` now returns a `list[dict]` of raw tweet objects from the GraphQL response (`tweet_results.result`).
- CSV output is now a curated "important fields" schema (stable header) derived from those raw GraphQL tweet objects.

### Compatibility guarantees (v4.x)

- Legacy class import path still works: `from Scweet.scweet import Scweet`.
- Preferred class import path available: `from Scweet import Scweet`.
- Legacy public method signatures preserved.
- Legacy CSV filename behavior preserved (same naming logic via `save_dir` / `custom_csv_name`).
- Legacy facade import path intentionally forces `legacy_csv` resume semantics for backward compatibility.

### Deprecated (planned removal in v5.0)

- Legacy import path `Scweet.scweet`.
- Constructor arg `n_splits` (use `config.pool.n_splits`).
- Constructor arg `concurrency` (use `config.pool.concurrency`).
- Legacy query input keys on `scrape/ascrape`:
  - `words`, `from_account`, `to_account`, `mention_account`, `hashtag`
  - `minlikes`, `minreplies`, `minretweets`
  - `filter_replies` (use `tweet_type="exclude_replies"`)

### Known limitations

- Follow endpoints are not implemented yet and currently return `501`.
- Login via API is not implemented yet. Only nodriver based login is available.
- X/Twitter behavior and anti-bot controls can still affect reliability depending on account quality and request patterns.

### Removed

- `requests` dependency/fallbacks for API HTTP. v4 API scraping requires `curl_cffi`.

### Fixed

- Ensure `Scweet/v4/default_manifest.json` is shipped in built distributions (wheel/sdist).
