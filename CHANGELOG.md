# Changelog

All notable changes to this project are documented in this file.

## [4.0.0] - Unreleased

### Added

- New v4 internal architecture under `Scweet/Scweet/v4/`.
- Async runner orchestration with in-memory task queue.
- SQLite-backed state for account lifecycle, runs, resume checkpoints, and manifest cache.
- API-first scraping core (GraphQL) with async runner orchestration.
- Phase 1 provisioning scaffolding and config knobs for DB-first account provisioning.
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

### Known limitations

- Profile/follow endpoints may be stubbed or incomplete while v4 internals are being migrated.
- X/Twitter behavior and anti-bot controls can still affect reliability depending on account quality and request patterns.

### Removed

- `requests` dependency/fallbacks for API HTTP. v4 API scraping requires `curl_cffi`.
