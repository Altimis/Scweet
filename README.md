# Scweet v4

Scweet v4 keeps the familiar v3 public API while moving scraping toward an API-only core and introducing DB-first account provisioning backed by SQLite.

## v4 status

- v4 facade routing is active.
- Legacy public signatures remain callable.
- Preferred import: `from Scweet import Scweet`.
- Legacy import remains supported in v4.x but is deprecated: `from Scweet.scweet import Scweet`.

## Architecture summary

- Compatibility facade in `Scweet/Scweet/scweet.py` keeps legacy method signatures and return shapes.
- New core modules live in `Scweet/Scweet/v4/`.
- Stateful components use local SQLite (`runs`, `accounts`, `resume_state`, manifest cache).
- Internal runtime uses async runner + in-memory task queue + account leasing.

## Installation

```bash
pip install Scweet
```

## Import policy

Preferred import (recommended for v4 usage):

```python
from Scweet import Scweet
```

Legacy import (supported in v4.x, deprecated):

```python
from Scweet.scweet import Scweet
```

## Backward compatibility (v4.x)

Compatibility guarantees include:

- Legacy class import path still works: `from Scweet.scweet import Scweet`.
- Preferred class import path available: `from Scweet import Scweet`.
- Legacy constructor args remain accepted (for example: `env_path`, `cookies`, `cookies_path`, `n_splits`, `concurrency`, `headless`).
- Legacy method signatures preserved for:
  - `scrape` / `ascrape`
  - `get_user_information` / `aget_user_information`
  - follows methods (`get_followers`, `get_following`, etc.)
- Legacy CSV output schema preserved.

## Account provisioning (DB-first)

Scweet stores account records in SQLite and reuses the DB state across runs. When you provide account sources, they are imported into the DB (best-effort) and then leased to workers during scraping.

Supported account inputs:

- `.env` (single-account, legacy style)
- `accounts.txt`
- `cookies.json`
- direct `cookies=` payload

`.env` key precedence (single account):

1. `AUTH_TOKEN` + `CT0` (or `CSRF`)
2. `AUTH_TOKEN` only
3. legacy credentials (`EMAIL`/`EMAIL_PASSWORD` and/or `USERNAME`/`PASSWORD`)

Phase 1 provisioning-related config knobs:

- `accounts.provision_on_init` (default `True`)
- `accounts.bootstrap_strategy` (default `"auto"`; one of `auto`, `token_only`, `nodriver_only`, `none`)
- `accounts.store_credentials` (default `False`; set to `True` only if you accept storing plaintext credentials in SQLite)
- `runtime.strict` (default `False`; if `True`, "no usable accounts" should raise instead of returning an empty result)

## Resume modes

Scweet v4 supports three resume modes under `config.resume.mode`:

- `legacy_csv`: v3-compatible resume using max CSV `Timestamp` to override `since`.
- `db_cursor`: resume from SQLite checkpoint (`since` + `cursor`) only.
- `hybrid_safe`: try DB checkpoint first, then fallback to CSV timestamp behavior.

Important compatibility rule:

- If you instantiate through the legacy import path (`from Scweet.scweet import Scweet`), resume is forced to `legacy_csv` behavior for compatibility.

## Account source formats

### `accounts.txt`

One account per line (colon-separated):

```text
username:password:email:email_password:2fa:auth_token
```

Notes:

- Blank lines and lines starting with `#` are ignored.
- Missing trailing fields are accepted.
- The auth token segment may include additional colons; parser keeps the rest as token.

### `cookies.json`

Accepted forms include:

1. List of account records.
2. Object with `accounts: [...]`.
3. Single account object.
4. Object mapping username -> cookies/account payload.

Minimal example:

```json
[
  {
    "username": "acct1",
    "cookies": {
      "auth_token": "...",
      "ct0": "..."
    }
  }
]
```

## Usage examples

### Scrape (v4 import path)

```python
from Scweet import Scweet

scweet = Scweet(
    db_path="scweet_state.db",
    accounts_file="accounts.txt",
    cookies_file="cookies.json",
    config={
        "resume": {"mode": "hybrid_safe"},
        "pool": {"n_splits": 8, "concurrency": 4},
    },
)

tweets = scweet.scrape(
    since="2026-02-01",
    until="2026-02-07",
    words=["bitcoin", "ethereum"],
    limit=200,
    save_dir="outputs",
    custom_csv_name="crypto.csv",
    resume=True,
)
```

### Preload DB then scrape (manual provisioning)

```python
from Scweet import Scweet

# Disable auto-provisioning if you want an explicit "provision first" step.
scweet = Scweet(
    db_path="scweet_state.db",
    config={"accounts": {"provision_on_init": False}},
)

result = scweet.provision_accounts(
    accounts_file="accounts.txt",
    cookies_file="cookies.json",
    env_path=".env",
    cookies={"auth_token": "...", "ct0": "..."},
)
print(result)  # {"processed": ..., "eligible": ...}

# DB-first reuse: re-running provisioning does not re-bootstrap accounts that already have usable auth in SQLite.
tweets = scweet.scrape(
    since="2026-02-01",
    until="2026-02-07",
    words=["openai"],
    limit=50,
    save_dir="outputs",
    custom_csv_name="tweets.csv",
)

# Strict mode: raise instead of silently returning empty results when no usable accounts exist.
strict_scweet = Scweet(
    db_path="scweet_state.db",
    config={"runtime": {"strict": True}, "accounts": {"provision_on_init": False}},
)
strict_scweet.provision_accounts(env_path=".env")
```

### Backward-compatible usage (legacy import path)

```python
from Scweet.scweet import Scweet

# Deprecated import path, still supported in v4.x.
scweet = Scweet(env_path=".env", n_splits=5, concurrency=5, headless=True)

results = scweet.scrape(
    since="2025-01-01",
    until="2025-01-07",
    words=["scweet"],
    resume=True,
)
```

## Migration and release notes

- Migration guide: `Scweet/MIGRATION_V3_TO_V4.md`
- Changelog: `Scweet/CHANGELOG.md`

## Responsible use

Scweet is not affiliated with Twitter/X. Use lawfully, respect platform terms, and avoid misuse.
