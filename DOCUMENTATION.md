# Scweet v4 Documentation

Scweet v4 preserves the familiar v3 surface (`Scweet(...)`, `scrape/ascrape`, output filenames, resume flags) while moving scraping to an **API-only** core and introducing **DB-first account provisioning** (SQLite). For new code, prefer `search(...)` / `asearch(...)` for structured query inputs, `profile_tweets(...)` / `aprofile_tweets(...)` for profile timeline scraping, and follows methods (`get_followers(...)`, `get_following(...)`, etc.) for social graph scraping.

## What’s In v4 (and What Isn’t)

Supported:

- Tweet search scraping (GraphQL SearchTimeline), API-only.
- Profile timeline scraping (GraphQL UserTweets), API-only.
- Followers/following scraping (GraphQL Followers/Following/BlueVerifiedFollowers), API-only.
- Multiple provisioning sources: `.env`, `accounts.txt`, `cookies.json`, Netscape `cookies.txt`, direct `cookies=` payload.
- Local SQLite state: accounts leasing/cooldowns, resume checkpoints, run stats, manifest cache.
- Optional internal cookie bootstrap with `nodriver` (credentials -> cookies). No scraping via browser.

Not implemented (v4.x):

- Browserless API login/provisioning with credentials (nodriver bootstrap is available)

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

tweets = scweet.search(
    since="2026-02-01",
    until="2026-02-07",
    search_query="bitcoin",
    has_images=True,
    limit=200,
    resume=True,
    save_dir="outputs",
    custom_csv_name="bitcoin.csv",
    save=True,
    save_format="csv",
)

print(len(tweets))  # list[dict] of raw GraphQL tweet objects
```

## Notebook Usage (Async)

In notebooks/Jupyter, you almost always have an active event loop. Use `await asearch(...)` (or `await ascrape(...)` for legacy code) instead of `scrape(...)`.

```python
from Scweet import Scweet

scweet = Scweet.from_sources(
    db_path="scweet_state.db",
    cookies_file="cookies.json",
    provision_on_init=True,
)

tweets = await scweet.asearch(
    since="2026-02-01",
    until="2026-02-07",
    search_query="bitcoin",
    any_words=["btc", "bitcoin"],
    min_likes=20,
    limit=50,
    resume=True,
    # in-memory only by default (`save=False`)
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
| `engine.api_http_mode` | `"auto" \| "sync" \| "async"` | `"auto"` | How HTTP calls are executed under the hood. `auto` prefers async sessions when available and falls back to sync. Use `asearch()` in async environments; use `search()` in sync scripts. |
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
| `runtime.strict` | `bool` | `False` | If `True`, Scweet raises instead of silently returning empty output when a run cannot make progress (for example: no leasable accounts, or repeated network/proxy failures). |

#### `operations`

Account leasing, rate limiting, retries, and cooldown policy.

| Key | Type | Default                      | Description |
| --- | --- |------------------------------| --- |
| `operations.account_lease_ttl_s` | `int` | `120`                        | How long a leased account stays reserved before expiring (crash safety). |
| `operations.account_lease_heartbeat_s` | `float` | `30.0`                       | How often workers extend the lease while running. Set `0` to disable heartbeats. |
| `operations.proxy_check_on_lease` | `bool` | `True`                       | Optional proxy smoke-check when building/leasing account sessions (helps fail fast on bad proxies). |
| `operations.proxy_check_url` | `str` | `"https://x.com/robots.txt"` | URL used by the optional proxy smoke-check. Default is `https://x.com/robots.txt`. |
| `operations.proxy_check_timeout_s` | `float` | `10.0`                       | Timeout for the optional proxy smoke-check. |
| `operations.account_daily_requests_limit` | `int` | `30`                         | Per-account daily cap (UTC) on *requests/pages*; accounts above this cap become ineligible for leasing until reset. |
| `operations.account_daily_tweets_limit` | `int` | `600`                        | Per-account daily cap (UTC) on *tweets returned*; accounts above this cap become ineligible for leasing until reset. |
| `operations.cooldown_default_s` | `float` | `120.0`                      | Cooldown used for rate limits when no reset header is available. |
| `operations.transient_cooldown_s` | `float` | `120.0`                      | Cooldown used for transient/network/5xx failures. |
| `operations.auth_cooldown_s` | `float` | `2592000.0`                  | Cooldown used for auth failures (401/403). Default is 30 days. |
| `operations.cooldown_jitter_s` | `float` | `10.0`                       | Adds random jitter to cooldowns to avoid synchronized retries. |
| `operations.account_requests_per_min` | `int` | `30`                         | Per-account request rate limit (token bucket). |
| `operations.account_min_delay_s` | `float` | `2.0`                        | Minimum delay between requests (per account worker). |
| `operations.api_page_size` | `int` | `20`                         | GraphQL page size (`count`). Larger values reduce requests but can increase per-request payload. Max 100. |
| `operations.max_empty_pages` | `int` | `1`                          | Stop pagination after this many consecutive pages return `0` results. |
| `operations.task_retry_base_s` | `int` | `1`                          | Base delay (seconds) used for task retries. |
| `operations.task_retry_max_s` | `int` | `30`                         | Max delay (seconds) for exponential backoff on transient errors. |
| `operations.max_task_attempts` | `int` | `3`                          | Max retries per task before failing. |
| `operations.max_fallback_attempts` | `int` | `3`                          | Max fallback retries per task before failing (used for continuation/edge cases). |
| `operations.max_account_switches` | `int` | `2`                          | Max times a task can switch accounts after auth errors before failing. |
| `operations.scheduler_min_interval_s` | `int` | `300`                        | Minimum interval size used when splitting `[since, until]` into `pool.n_splits` tasks. Limits how many splits are allowed. |

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
| `output.format` | `"csv" \| "json" \| "both" \| "none"` | `"csv"` | Fallback file format when a method call uses `save=True` and does not pass `save_format`. |
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
- `nodriver_only`: allow credentials bootstrap only (uses optional nodriver bootstrap)
- `none`: do not bootstrap; accounts missing auth are imported but marked unusable

Credentials bootstrap requires `nodriver` and a record containing a login identifier + password (`email` or `username` + `password`).

## Search API

### `search(...)` and `asearch(...)` (recommended)

- `search(...)` is sync (good for normal scripts)
- `asearch(...)` is async (required in notebooks/async apps)

Important parameters:

- `since`, `until`: date bounds (YYYY-MM-DD); v4 normalizes internally.
- `search_query`: free-form Twitter query text (operators supported).
- `all_words`, `any_words`, `exact_phrases`, `exclude_words`
- `from_users`, `to_users`, `mentioning_users`
- `hashtags_any`, `hashtags_exclude`
- `tweet_type`: `all`, `originals_only`, `replies_only`, `retweets_only`, `exclude_replies`, `exclude_retweets`
- `verified_only`, `blue_verified_only`
- `has_images`, `has_videos`, `has_links`, `has_mentions`, `has_hashtags`
- `min_likes`, `min_replies`, `min_retweets`
- `place`, `geocode`, `near`, `within`
- `lang`
- `display_type`: `"Top"` or `"Latest"` (legacy value `"Recent"` is treated as `"Latest"`).
- `limit`: best-effort per-run cap. Due to concurrency/page size, you may overshoot slightly.
- `max_empty_pages` (default `1`): stop cursor pagination after this many consecutive pages with `0` results.
- `resume`: append to existing outputs + attempt continuation using resume mode policy.
- `save`: enable file writing for this call (`False` by default).
- `save_format`: per-call output format (`csv|json|both|none`), used only when `save=True`.

### `scrape(...)` and `ascrape(...)` (compat wrappers)

- Legacy signatures are preserved for backward compatibility.
- If canonical keys are passed to `scrape(...)`, it routes to `asearch(...)`.
- Legacy keys are still accepted and normalized, with deprecation warnings.

Deprecated legacy query keys:

- `words`, `from_account`, `to_account`, `mention_account`, `hashtag`
- `minlikes`, `minreplies`, `minretweets`
- `filter_replies` (mapped to `tweet_type=exclude_replies`)
- legacy aliases like `query`, `words_and`, `words_or`, `verified`, `images`, `videos`, `links`

### How many tweets will I get?

`limit` is a per-run target, not “total across runs”. If you run the same query multiple times with `resume=True`, outputs will append unless you use dedupe (below).

## Profile Information API

Use `get_user_information(...)` / `aget_user_information(...)` to fetch profile info in batches.

Accepted input fields (explicit only):

- `usernames=[...]`
- `profile_urls=[...]` (profile handle URLs like `https://x.com/OpenAI`)

Simple usage:

```python
items = scweet.get_user_information(
    usernames=["OpenAI", "elonmusk"],
    profile_urls=["https://x.com/OpenAI"],
)
print(items)
```

Include metadata/errors:

```python
result = scweet.get_user_information(
    usernames=["OpenAI", "elonmusk"],
    profile_urls=["https://x.com/OpenAI"],
    include_meta=True,
    save_dir="outputs",
    custom_csv_name="profiles_info.csv",
    save=True,
    save_format="both",
)
print(result["items"])  # list of profile records
print(result["meta"])   # requested/resolved/failed/skipped/errors
```

Notes:

- The default return value is `list[dict]` profile records (`result["items"]` when `include_meta=True`).
- Set `include_meta=True` to get the response envelope `{items, meta, status_code}`.

## Profile Timeline API

Use `profile_tweets(...)` / `aprofile_tweets(...)` to scrape tweets directly from profile timelines (`UserTweets`).

Accepted input fields (explicit only):

- `usernames=[...]`
- `profile_urls=[...]` (profile handle URLs like `https://x.com/OpenAI`)

Main parameters:

- `limit`: global cap across all requested profiles.
- `per_profile_limit`: cap per profile target.
- `max_pages_per_profile`: hard page cap per profile (default: unlimited).
- `max_empty_pages` (default `1`): stop cursor pagination after this many consecutive pages with `0` results.
- `resume`: continue from saved per-profile cursors.
- `offline`: scrape without leasing an account (best-effort; X usually limits depth/pages for anonymous access).
- `cursor_handoff`: allow same-cursor continuation on another account for retryable failures.
- `max_account_switches`: max handoffs per profile target.
- `save_dir`, `custom_csv_name`: output path controls, same as search.
- `save`: enable file writing for this call (`False` by default).
- `save_format`: per-call output format (`csv|json|both|none`), used only when `save=True`.

Simple usage:

```python
tweets = scweet.profile_tweets(
    usernames=["OpenAI", "elonmusk"],
    profile_urls=["https://x.com/OpenAI"],
    limit=500,
    per_profile_limit=250,
    max_pages_per_profile=50,
    resume=True,
    offline=False,
    cursor_handoff=True,
    max_account_switches=2,
    save_dir="outputs",
    custom_csv_name="profiles_timeline.csv",
    save=True,
    save_format="both",
)
print(len(tweets))
```

Aliases:

- `get_profile_timeline(...)` (sync)
- `aget_profile_timeline(...)` (async)

Default config knob:

- `operations.profile_timeline_allow_anonymous` (`False` by default). When enabled, profile timeline scraping can run without leasing accounts unless overridden per call (`offline=`).

## Followers / Following API

Preferred input fields:

- `usernames=[...]`
- `profile_urls=[...]` (profile handle URLs like `https://x.com/OpenAI`)
- `user_ids=[...]` (direct numeric user ids, no username/url lookup needed)

Legacy aliases are still accepted for compatibility (`handle`, `user_id`, `profile_url`, `users`, `user_ids`, `type`; `login/stay_logged_in/sleep` are accepted and ignored).

Methods:

- Sync: `get_followers(...)`, `get_following(...)`, `get_verified_followers(...)`
- Async: `aget_followers(...)`, `aget_following(...)`, `aget_verified_followers(...)`

Main parameters:

- `limit`: global cap across all requested targets.
- `per_profile_limit`: cap per target.
- `max_pages_per_profile`: hard page cap per target (default: unlimited).
- `max_empty_pages` (default `1`): stop cursor pagination after this many consecutive pages with `0` results.
- `resume`: continue from saved per-target cursors.
- `cursor_handoff`: allow same-cursor continuation on another account for retryable failures.
- `max_account_switches`: max handoffs per target.
- `save_dir`, `custom_csv_name`: output path controls, same style as search/profile timeline.
- `save`: enable file writing for this call (`False` by default).
- `save_format`: per-call output format (`csv|json|both|none`), used only when `save=True`.
- `raw_json` (`False` by default): for follows JSON/output, choose curated rows (`False`) or raw user payload rows (`True`).
- account pacing/cooldown uses the same operations knobs as search:
  - `operations.account_requests_per_min`
  - `operations.account_min_delay_s`
  - `operations.cooldown_default_s`, `operations.transient_cooldown_s`, `operations.auth_cooldown_s`, `operations.cooldown_jitter_s`
- preemptive header handling is enabled:
  - when `x-rate-limit-remaining <= 0` on an otherwise `200` response, Scweet treats the account as rate-limited (`429` effective status)
  - cooldown uses `x-rate-limit-reset` when present
  - with `cursor_handoff=True`, the cursor can continue on another account (up to `max_account_switches`)
- follows page usage contributes `unique_results` into the same per-account daily item counter field used by search runs

Simple usage:

```python
followers = scweet.get_followers(
    usernames=["OpenAI", "elonmusk"],
    profile_urls=["https://x.com/OpenAI"],
    user_ids=["44196397"],  # optional: direct id target
    limit=500,
    per_profile_limit=250,
    max_pages_per_profile=40,
    resume=True,
    cursor_handoff=True,
    max_account_switches=2,
    save_dir="outputs",
    custom_csv_name="followers.csv",
    save=True,
    save_format="json",
    raw_json=True,  # JSON/output rows contain full Twitter user payload under `raw`
)
print(len(followers))
```

Output shape:

- Return value is `list[dict]`.
- Each row includes:
  - `type` (`followers`, `following`, `verified_followers`)
  - `target` (the requested profile this row belongs to)
  - user fields (`user_id`, `username`, counts, verification flags, and `raw`) when `raw_json=False` (default)
  - raw payload rows (`follow_key`, `type`, `target`, `raw`) when `raw_json=True`
- File writing uses per-call `save` + `save_format`:
  - `csv`: follows CSV rows
  - `json`: follows JSON rows (`raw_json=False`: curated rows, `raw_json=True`: full payload rows)
  - `both`: CSV + JSON
  - `none`: no files

## Output (Return + Files)

Return value:

- `search/asearch/scrape/ascrape/profile_tweets/aprofile_tweets/get_profile_timeline/aget_profile_timeline` return `list[dict]` of **raw GraphQL tweet objects** (`tweet_results.result`).
- `get_followers/get_following/get_verified_followers` (and async variants):
  - `raw_json=False` (default): return curated user rows with a per-row `target` field.
  - `raw_json=True`: return rows containing `{follow_key, type, target, raw}` where `raw` is the full user payload from Twitter.

File outputs are controlled per call via `save` + `save_format`:

- `csv`: curated CSV schema with important fields
- `json`: raw tweet objects saved as JSON array
- `both`: write CSV + JSON
- `none`: don’t write files

Writing happens only when `save=True`. If `save=True` and `save_format` is omitted, Scweet uses config `output.format` (if not set or `none`, it won't write).

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

Notebook-friendly setup (stdlib):

```python
import logging, sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s:%(lineno)d | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
    force=True,
)
```

Notebook-friendly setup (Scweet helper):

```python
from Scweet import configure_logging

configure_logging(profile="simple", level="INFO", force=True)

# More detail (per-request API logs + file/line):
configure_logging(profile="detailed", level="DEBUG", show_api_http=True, force=True)
```

Common messages:

- `Import account reuse ...`: DB already had usable auth for that token/username.
- `Import account creds bootstrap ...`: account needs nodriver login bootstrap.
- `No usable accounts available ...`: scraping can’t lease an eligible account (set `runtime.strict=True` to raise).
- `Profiles lease unavailable ... blocked=... sample=...`: profile lease failed; logs include blocker counts (`status`, `daily_limit`, `missing_csrf`, etc.) and sample accounts.

## Local DB Maintenance (ScweetDB)

Scweet stores state in SQLite. You can inspect and maintain it via `ScweetDB`:

```python
from Scweet import ScweetDB

db = ScweetDB("scweet_state.db")
print(db.accounts_summary())
print(db.list_accounts(limit=10, eligible_only=True, include_cookies=True))
print(db.repair_account("acct1", force_refresh=True))
print(db.clear_leases(expired_only=True))
print(db.reset_account_cooldowns(clear_leases=True, include_unusable=True))
print(db.collapse_duplicates_by_auth_token(dry_run=True))
```

Secrets are redacted by default (fingerprints + cookie keys). Use `reveal_secrets=True` only when necessary.

`repair_account(...)` is a targeted per-username recovery helper. It can:

- refresh cookies from `auth_token` (API bootstrap; no browser login fallback),
- clear lease/cooldown state,
- reset daily counters,
- optionally mark the account unusable if auth is still invalid.

## Proxy, User-Agent, HTTP Mode, Impersonation

### Proxy

Set `runtime.proxy` as:

- `{"host": "...", "port": 8080, "username": "...", "password": "..."}` (dict)
- `"http://user:pass@host:port"` (string)
- `{"http": "...", "https": "..."}` (requests/curl-style dict)

Invalid proxy formats raise a config validation error.

This proxy is used for:

- API calls (curl_cffi sessions)
- Transaction-id bootstrap (if enabled)
- Token bootstrap (best-effort)
- nodriver login bootstrap

Optional fail-fast proxy check:

- `config.operations.proxy_check_on_lease=True` will run a cheap proxy-only connectivity check (no account cookies/headers).
- `config.operations.proxy_check_url` and `config.operations.proxy_check_timeout_s` control the check.
  - Default URL is `https://x.com/robots.txt`. If you want proxy egress verification, set an IP-echo URL explicitly.

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

- GraphQL `query_id`s for operations (for example: `search_timeline`, `user_lookup_screen_name`, `profile_timeline`)
- endpoint templates per operation
- global `features` dict passed to GraphQL
- optional per-operation overrides:
  - `operation_features[operation]` merged on top of global `features`
  - `operation_field_toggles[operation]` sent as `fieldToggles`

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

- Implement browserless API-based login for account provisioning using username/password + email/2fa.
- Expand manifest coverage (variable schema, optional toggles) where possible.
