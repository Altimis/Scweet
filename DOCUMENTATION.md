# Scweet v5 — Full Documentation

Scweet is an **API-only** Twitter/X scraper built on the web GraphQL endpoints. It handles account pooling, rate limiting, cooldowns, resume, and output persistence — all backed by a local SQLite database.

```bash
pip install -U Scweet
```

```python
from Scweet import Scweet, ScweetConfig, ScweetDB
```

---

## Account Setup

Scweet needs Twitter/X account cookies to make authenticated API requests.

### Getting your cookies

1. Log into Twitter/X in your browser
2. Open DevTools (F12) > Application > Cookies > `https://x.com`
3. Copy `auth_token` and `ct0` values

### Option A: cookies.json (recommended)

Create a `cookies.json` file:

```json
[
  {
    "username": "your_account",
    "cookies": { "auth_token": "...", "ct0": "..." }
  }
]
```

```python
s = Scweet(cookies_file="cookies.json")
```

For multiple accounts (enables concurrent scraping):

```json
[
  { "username": "account1", "cookies": { "auth_token": "...", "ct0": "..." } },
  { "username": "account2", "cookies": { "auth_token": "...", "ct0": "..." } }
]
```

### Option B: auth_token (quickest)

If you just have an `auth_token`, Scweet will bootstrap `ct0` automatically:

```python
s = Scweet(auth_token="YOUR_AUTH_TOKEN")
```

### Option C: inline cookies

Pass cookies directly — useful for scripts and one-off runs:

```python
# Single account
s = Scweet(cookies={"auth_token": "...", "ct0": "..."})

# Multiple accounts
s = Scweet(cookies=[
    {"auth_token": "tok1", "ct0": "ct0_1"},
    {"auth_token": "tok2", "ct0": "ct0_2"},
])
```

### How provisioning works

When you create a `Scweet` instance, it **provisions** your accounts into a local SQLite database (`scweet_state.db` by default). This means your cookies are imported, validated, and stored so Scweet can manage them — tracking rate limits, cooldowns, daily caps, and lease state across requests.

This happens automatically on init (`provision=True` by default). You provide cookies once, and Scweet handles the rest. If an account already exists in the DB (matched by username or auth_token), it's updated rather than duplicated.

### Reuse existing DB

Because accounts are persisted in SQLite, you don't need to provide cookies every time. After the first run, you can just point to the DB:

```python
s = Scweet(db_path="scweet_state.db")
```

This reuses your previously provisioned accounts with all their state (daily counters, cooldowns, etc.) intact.

You can also skip provisioning entirely if you only want to work with accounts already in the DB:

```python
s = Scweet(db_path="scweet_state.db", provision=False)
```

---

## Controlling Limits

Every method that paginates (`search`, `get_profile_tweets`, `get_followers`, `get_following`) accepts a **`limit`** parameter — the maximum number of items to collect in that call. If omitted (`None`), scraping continues until results are exhausted or account daily caps are hit.

**Always set a `limit`** to avoid burning through your account quota unexpectedly:

```python
tweets = s.search("python", limit=200)              # stop after 200 tweets
tweets = s.get_profile_tweets(["elonmusk"], limit=100)
users  = s.get_followers(["elonmusk"], limit=500)
users  = s.get_following(["OpenAI"], limit=500)
```

There are two layers of limits:

| Layer | Where | What it controls |
|-------|-------|------------------|
| **Per-call `limit`** | Method argument | Max items returned by a single call |
| **Account daily caps** | `ScweetConfig` | Max API requests / tweets per account per UTC day |

The per-call `limit` is what you should set in normal usage. The account daily caps (`daily_requests_limit`, `daily_tweets_limit`) are safety nets that protect your account from over-use across all calls in a day — see [Rate Limiting](#rate-limiting) in the config reference.

`get_user_info` does not paginate (one API call per user), so it has no `limit` parameter.

---

## Search API

### Basic search

```python
s = Scweet(cookies_file="cookies.json")

# Defaults to last 30 days if since/until omitted — always set explicit dates for reproducibility
tweets = s.search("python programming", limit=100)

# Explicit date range
tweets = s.search("python programming", since="2024-01-01", until="2024-02-01", limit=500)
print(f"Found {len(tweets)} tweets")
```

Both `since` and `until` are optional. `since` defaults to **30 days ago**, `until` defaults to today. Always set explicit dates for reproducible results.

### Structured filters

All filters are optional and merge with the query string:

```python
tweets = s.search(
    since="2024-01-01",
    from_users=["elonmusk"],
    min_likes=100,
    has_images=True,
    lang="en",
    limit=200,
)
```

Combining a query string with filters:

```python
tweets = s.search(
    "AI tools",
    since="2024-01-01",
    from_users=["OpenAI"],
    min_likes=50,
    limit=100,
)
```

#### Available filters

| Parameter | Type | Description |
|-----------|------|-------------|
| `all_words` | `list[str]` | All words must appear (AND) |
| `any_words` | `list[str]` | Any word can appear (OR) |
| `exact_phrases` | `list[str]` | Exact phrase match |
| `exclude_words` | `list[str]` | Exclude tweets with these words |
| `hashtags_any` | `list[str]` | Match any of these hashtags |
| `hashtags_exclude` | `list[str]` | Exclude these hashtags |
| `from_users` | `list[str]` | Tweets from these users |
| `to_users` | `list[str]` | Tweets to these users |
| `mentioning_users` | `list[str]` | Tweets mentioning these users |
| `tweet_type` | `str` | `all`, `originals_only`, `replies_only`, `retweets_only`, `exclude_replies`, `exclude_retweets` |
| `verified_only` | `bool` | Verified accounts only |
| `blue_verified_only` | `bool` | Blue verified only |
| `has_images` | `bool` | Must contain images |
| `has_videos` | `bool` | Must contain videos |
| `has_links` | `bool` | Must contain links |
| `has_mentions` | `bool` | Must contain mentions |
| `has_hashtags` | `bool` | Must contain hashtags |
| `min_likes` | `int` | Minimum likes |
| `min_replies` | `int` | Minimum replies |
| `min_retweets` | `int` | Minimum retweets |
| `place` | `str` | Place filter |
| `geocode` | `str` | Geocode filter (e.g., `"37.7749,-122.4194,10km"`) |
| `near` | `str` | Near location |
| `within` | `str` | Within radius (e.g., `"15mi"`) |

#### Standard parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `query` | `str` | `""` | Raw query string (Twitter search operators) |
| `since` | `str` | 30 days ago | Start date (`YYYY-MM-DD`) |
| `until` | `str` | today | End date (`YYYY-MM-DD`) |
| `lang` | `str` | `None` | Language filter (e.g., `"en"`) |
| `display_type` | `str` | `"Top"` | `"Top"` or `"Latest"` |
| `limit` | `int` | `None` | Max tweets to collect. `None` = no cap (scrapes until exhausted). **Recommended to always set.** |
| `max_empty_pages` | `int` | config value | Stop after N consecutive empty pages |
| `resume` | `bool` | `False` | Resume from last checkpoint |
| `save` | `bool` | `False` | Save results to disk |
| `save_format` | `str` | config value | `"csv"`, `"json"`, or `"both"` |

### Async variant

```python
tweets = await s.asearch("query", since="2024-01-01", limit=100)
```

---

## Profile Tweets

Fetch tweets from user timelines:

```python
tweets = s.get_profile_tweets(["elonmusk", "OpenAI"], limit=100)

# With options
tweets = s.get_profile_tweets(
    ["elonmusk"],
    limit=500,
    max_empty_pages=2,
    save=True,
    save_format="json",
)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `users` | `list[str]` | *required* | Usernames or profile URLs |
| `limit` | `int` | `None` | Max tweets to collect. `None` = no cap. **Recommended to always set.** |
| `max_empty_pages` | `int` | config value | Stop after N consecutive empty pages |
| `resume` | `bool` | `False` | Resume from last checkpoint |
| `save` | `bool` | `False` | Save results to disk |
| `save_format` | `str` | config value | `"csv"`, `"json"`, or `"both"` |

Async: `await s.aget_profile_tweets(["elonmusk"], limit=100)`

---

## Followers / Following

```python
# Followers
users = s.get_followers(["elonmusk"], limit=1000)

# Following
users = s.get_following(["OpenAI"], limit=500)
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `users` | `list[str]` | *required* | Usernames or profile URLs |
| `limit` | `int` | `None` | Max users to collect. `None` = no cap. **Recommended to always set.** |
| `max_empty_pages` | `int` | config value | Stop after N consecutive empty pages |
| `resume` | `bool` | `False` | Resume from last checkpoint |
| `raw_json` | `bool` | `False` | Include full Twitter user payload under `raw` key |
| `save` | `bool` | `False` | Save results to disk |
| `save_format` | `str` | config value | `"csv"`, `"json"`, or `"both"` |

### raw_json option

By default, follower/following records contain curated fields. With `raw_json=True`, each record includes the full Twitter user payload under a `raw` key (CSV output stays curated regardless):

```python
users = s.get_followers(["elonmusk"], limit=100, raw_json=True)
# users[0]["raw"] contains the full GraphQL user object
```

Async: `await s.aget_followers(["elonmusk"], limit=500)` / `await s.aget_following(["OpenAI"], limit=500)`

---

## User Info

Fetch profile information for one or more users:

```python
profiles = s.get_user_info(["elonmusk", "OpenAI"])
# Returns list of dicts with profile fields
```

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `users` | `list[str]` | *required* | Usernames or profile URLs |
| `save` | `bool` | `False` | Save results to disk |
| `save_format` | `str` | config value | `"csv"`, `"json"`, or `"both"` |

Async: `await s.aget_user_info(["elonmusk"])`

---

## Saving Results

By default, results are returned in-memory only (`save=False`). To persist to disk:

```python
# Save as CSV (default format)
tweets = s.search("query", since="2024-01-01", limit=200, save=True)

# Save as JSON
tweets = s.search("query", since="2024-01-01", limit=200, save=True, save_format="json")

# Save both CSV and JSON
tweets = s.search("query", since="2024-01-01", limit=200, save=True, save_format="both")
```

Output files are written to the `save_dir` directory (default: `"outputs"`). File names are based on the operation type (`search.csv`, `profile_tweets.json`, `followers.csv`, etc.).

The default format can be set globally via `ScweetConfig(save_format="json")`.

---

## Output Schemas

### Tweet record

Returned by `search()` and `get_profile_tweets()`.

| Field | Type | Description |
|-------|------|-------------|
| `tweet_id` | `str` | Tweet ID |
| `user` | `dict` | Author info: `screen_name` (handle), `name` (display name) |
| `timestamp` | `str` | Post time — Twitter date string, e.g. `"Thu Mar 20 22:25:15 +0000 2025"` |
| `text` | `str` | Full tweet text |
| `embedded_text` | `str \| None` | Quoted tweet text (if this tweet quotes another) |
| `emojis` | `list \| None` | Extracted emojis (if any) |
| `comments` | `int` | Reply count |
| `likes` | `int` | Like count |
| `retweets` | `int` | Retweet count |
| `media` | `dict \| None` | Media: `{"image_links": ["https://..."]}` — `None` if no media |
| `tweet_url` | `str` | Permalink, e.g. `"https://x.com/user/status/123"` |
| `raw` | `dict` | Full GraphQL payload |

### User record

Returned by `get_followers()`, `get_following()`, and `get_user_info()`.

| Field | Type | Description |
|-------|------|-------------|
| `user_id` | `str` | Twitter user ID |
| `username` | `str` | Screen name / handle |
| `name` | `str` | Display name |
| `description` | `str` | Bio text |
| `location` | `str \| None` | Self-reported location |
| `created_at` | `str` | Account creation date (Twitter date string) |
| `followers_count` | `int` | Follower count |
| `following_count` | `int` | Following count |
| `statuses_count` | `int` | Total tweets posted |
| `favourites_count` | `int` | Total likes given |
| `media_count` | `int` | Media tweet count |
| `listed_count` | `int` | List membership count |
| `verified` | `bool` | Legacy verified badge |
| `blue_verified` | `bool` | Twitter Blue / paid verification |
| `protected` | `bool` | Protected (private) account |
| `profile_image_url` | `str` | Profile photo URL |
| `profile_banner_url` | `str` | Banner image URL |
| `url` | `str \| None` | Website URL set in bio |
| `raw` | `dict` | Full GraphQL payload (only present when `raw_json=True`) |

**Followers / following only:** each record also has `type` (`"followers"` or `"following"`) and `target` (info about the queried account).

**User info only:** each record has `input` (the queried input) instead of `type`/`target`. The `raw` field is omitted by default (not present unless the underlying engine returns it).

---

## Resume Interrupted Searches

Resume a search from where it left off using SQLite cursor checkpoints:

```python
# First run — gets interrupted or completes partially
tweets = s.search("query", since="2024-01-01", until="2024-06-01", limit=1000)

# Resume — picks up from last saved checkpoint
tweets = s.search("query", since="2024-01-01", until="2024-06-01", limit=1000, resume=True)
```

Resume works by matching a hash of the query parameters. The same `since`, `until`, `query`, `lang`, and `display_type` must be provided to resume correctly.

---

## Configuration Reference

All fields have sensible defaults. Override with `ScweetConfig`:

```python
from Scweet import Scweet, ScweetConfig

s = Scweet(
    cookies_file="cookies.json",
    config=ScweetConfig(
        concurrency=3,
        proxy="http://user:pass@host:port",
        min_delay_s=2.0,
    ),
)
```

### Core

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `db_path` | `str` | `"scweet_state.db"` | SQLite state file path |
| `proxy` | `str \| dict \| None` | `None` | HTTP proxy for API calls |
| `concurrency` | `int` | `5` | Number of parallel workers |

### Output

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `save_dir` | `str` | `"outputs"` | Default output directory |
| `save_format` | `str` | `"csv"` | Default format: `"csv"`, `"json"`, or `"both"` |

### HTTP Tuning

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `api_http_mode` | `str` | `"auto"` | HTTP mode: `"auto"`, `"async"`, `"sync"` |
| `api_http_impersonate` | `str \| None` | `None` | Browser impersonation target for curl_cffi |
| `api_user_agent` | `str \| None` | `None` | Custom User-Agent string |

### Rate Limiting

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `daily_requests_limit` | `int` | `30` | Max API requests per account per day |
| `daily_tweets_limit` | `int` | `600` | Max tweets per account per day |
| `max_empty_pages` | `int` | `1` | Stop after N consecutive empty result pages |
| `api_page_size` | `int` | `20` | Tweets per API page (1-100) |
| `min_delay_s` | `float` | `2.0` | Minimum delay between requests |
| `requests_per_min` | `int` | `30` | Rate limit per account per minute |

### Advanced

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `enable_wal` | `bool` | `True` | SQLite WAL mode |
| `busy_timeout_ms` | `int` | `5000` | SQLite busy timeout |
| `lease_ttl_s` | `int` | `120` | Account lease time-to-live |
| `lease_heartbeat_s` | `float` | `30.0` | Heartbeat interval for active leases |
| `cooldown_default_s` | `float` | `120.0` | Default cooldown after rate limit |
| `transient_cooldown_s` | `float` | `120.0` | Cooldown for transient errors (e.g., 404/stale query IDs) |
| `auth_cooldown_s` | `float` | `2592000.0` | Cooldown for auth failures (30 days) |
| `cooldown_jitter_s` | `float` | `10.0` | Random jitter added to cooldowns |
| `task_retry_base_s` | `int` | `1` | Base delay for task retry backoff |
| `task_retry_max_s` | `int` | `30` | Max delay for task retry backoff |
| `max_task_attempts` | `int` | `3` | Max retry attempts per task |
| `max_fallback_attempts` | `int` | `3` | Max fallback attempts on failure |
| `max_account_switches` | `int` | `2` | Max account switches per task |
| `scheduler_min_interval_s` | `int` | `300` | Minimum time interval split (seconds) |
| `n_splits` | `int` | `5` | Number of time interval splits for search |
| `priority` | `int` | `1` | Task priority |
| `proxy_check_on_lease` | `bool` | `True` | Verify proxy connectivity before leasing |
| `proxy_check_url` | `str` | `"https://x.com/robots.txt"` | URL for proxy check |
| `proxy_check_timeout_s` | `float` | `10.0` | Timeout for proxy check |
| `profile_timeline_allow_anonymous` | `bool` | `False` | Allow anonymous profile timeline requests |

### Manifest (Query IDs)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `manifest_url` | `str \| None` | `None` | Remote manifest URL for query IDs |
| `manifest_ttl_s` | `int` | `3600` | Cache TTL for remote manifest |
| `manifest_update_on_init` | `bool` | `False` | Fetch remote manifest on init |
| `manifest_scrape_on_init` | `bool` | `False` | Scrape fresh query IDs from X on init |

---

## Auto-Updating Query IDs

Twitter/X rotates GraphQL query IDs periodically. When IDs go stale, requests return 404. Scweet ships with default IDs that work at release time, but you can auto-fetch fresh ones:

```python
s = Scweet(
    cookies_file="cookies.json",
    config=ScweetConfig(manifest_scrape_on_init=True),
)
```

This fetches the current `main.js` bundle from X on init and extracts the latest query IDs. It adds a few seconds to startup but ensures your requests use current IDs.

---

## Account Management (ScweetDB)

`ScweetDB` provides direct access to the SQLite state for account inspection and management:

```python
from Scweet import ScweetDB

db = ScweetDB("scweet_state.db")
```

### accounts_summary()

```python
summary = db.accounts_summary()
# {"db_path": "...", "total": 5, "eligible": 3, "unusable": 1, "cooling_down": 1, ...}
```

### list_accounts()

```python
accounts = db.list_accounts(limit=10, eligible_only=True)
# Returns list of account dicts with redacted secrets (fingerprints only)

# Include cookie keys
accounts = db.list_accounts(include_cookies=True)

# Reveal full secrets (use with caution)
accounts = db.list_accounts(reveal_secrets=True)
```

### get_account(username)

```python
account = db.get_account("my_account")
```

### repair_account(username)

Reset cooldowns, clear leases, and optionally refresh auth tokens:

```python
result = db.repair_account("my_account")
# {"updated": 1, "changes": ["cooldown_cleared", "lease_cleared", ...], ...}

# Force token refresh even if auth material looks valid
result = db.repair_account("my_account", force_refresh=True)
```

### reset_account_cooldowns()

```python
# Reset all account cooldowns
db.reset_account_cooldowns()

# Reset specific accounts
db.reset_account_cooldowns(usernames=["account1", "account2"])

# Include unusable accounts (reactivates them)
db.reset_account_cooldowns(include_unusable=True)
```

### clear_leases()

```python
# Clear expired leases only (safe)
db.clear_leases(expired_only=True)

# Clear all leases
db.clear_leases(expired_only=False)
```

### reset_daily_counters()

```python
db.reset_daily_counters()
```

### Other methods

- `delete_account(username)` — Remove an account from the pool.
- `set_account_proxy(username, proxy)` — Set or clear a per-account proxy override.
- `mark_account_unusable(username)` — Mark an account as unusable (won't be leased).
- `import_accounts_from_sources(...)` — Import accounts from files/cookies into the DB.
- `collapse_duplicates_by_auth_token(dry_run=True)` — Find and merge duplicate accounts.
- `get_checkpoint(query_hash)` / `clear_checkpoint(query_hash)` / `clear_all_checkpoints()` — Manage resume checkpoints.
- `list_runs(limit=50)` / `last_run()` / `runs_summary()` — Inspect run history.

---

## Logging

Scweet uses Python's standard `logging` module under the `"Scweet"` logger namespace. By default no output is produced (NullHandler — standard library practice). To see logs, configure a handler on the `"Scweet"` logger in your application:

```python
import logging

logging.basicConfig(level=logging.INFO)
# or target only Scweet:
logging.getLogger("Scweet").setLevel(logging.INFO)
logging.getLogger("Scweet").addHandler(logging.StreamHandler())
```

The CLI automatically sets up INFO-level logging to stderr. Pass `-v` / `--verbose` to the CLI for DEBUG-level output.

---

## Async Usage

All public methods have async variants. Use them in async contexts:

```python
import asyncio
from Scweet import Scweet

async def main():
    s = Scweet(cookies_file="cookies.json")

    tweets = await s.asearch("query", since="2024-01-01", limit=100)
    profiles = await s.aget_user_info(["elonmusk"])
    followers = await s.aget_followers(["elonmusk"], limit=500)

asyncio.run(main())
```

The sync methods (`search`, `get_followers`, etc.) wrap their async counterparts with `asyncio.run()`, so they cannot be called from within an already-running event loop.

### No close needed

`Scweet` and `ScweetDB` don't require explicit closing. HTTP sessions are created and closed per-request internally, and SQLite connections are scoped per-operation. You can create a `Scweet` instance, use it, and let it go out of scope — no resource leaks.

---

## Error Handling

All Scweet methods raise exceptions on failure — there is no silent empty-result mode. Wrap calls in try/except to handle errors explicitly:

```python
from Scweet import Scweet, AccountPoolExhausted, NetworkError, RunFailed

s = Scweet(cookies_file="cookies.json")

try:
    tweets = s.search("query")
except AccountPoolExhausted as e:
    print(f"No accounts available: {e}")
except NetworkError:
    print("Network issue — check your connection or proxy")
except RunFailed as e:
    print(f"Scrape failed: {e}")
```

This applies to all methods: `search`, `get_profile_tweets`, `get_followers`, `get_following`, and `get_user_info`.

### Exception hierarchy

All Scweet exceptions inherit from `ScweetError`, so you can catch everything with a single handler:

```
ScweetError                          # Base — catch-all
  AccountPoolExhausted               # No eligible accounts (all cooled down / at daily limits)
  EngineError                        # Engine-level runtime error
    RunFailed                        # Run completed but couldn't produce results
      NetworkError                   # Network/connectivity failure
      ProxyError                     # Proxy misconfiguration or connectivity failure
```

All exceptions are importable from the top-level package:

```python
from Scweet import ScweetError, AccountPoolExhausted, RunFailed, NetworkError, ProxyError, EngineError
```

### Troubleshooting

**Empty results / fewer tweets than expected**
- Check your date range — Twitter search is often shallow on older dates
- Try `display_type="Latest"` to get chronological results instead of "Top"
- Your account may have hit its daily cap (`daily_requests_limit` / `daily_tweets_limit` in `ScweetConfig`). Check with `ScweetDB("scweet_state.db").accounts_summary()`
- Run with logging enabled to see what's happening: `logging.basicConfig(level=logging.INFO)`

**`AccountPoolExhausted`**
- All accounts are cooling down or at daily limits. The error message includes counts: `total=N, unusable=M, cooling_down=K`
- Wait for cooldowns to expire, or add more accounts
- Reset cooldowns manually: `ScweetDB("scweet_state.db").reset_account_cooldowns()`

**`RunFailed` / `NetworkError`**
- Check your internet connection and proxy configuration
- X may have rotated GraphQL query IDs — enable `manifest_scrape_on_init=True` to auto-fetch fresh ones
- 404 errors in logs mean stale query IDs (transient) — not bad auth

**Auth errors (401/403 in logs)**
- Your `auth_token` or `ct0` cookie has expired — refresh them from your browser
- Use `ScweetDB("scweet_state.db").repair_account("username", force_refresh=True)` to trigger token refresh

---

## CLI

Scweet ships with a `scweet` command-line tool installed automatically alongside the package. No extra setup required — just `pip install -U Scweet`.

### Usage pattern

```
scweet [auth options] [config options] <subcommand> [subcommand options]
```

### Global options

**Auth:**

| Flag | Description |
|------|-------------|
| `--auth-token TOKEN` | `auth_token` cookie value |
| `--cookies-file FILE` | Path to a cookies JSON file |
| `--env-file FILE` | Path to a `.env` file |
| `--db-path PATH` | SQLite state file (default: `scweet_state.db`) |

**Config:**

| Flag | Description |
|------|-------------|
| `--proxy PROXY` | Proxy URL or JSON string |
| `--concurrency N` | Worker concurrency (default: `5`) |

### Output options

Available on every subcommand:

| Flag | Description |
|------|-------------|
| `--save` | Save results to file |
| `--save-format {csv,json,both}` | File format (default: `csv`) |
| `--save-dir DIR` | Output directory (default: `outputs`) |
| `--save-name NAME` | Base filename for saved output |
| `--pretty` | Print results as indented JSON to stdout |

By default the CLI runs silently — no output is printed. Use `--save` to write results to a file, `--pretty` to print to stdout, or both together.

### Subcommands

#### `search`

```bash
scweet --auth-token TOKEN search [QUERY] [options]
```

`QUERY` is optional — you can use filters alone.

| Flag | Description |
|------|-------------|
| `--since DATE` | Start date `YYYY-MM-DD` |
| `--until DATE` | End date `YYYY-MM-DD` |
| `--limit N` | Max tweets to return |
| `--lang CODE` | Language code (e.g. `en`) |
| `--display-type {Top,Latest}` | Default: `Top` |
| `--from USER [USER ...]` | Tweets from these users |
| `--to USER [USER ...]` | Tweets sent to these users |
| `--mention USER [USER ...]` | Tweets mentioning these users |
| `--all-words WORD [WORD ...]` | Tweets containing ALL of these words (AND) |
| `--any-words WORD [WORD ...]` | Tweets containing ANY of these words (OR) |
| `--exact-phrases PHRASE [PHRASE ...]` | Tweets containing these exact phrases |
| `--hashtag TAG [TAG ...]` | Tweets containing any of these hashtags |
| `--hashtags-exclude TAG [TAG ...]` | Exclude tweets with these hashtags |
| `--exclude WORD [WORD ...]` | Exclude tweets with these words |
| `--tweet-type {originals-only,replies-only,retweets-only,exclude-replies,exclude-retweets}` | Filter by tweet type |
| `--min-likes N` | Minimum likes |
| `--min-replies N` | Minimum replies |
| `--min-retweets N` | Minimum retweets |
| `--has-images` | Must contain images |
| `--has-videos` | Must contain videos |
| `--has-links` | Must contain links |
| `--has-mentions` | Must contain @mentions |
| `--has-hashtags` | Must contain hashtags |
| `--verified-only` | Verified accounts only |
| `--blue-verified-only` | Blue verified accounts only |
| `--place PLACE` | Place filter |
| `--geocode GEOCODE` | Geocode filter (e.g. `40.7,-74.0,10km`) |
| `--near PLACE` | Near this location (e.g. `"San Francisco"`) |
| `--within RADIUS` | Radius for `--near` (e.g. `15km` or `10mi`) |
| `--resume` | Resume from last checkpoint |
| `--max-empty-pages N` | Stop after N consecutive empty pages |

#### `profile-tweets`

```bash
scweet --auth-token TOKEN profile-tweets USER [USER ...] [options]
```

| Flag | Description |
|------|-------------|
| `--limit N` | Max tweets to return |
| `--resume` | Resume from last checkpoint |
| `--max-empty-pages N` | Stop after N consecutive empty pages |

#### `followers` / `following`

```bash
scweet --auth-token TOKEN followers USER [USER ...] [options]
scweet --auth-token TOKEN following USER [USER ...] [options]
```

| Flag | Description |
|------|-------------|
| `--limit N` | Max users to return |
| `--resume` | Resume from last checkpoint |
| `--max-empty-pages N` | Stop after N consecutive empty pages |
| `--raw-json` | Return raw API JSON instead of normalized dicts |

#### `user-info`

```bash
scweet --auth-token TOKEN user-info USER [USER ...]
```

No pagination — one API call per user.

### Examples

```bash
# Search (defaults to last 30 days — set explicit dates for reproducibility)
scweet --auth-token TOKEN search "ChatGPT" --limit 200 --pretty

# Search with date range and engagement filters
scweet --auth-token TOKEN search "AI tools" \
  --since 2025-01-01 --until 2025-06-01 \
  --min-likes 100 --has-images --limit 500

# Tweets from specific accounts containing a hashtag
scweet --auth-token TOKEN search \
  --from elonmusk naval sama \
  --hashtag AI startups --limit 100

# Pull a user's timeline, save to JSON
scweet --cookies-file cookies.json profile-tweets elonmusk \
  --limit 200 --save --save-format json

# Get followers and pipe to jq
scweet --auth-token TOKEN followers elonmusk --limit 1000 --pretty | jq '.[].screen_name'

# Lookup multiple profiles
scweet --auth-token TOKEN user-info elonmusk OpenAI sama --pretty

# Resume a previously interrupted search
scweet --auth-token TOKEN search "python" --since 2025-01-01 --resume
```

### Help

```bash
scweet --help
scweet search --help
scweet followers --help
```

---

## Migration from v4

| v4 | v5 |
|----|-----|
| `Scweet.from_sources(...)` | `Scweet(cookies_file=...)` |
| `scweet.scrape(words=["bitcoin"], ...)` | `s.search("bitcoin", ...)` |
| `scweet.ascrape(...)` | `s.asearch(...)` |
| `scweet.profile_tweets(usernames=[...])` | `s.get_profile_tweets([...])` |
| `scweet.get_user_information(usernames=[...])` | `s.get_user_info([...])` |
| `ScweetConfig.from_sources(overrides={...})` | `ScweetConfig(field=value)` |
| Nested config (`pool.concurrency`) | Flat config (`concurrency`) |
| `from Scweet.scweet import Scweet` | `from Scweet import Scweet` |

---

MIT License
