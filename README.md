# Scweet v4: Twitter/X Scraper

[![Scweet Actor Status](https://apify.com/actor-badge?actor=altimis/scweet)](https://apify.com/altimis/scweet)
[![PyPI Downloads](https://static.pepy.tech/badge/scweet/month)](https://pepy.tech/projects/scweet)
[![PyPI Version](https://img.shields.io/pypi/v/scweet.svg)](https://pypi.org/project/scweet/)
[![License](https://img.shields.io/github/license/Altimis/scweet)](https://github.com/Altimis/scweet/blob/main/LICENSE)

> Note: Scweet is not affiliated with Twitter/X. Use responsibly and lawfully.

Scweet is:

- A hosted [**Apify Actor**](https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=jeb97) (recommended for production runs and easy scaling).
- A Python **library** (recommended when you want to embed scraping in your own codebase).

Tweet search scraping in v4 is **API-only** (Twitter/X web GraphQL). Scweet keeps local state in SQLite (accounts, leases, resume checkpoints).

Full documentation: `DOCUMENTATION.md`

## Run Scweet on Apify (Hosted)

If you want the fastest path to results (and the best option for production workflows), use the hosted Apify Actor:

- Actor page: https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=jeb97
- Apify offers a free plan/trial (plan limits can change); see the Actor page for current details.

[![Run on Apify](https://apify.com/static/run-on-apify-button.svg)](https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=jeb97)

For more details, see Apify Python client quickstart: https://apify.com/altimis/scweet/api/python

## Should I Use the Actor or the Library?

| Use case | Recommended |
| --- | --- |
| You want hosted runs, scheduling, scalable execution, and datasets | Apify Actor |
| You want to embed scraping inside your own Python pipeline/app | Python library |
| You don’t want to manage local state DB / provisioning details | Apify Actor |
| You need full control over provisioning/account leasing | Python library |

## Trust & Expectations

- This is scraping (Twitter/X web GraphQL), not an official API.
- You need accounts/cookies. Rate limits and anti-bot controls vary.
- For production workflows, the Apify Actor is usually the simplest and most reliable option.

## Installation (Scweet library)

```bash
pip install Scweet
```

## Imports (v4)

```python
from Scweet import Scweet, ScweetConfig, ScweetDB
```

Legacy import path (supported in v4.x, deprecated):

```python
from Scweet.scweet import Scweet
```

## Python Library Quickstart (Cookies -> Scrape)

```python
from Scweet import Scweet

scweet = Scweet.from_sources(
    db_path="scweet_state.db",
    # Provide accounts via one (or more) sources:
    cookies_file="cookies.json",       # also supports Netscape cookies.txt
    # accounts_file="accounts.txt",
    # env_path=".env",
    # cookies={"auth_token": "...", "ct0": "..."},
    # cookies="YOUR_AUTH_TOKEN",  # convenience auth_token string (ct0 can be bootstrapped if allowed)
    output_format="both",  # csv|json|both|none
)

tweets = scweet.scrape(
    since="2026-02-01",
    until="2026-02-07",
    words=["openai"],
    limit=200,
    resume=True,
    save_dir="outputs",
    custom_csv_name="openai.csv",
)

print("tweets:", len(tweets))
```

Examples you can run from source checkout:

- Sync: `examples/sync_example.py`
- Async: `examples/async_example.py`

Example input templates (placeholders):

- `examples/.env`
- `examples/accounts.txt`
- `examples/cookies.json`

## Configure (Keep It Simple)

If you want one place to control everything, build a config and pass it to `Scweet(config=...)`. Keep most advanced knobs in `DOCUMENTATION.md`.

```python
from Scweet import Scweet, ScweetConfig

cfg = ScweetConfig.from_sources(
    db_path="scweet_state.db",
    cookies_file="cookies.json",       # optional provisioning source
    accounts_file="accounts.txt",      # optional provisioning source
    # cookies={"auth_token": "...", "ct0": "..."},  # optional provisioning source
    # cookies="YOUR_AUTH_TOKEN",  # optional provisioning source
    bootstrap_strategy="auto",         # auto|token_only|nodriver_only|none
    provision_on_init=True,            # import sources during Scweet init
    output_format="both",              # csv|json|both|none
    resume_mode="hybrid_safe",         # legacy_csv|db_cursor|hybrid_safe
    strict=False,                      # raise instead of returning empty output for some failures
    proxy=None,                        # used for API calls and nodriver bootstrap
    overrides={
        "pool": {"concurrency": 4},
        "operations": {
            "account_lease_ttl_s": 300,
            "account_requests_per_min": 30,
            "account_min_delay_s": 2,
            "account_daily_requests_limit": 30,
            "account_daily_tweets_limit": 600,
        },
        "output": {"dedupe_on_resume_by_tweet_id": True},
    },
)

scweet = Scweet(config=cfg)
```

Key knobs most users care about:

- `pool.concurrency`
- `operations.account_requests_per_min`
- `operations.account_min_delay_s`
- `operations.account_daily_requests_limit` and `operations.account_daily_tweets_limit`
- `output.format` and `output.dedupe_on_resume_by_tweet_id`
- `resume.mode` (`legacy_csv`, `db_cursor`, `hybrid_safe`)

Logging (optional):

```python
from Scweet import configure_logging

configure_logging(profile="simple", level="INFO", force=True)  # notebook-friendly
```

## Provision Accounts (DB-First)

Scweet stores accounts in SQLite. Provisioning imports account sources into the DB and marks which accounts are eligible.

Supported sources:

- `accounts.txt`
- `cookies.json` (and Netscape `cookies.txt`)
- `cookies=` payload (cookie dict/list/header string/auth_token string/file path/JSON string)
- `.env` via `env_path`

You can provision on init (recommended) or manually:

```python
from Scweet import Scweet

scweet = Scweet.from_sources(db_path="scweet_state.db", provision_on_init=False)

result = scweet.provision_accounts(
    accounts_file="accounts.txt",
    cookies_file="cookies.json",
    # env_path=".env",
    # cookies={"auth_token": "...", "ct0": "..."},
    # cookies="YOUR_AUTH_TOKEN",
)
print(result)  # {"processed": ..., "eligible": ...}
```

### accounts.txt format

One account per line (colon-separated):

```text
username:password:email:email_password:2fa:auth_token
```

Missing trailing fields are allowed.

### cookies.json format

```json
[
  {
    "username": "acct1",
    "cookies": { "auth_token": "...", "ct0": "..." }
  }
]
```

### Per-account proxy override (optional)

By default, `proxy=` (runtime proxy) applies to all accounts. If you need a different proxy per account, set a proxy on the account record:

- In `cookies.json`: add `"proxy"` to the account object (string URL or dict).
- In `accounts.txt`: append a tab then a proxy value (string URL or JSON dict).
- Or set it later via `ScweetDB.set_account_proxy(username, proxy)`.

Proxy credentials are supported:

- API HTTP accepts either a URL string like `"http://user:pass@host:port"` or a dict like `{"host": "...", "port": 8080, "username": "...", "password": "..."}`.
- nodriver bootstrap also supports authenticated proxies, but the dict form is recommended for proxy auth.

Example `cookies.json` record with proxy:

```json
[
  {
    "username": "acct1",
    "cookies": { "auth_token": "...", "ct0": "..." },
    "proxy": { "host": "127.0.0.1", "port": 8080, "username": "proxyuser", "password": "proxypass" }
  }
]
```

Example `accounts.txt` line with a proxy (tab-separated):

```text
alice:::::AUTH_TOKEN_HERE	{"host":"127.0.0.1","port":8080}
```

## Scrape (Inputs + Outputs)

Key scrape inputs:

- `since`, `until` (YYYY-MM-DD)
- `words` (list or legacy string split by `//`)
- `from_account`, `to_account`, `mention_account`, `hashtag`, `lang`
- `display_type` ("Top" or "Latest")
- `limit` (best-effort per run)
- `resume=True` appends to outputs and continues using the configured resume mode

The return value is always `list[dict]` of raw GraphQL tweet objects.

Files are controlled by `output_format`:

- `csv`: curated "important fields" schema
- `json`: raw tweets (full fidelity)
- `both`: write both
- `none`: return only

## Resume + Dedupe

- `resume=True` appends to existing CSV and JSON outputs.
- To avoid writing duplicates across runs when resuming:
  - `overrides={"output": {"dedupe_on_resume_by_tweet_id": True}}`

## Local DB Helpers (ScweetDB)

Use `ScweetDB` to inspect and maintain the local state DB:

```python
from Scweet import ScweetDB

db = ScweetDB("scweet_state.db")
print(db.accounts_summary())
print(db.list_accounts(limit=10, eligible_only=True))
print(db.set_account_proxy("acct1", {"host": "127.0.0.1", "port": 8080}))
print(db.reset_daily_counters())
print(db.clear_leases(expired_only=True))
print(db.reset_account_cooldowns(clear_leases=True, include_unusable=True))
print(db.collapse_duplicates_by_auth_token(dry_run=True))
```

## Coming Soon

- Profile info scraping
- Followers/following scraping
- Profile timeline scraping
- Richer search query inputs

## More Details

See `DOCUMENTATION.md` for the full guide (cookies formats, logging setup, strict mode, manifest updates, advanced config knobs).

## Contribute
We welcome **PRs**, bug reports, and feature suggestions!  
If you find Scweet useful, consider **starring** the repo ⭐ 

---
MIT License • © 2020–2026 Altimis
