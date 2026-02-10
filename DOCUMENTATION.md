# Scweet v4 Documentation

Scweet v4 preserves the familiar v3 surface (`Scweet(...)`, `scrape/ascrape`, output filenames, resume flags) while moving tweet search scraping to an **API-only** core and introducing **DB-first account provisioning** (SQLite).

## What’s In v4 (and What Isn’t)

Supported:

- Tweet search scraping (GraphQL SearchTimeline), API-only.
- Multiple provisioning sources: `.env`, `accounts.txt`, `cookies.json`, Netscape `cookies.txt`, direct `cookies=` payload.
- Local SQLite state: accounts leasing/cooldowns, resume checkpoints, run stats, manifest cache.
- Optional internal cookie bootstrap with `nodriver` (credentials -> cookies). No scraping via browser.

Not implemented (v4.x):

- Profile scraping and follower/following scraping are **stubbed** (methods exist for signature compatibility, but engines return `501 Not implemented`).
- API Login/provisioning using creds
- API profile timeline scraping
- Richer scraping query input 

## Installation

```bash
pip install Scweet
```

Notes:

- Python >= 3.9
- API HTTP stack uses `curl_cffi` (sync or async sessions depending on config).
- `nodriver` is only needed if you want credentials-based cookie bootstrap.

## Quickstart

The simplest “I already have cookies” flow:

```python
from Scweet import Scweet

scweet = Scweet.from_sources(
    db_path="scweet_state.db",
    cookies={"auth_token": "...", "ct0": "..."}, # ct0 is optional here.
)

tweets = scweet.scrape(
    since="2026-02-01",
    until="2026-02-07",
    words=["bitcoin"],
    limit=200,
    resume=True,
    save_dir="outputs",
    custom_csv_name="bitcoin.csv",
)

print(len(tweets))  # list[dict] of raw GraphQL tweet objects
```

## Notebook Usage (Async)

In notebooks/Jupyter, you almost always have an active event loop. Use `await ascrape(...)` instead of `scrape(...)`.

```python
from Scweet import Scweet

scweet = Scweet.from_sources(
    db_path="scweet_state.db",
    cookies_file="cookies.json",
    provision_on_init=True,
)

tweets = await scweet.ascrape(
    since="2026-02-01",
    until="2026-02-07",
    words=["bitcoin"],
    limit=50,
    resume=True,
    save_dir="outputs",
    custom_csv_name="nb_bitcoin.csv",
)
```

## Configuration

There are three ways to configure Scweet v4:

1. `Scweet.from_sources(...)` (convenience)
2. `ScweetConfig.from_sources(...)` (recommended for typed discoverability)
3. Pass a full config dict/model to `Scweet(config=...)` for advanced tuning

### Recommended: `ScweetConfig.from_sources(...)`

```python
from Scweet import Scweet, ScweetConfig

cfg = ScweetConfig.from_sources(
    db_path="scweet_state.db",
    accounts_file="accounts.txt",
    cookies_file="cookies.json",    # or cookies.txt (Netscape)
    # env_path=".env",                # works only for 1 account
    bootstrap_strategy="auto",      # auto|token_only|nodriver_only|none
    resume_mode="hybrid_safe",      # legacy_csv|db_cursor|hybrid_safe
    output_format="both",           # csv|json|both|none
    strict=False,
    proxy={"host": "127.0.0.1", "port": 8080},
    api_http_impersonate="chrome124",
    overrides={
        "operations": {"account_lease_ttl_s": 600},
        "output": {"dedupe_on_resume_by_tweet_id": True},
    },
)

scweet = Scweet(config=cfg)
```

### Advanced: `overrides={...}`

All “power knobs” live in nested config sections. `overrides` is a deep merge patch.

Common advanced fields:

- `operations.account_lease_ttl_s`
- `operations.account_requests_per_min`
- `operations.api_page_size`
- `pool.n_splits`, `pool.concurrency`
- `output.dedupe_on_resume_by_tweet_id`
- `manifest.manifest_url`, `manifest.update_on_init`, `manifest.ttl_s`

### Full Configuration Reference (`ScweetConfig`)

`ScweetConfig` is the full v4 configuration model (Pydantic) and is the source of truth for all runtime behavior.

You can provide configuration as:

- A `ScweetConfig` instance (recommended for IDE discoverability).
- A `dict` (same shape as below).

To print the current defaults as JSON:

```python
from Scweet import ScweetConfig
import json

print(json.dumps(ScweetConfig().model_dump(mode="json"), indent=2))
```

Note on defaults:

- `ScweetConfig()` contains baseline defaults for all fields.
- `ScweetConfig.from_sources(...)` applies v4-friendly defaults (notably `engine.kind="api"` since v4 tweet search scraping is API-only).

#### `engine`

Controls API HTTP behavior and keeps legacy compatibility fields.

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `engine.kind` | `"api" \| "browser" \| "auto"` | `"browser"` | Legacy/compat field. v4 tweet search scraping is API-only, so you should treat this as `"api"`. |
| `engine.api_http_mode` | `"auto" \| "sync" \| "async"` | `"auto"` | How HTTP calls are executed under the hood. `auto` prefers async sessions when available and falls back to sync. Use `ascrape()` in async environments; use `scrape()` in sync scripts. |
| `engine.api_http_impersonate` | `str \| None` | `None` | `curl_cffi` impersonation string (example: `"chrome124"`). Affects API sessions and transaction-id bootstrap. If unset, `curl_cffi` defaults are used (or `SCWEET_HTTP_IMPERSONATE`). |

#### `storage`

SQLite state DB configuration.

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `storage.db_path` | `str` | `"scweet_state.db"` | SQLite path for Scweet state (accounts, leases, resume, manifest cache). |
| `storage.enable_wal` | `bool` | `True` | Enable WAL mode (recommended) for better concurrency/perf on SQLite. |
| `storage.busy_timeout_ms` | `int` | `5000` | SQLite busy timeout in milliseconds. |

#### `accounts`

Account provisioning sources and bootstrap policy.

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `accounts.accounts_file` | `str \| None` | `None` | Path to `accounts.txt` (colon-separated) provisioning source. |
| `accounts.cookies_file` | `str \| None` | `None` | Path to `cookies.json` or Netscape `cookies.txt`. |
| `accounts.cookies_path` | `str \| None` | `None` | Legacy alias for a cookies path (kept for backward compatibility). Prefer `cookies_file`. |
| `accounts.env_path` | `str \| None` | `None` | Path to a dotenv-style `.env` (legacy single-account provisioning). |
| `accounts.cookies` | `Any` | `None` | The legacy `cookies=` payload. Accepted forms include cookie dict/list, Cookie header string, auth_token string, JSON string, or a file path string. See the cookies section. |
| `accounts.provision_on_init` | `bool` | `True` | If `True`, `Scweet(...)` will import any provided sources into the DB during initialization. |
| `accounts.bootstrap_strategy` | `"auto" \| "token_only" \| "nodriver_only" \| "none"` | `"auto"` | Controls whether Scweet may bootstrap missing auth material (auth_token -> cookies, and/or credentials -> cookies via nodriver). |

#### `pool`

Work splitting and concurrency.

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `pool.n_splits` | `int` | `5` | Split the date window into N intervals (tasks). More splits can increase parallelism but also increases overhead. |
| `pool.concurrency` | `int` | `5` | Max concurrent workers. Effective concurrency is limited by the number of eligible accounts in the DB. |

#### `runtime`

Runtime behavior and nodriver (credentials bootstrap) controls.

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `runtime.proxy` | `str \| dict \| None` | `None` | Default proxy used for API HTTP and nodriver bootstrap. Can be a URL (`"http://user:pass@host:port"`) or a dict (`{"host": "...", "port": 8080, "username": "...", "password": "..."}`), or a requests-style proxies dict. Per-account proxy overrides can be stored in the DB. |
| `runtime.user_agent` | `str \| None` | `None` | User-Agent override for nodriver bootstrap only. |
| `runtime.api_user_agent` | `str \| None` | `None` | User-Agent override for API HTTP requests. By default, Scweet does **not** set a UA for `curl_cffi` sessions (to avoid impersonation fingerprint mismatches). |
| `runtime.headless` | `bool` | `True` | nodriver option: headless mode for bootstrap/login. |
| `runtime.scroll_ratio` | `int` | `30` | Legacy field (browser-scraping era). Currently unused in v4 API-only scraping. |
| `runtime.code_callback` | `callable \| None` | `None` | Optional callback used by nodriver bootstrap to request user-provided login codes (email/2FA). |
| `runtime.strict` | `bool` | `False` | If `True`, some failures become exceptions (for example: manifest refresh when `update_on_init=True`, or "no usable accounts" instead of returning empty outputs). |

#### `operations`

Account leasing, rate limiting, retries, and cooldown policy.

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `operations.account_lease_ttl_s` | `int` | `120` | How long a leased account stays reserved before expiring (crash safety). |
| `operations.account_lease_heartbeat_s` | `float` | `30.0` | How often workers extend the lease while running. Set `0` to disable heartbeats. |
| `operations.account_daily_requests_limit` | `int` | `5000` | Per-account daily cap (UTC) on *requests/pages*; accounts above this cap become ineligible for leasing until reset. |
| `operations.account_daily_tweets_limit` | `int` | `50000` | Per-account daily cap (UTC) on *tweets returned*; accounts above this cap become ineligible for leasing until reset. |
| `operations.cooldown_default_s` | `float` | `120.0` | Cooldown used for rate limits when no reset header is available. |
| `operations.transient_cooldown_s` | `float` | `120.0` | Cooldown used for transient/network/5xx failures. |
| `operations.auth_cooldown_s` | `float` | `2592000.0` | Cooldown used for auth failures (401/403/404). Default is 30 days. |
| `operations.cooldown_jitter_s` | `float` | `10.0` | Adds random jitter to cooldowns to avoid synchronized retries. |
| `operations.account_requests_per_min` | `int` | `30` | Per-account request rate limit (token bucket). |
| `operations.account_min_delay_s` | `float` | `0.0` | Minimum delay between requests (per account worker). |
| `operations.api_page_size` | `int` | `20` | GraphQL page size (`count`). Larger values reduce requests but can increase per-request payload. Max 100. |
| `operations.task_retry_base_s` | `int` | `1` | Base delay (seconds) used for task retries. |
| `operations.task_retry_max_s` | `int` | `30` | Max delay (seconds) for exponential backoff on transient errors. |
| `operations.max_task_attempts` | `int` | `3` | Max retries per task before failing. |
| `operations.max_fallback_attempts` | `int` | `3` | Max fallback retries per task before failing (used for continuation/edge cases). |
| `operations.max_account_switches` | `int` | `2` | Max times a task can switch accounts after auth errors before failing. |
| `operations.scheduler_min_interval_s` | `int` | `300` | Minimum interval size used when splitting `[since, until]` into `pool.n_splits` tasks. Limits how many splits are allowed. |

#### `resume`

Resume policy for `resume=True`.

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `resume.mode` | `"legacy_csv" \| "db_cursor" \| "hybrid_safe"` | `"hybrid_safe"` | How Scweet decides where to continue when resuming (CSV timestamp, DB cursor checkpoint, or hybrid). |

#### `output`

File outputs (return value is always `list[dict]`).

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `output.save_dir` | `str` | `"outputs"` | Default directory for output files (can be overridden per call via `save_dir=`). |
| `output.format` | `"csv" \| "json" \| "both" \| "none"` | `"csv"` | Which files Scweet writes: CSV only, JSON only, both, or none. |
| `output.dedupe_on_resume_by_tweet_id` | `bool` | `False` | If `True` and `resume=True`, Scweet avoids appending duplicates (by tweet id) to CSV and JSON outputs. |

#### `manifest`

GraphQL request manifest controls (query ids + features).

| Key | Type | Default | Description |
| --- | --- | --- | --- |
| `manifest.manifest_url` | `str \| None` | `None` | Remote manifest URL (your hosted `scweet_manifest.json`). If unset, Scweet uses the packaged manifest (with a built-in fallback). |
| `manifest.ttl_s` | `int` | `3600` | Cache TTL (seconds) for the remote manifest (stored in SQLite). |
| `manifest.update_on_init` | `bool` | `False` | If `True`, Scweet will attempt a best-effort remote refresh during init (raises if `runtime.strict=True`). |

## Account Provisioning (DB-First)

Scweet imports account sources into SQLite. Scraping workers lease accounts from the DB.

Provisioning sources:

- `env_path=".env"`: legacy single-account provisioning
- `accounts_file="accounts.txt"`: multiple accounts, credentials and/or tokens
- `cookies_file="cookies.json"` or Netscape `cookies.txt`
- `cookies=...` payload: dict/list/header/raw token/path string/JSON string

### Provision on init vs manual provisioning

If `accounts.provision_on_init=True` (default), Scweet imports accounts during `Scweet(...)` init when you provide any sources.

If you want a two-step flow:

```python
from Scweet import Scweet

scweet = Scweet.from_sources(db_path="scweet_state.db", provision_on_init=False)
print(scweet.provision_accounts(accounts_file="accounts.txt"))
```

### Bootstrap strategy (`accounts.bootstrap_strategy`)

Controls how Scweet can create missing auth material:

- `auto` (default): allow auth_token bootstrap and credentials (nodriver) bootstrap
- `token_only`: allow auth_token bootstrap only
- `nodriver_only`: allow credentials bootstrap only # not recommended. API login coming soon. 
- `none`: do not bootstrap; accounts missing auth are imported but marked unusable

Credentials bootstrap requires `nodriver` and a record containing a login identifier + password (`email` or `username` + `password`).

## Scraping API

### `scrape(...)` and `ascrape(...)`

- `scrape(...)` is sync (good for normal scripts)
- `ascrape(...)` is async (required in notebooks/async apps)

Important parameters:

- `since`, `until`: date bounds (YYYY-MM-DD); v4 normalizes internally.
- `words`: list of keywords (OR query) or `"a//b"` string (legacy split).
- `from_account`, `to_account`, `mention_account`, `hashtag`, `lang`
- `display_type`: `"Top"` or `"Latest"` (legacy value `"Recent"` is treated as `"Latest"`).
- `limit`: best-effort per-run cap. Due to concurrency/page size, you may overshoot slightly.
- `resume`: append to existing outputs + attempt continuation using resume mode policy.
- More scraping params coming soon.

Accepted-but-ignored (v3 compatibility):

- `filter_replies`, `proximity`, `geocode`, `minreplies`, `minlikes`, `minretweets`

These parameters remain in the public signature for backward compatibility, but are not currently applied to the v4 API search query.

### How many tweets will I get?

`limit` is a per-run target, not “total across runs”. If you run the same query multiple times with `resume=True`, outputs will append unless you use dedupe (below).

## Output (Return + Files)

Return value:

- `scrape/ascrape` returns `list[dict]` of **raw GraphQL tweet objects** (`tweet_results.result`).

File outputs are controlled by `config.output.format`:

- `csv` (default): curated CSV schema with important fields
- `json`: raw tweet objects saved as JSON array
- `both`: write CSV + JSON
- `none`: don’t write files

### Dedupe on resume (CSV and JSON)

To avoid writing duplicates across runs when appending:

```python
Scweet(config={"output": {"dedupe_on_resume_by_tweet_id": True}})
```

When enabled and `resume=True`, Scweet reads existing tweet ids from the current output files and skips any new tweet whose id already exists.

Limitations:

- It prevents *new* duplicates while appending; it does not retroactively clean old files.
- JSON dedupe loads the whole existing JSON array to build the id set (can be slow for huge files).

## Resume Modes

`config.resume.mode` controls how `resume=True` chooses where to start:

- `legacy_csv`: v3 behavior (override `since` based on max CSV timestamp)
- `db_cursor`: use DB checkpoint (`since` + cursor)
- `hybrid_safe`: prefer DB checkpoint, fallback to CSV timestamp

Compatibility rule:

- If you import the legacy facade (`from Scweet.scweet import Scweet`), resume is forced to `legacy_csv`.

## Logging

Scweet uses the standard Python `logging` module and installs no handlers.

Notebook-friendly setup:

```python
import logging, sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s:%(lineno)d | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
```

Common messages:

- `Import account reuse ...`: DB already had usable auth for that token/username.
- `Import account creds bootstrap ...`: account needs nodriver login bootstrap.
- `No usable accounts available ...`: scraping can’t lease an eligible account (set `runtime.strict=True` to raise).

## Local DB Maintenance (ScweetDB)

Scweet stores state in SQLite. You can inspect and maintain it via `ScweetDB`:

```python
from Scweet import ScweetDB

db = ScweetDB("scweet_state.db")
print(db.accounts_summary())
print(db.list_accounts(limit=10, eligible_only=True, include_cookies=True))
print(db.clear_leases(expired_only=True))
print(db.reset_account_cooldowns(clear_leases=True, include_unusable=True))
print(db.collapse_duplicates_by_auth_token(dry_run=True))
```

Secrets are redacted by default (fingerprints + cookie keys). Use `reveal_secrets=True` only when necessary.

## Proxy, User-Agent, HTTP Mode, Impersonation

### Proxy

Set `runtime.proxy` as:

- `{"host": "...", "port": 8080, "username": "...", "password": "..."}` (dict)
- `"http://user:pass@host:port"` (string)
- `{"http": "...", "https": "..."}` (requests/curl-style dict)

This proxy is used for:

- API calls (curl_cffi sessions)
- Transaction-id bootstrap (if enabled)
- Token bootstrap (best-effort)
- nodriver login bootstrap

### User-Agent policy

- `runtime.user_agent`: used by **nodriver** only
- `runtime.api_user_agent`: overrides API HTTP User-Agent (by default, curl_cffi uses its own UA consistent with impersonation)

### curl_cffi impersonation

Control via `engine.api_http_impersonate` (e.g. `"chrome124"`).

### API HTTP mode

`engine.api_http_mode` controls how sessions are created:

- `auto` (default): prefer async if available
- `async`: force async
- `sync`: force sync

## Manifest (Query IDs + Features)

Twitter’s web GraphQL layer changes frequently. Scweet externalizes the most common drift points into a small manifest:

- GraphQL `query_id` for SearchTimeline
- endpoint template
- `features` dict passed to GraphQL

Defaults:

- Local packaged manifest: `Scweet/v4/default_manifest.json` (plus a built-in fallback)

Override via URL:

```python
from Scweet import Scweet

scweet = Scweet.from_sources(
    db_path="scweet_state.db",
    cookies_file="cookies.json",
    manifest_url="https://gist.githubusercontent.com/<user>/<gist>/raw/scweet_manifest.json",
    update_manifest=True,  # force refresh at init (best-effort unless strict)
)
```

Caching:

- Remote manifests are cached in SQLite (`manifest_cache`) for `manifest.ttl_s` seconds.

Important limitation:

- The manifest does not protect against *all* future breaking changes (auth flows, variable schema, response shape).

## Exceptions and Strict Mode

Key exceptions:

- `Scweet.v4.exceptions.AccountPoolExhausted`: no eligible account could be leased.

Strict mode:

- `runtime.strict=True` turns some “best effort” behavior into exceptions (recommended for production workflows where silent empty output is not acceptable).

## Future Work (Planned)

- Implement profile/follows APIs (API-only) to replace legacy browser behavior.
- Improve resume semantics for “total tweets across runs” and stronger cross-run dedupe.
- Expand manifest coverage (variable schema, optional toggles) where possible.
- Add first-class docs website (recommendation: MkDocs Material).
