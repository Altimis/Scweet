# Scweet (v4): API-Only Tweet Search Scraping in Python

[![Scweet Actor Status](https://apify.com/actor-badge?actor=altimis/scweet)](https://apify.com/altimis/scweet)
[![PyPI Downloads](https://static.pepy.tech/badge/scweet/month)](https://pepy.tech/projects/scweet)
[![PyPI Version](https://img.shields.io/pypi/v/scweet.svg)](https://pypi.org/project/scweet/)
[![License](https://img.shields.io/github/license/Altimis/scweet)](https://github.com/Altimis/scweet/blob/main/LICENSE)

> Note: Scweet is not affiliated with Twitter/X. Use responsibly and lawfully.

Scweet is a Python library for scraping tweets via Twitter/X web GraphQL.

What Scweet v4 is good for:

- Search tweets by keywords, hashtags, mentions, accounts, and date windows.
- Keep state locally (SQLite) so accounts + resume checkpoints persist across runs.
- Build repeatable data pipelines where you can provision once and scrape many times.

v4 notes:

- Tweet search scraping is API-only (no browser scraping engine).
- `nodriver` is used internally only for optional cookie bootstrap (credentials login -> cookies).
- Profile/followers/following APIs are coming soon (v4 methods exist for compatibility but are not implemented yet).

Full documentation: `DOCUMENTATION.md`

## Scweet on Apify (Hosted Option)

If you prefer a hosted / no local setup option, Scweet is also available as an Apify Actor:

- Link: https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=jeb97
- Fast, managed runs without maintaining local infrastructure.

[![Run on Apify](https://apify.com/static/run-on-apify-button.svg)](https://apify.com/altimis/scweet?fpr=a40q9&fp_sid=jeb97)

## Installation

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

## Quickstart (Cookies -> Scrape)

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
- Notebook: `examples/example.ipynb`

Example input templates (placeholders):

- `examples/.env`
- `examples/accounts.txt`
- `examples/cookies.json`

## Configure Scweet (Recommended: ScweetConfig)

If you want one place to control everything, build a config and pass it to `Scweet(config=...)`.

```python
from Scweet import Scweet, ScweetConfig

cfg = ScweetConfig.from_sources(
    db_path="scweet_state.db",
    cookies="YOUR_AUTH_TOKEN",
    cookies_file="cookies.json",       # optional provisioning source
    accounts_file="accounts.txt",      # optional provisioning source
    # cookies={"auth_token": "...", "ct0": "..."},  # optional provisioning source
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
                # Per-account daily caps (lease eligibility; resets by UTC day).
                "account_daily_requests_limit": 30,
                "account_daily_tweets_limit": 600,
            },
            "output": {"dedupe_on_resume_by_tweet_id": True},
        },
    )

scweet = Scweet(config=cfg)
```

Daily caps:

- `operations.account_daily_tweets_limit` and `operations.account_daily_requests_limit` control when an account becomes ineligible for leasing for the rest of the UTC day.
- Counters reset automatically when the day changes (UTC), or you can reset them manually via `ScweetDB.reset_daily_counters()`.

## Provision Accounts (DB-First)

Scweet stores accounts in SQLite. Provisioning imports account sources into the DB and marks which accounts are eligible.

Supported sources include:

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

### Per-account proxy override (optional)

By default, `proxy=` (runtime proxy) applies to all accounts. If you need a different proxy per account, set a proxy on the account record:

- In `cookies.json`: add `"proxy"` to the account object (string URL or dict).
- In `accounts.txt`: append a tab then a proxy value (string URL or JSON dict).
- Or set it later via `ScweetDB.set_account_proxy(username, proxy)`.

Proxy credentials are supported:

- API HTTP (curl_cffi) accepts either a URL string like `"http://user:pass@host:port"` or a dict like `{"host": "...", "port": 8080, "username": "...", "password": "..."}`.
- nodriver bootstrap also supports authenticated proxies, but the dict form is recommended for proxy auth.

Example `cookies.json` record:

```json
[
  {
    "username": "acct1",
    "cookies": {"auth_token": "...", "ct0": "..."},
    "proxy": {"host": "127.0.0.1", "port": 8080, "username": "proxyuser", "password": "proxypass"}
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

- API-only profile info scraping
- API-only followers/following scraping 
- API-only login/provisioning from creds
- API-only profile timeline scraping
- Richer scraping query inputs.

## More Details

See `DOCUMENTATION.md` for the full guide (cookies formats, logging setup, strict mode, manifest updates, advanced config knobs).
