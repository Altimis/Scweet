# Scweet v4

Scweet v4 keeps the familiar public API while moving internals to a modern async architecture with account pooling and SQLite state.

## v4 status

- v4 facade routing is active.
- Legacy public signatures remain callable.
- Preferred path: `from Scweet import Scweet`.
- Legacy path remains supported in v4.x but is deprecated: `from Scweet.scweet import Scweet`.

## Architecture summary

- Compatibility facade in `Scweet/Scweet/scweet.py` keeps legacy method signatures and return shapes.
- New core modules live in `Scweet/Scweet/v4/`.
- Stateful components use local SQLite (`runs`, `accounts`, `resume_state`, manifest cache).
- Internal runtime uses async runner + in-memory task queue + account leasing.
- Engines are selectable (`browser`, `api`, `auto`) through config.

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

## Deprecation policy (v4.x -> v5.0)

The following are still supported in v4.x but emit `FutureWarning` and are planned for removal in v5.0:

- Legacy import path: `Scweet.scweet`
- Constructor arg `mode` -> use `engine`
- Constructor arg `env_path` -> use `accounts_file` / `cookies_file`
- Constructor arg `n_splits` -> use `config.pool.n_splits`
- Constructor arg `concurrency` -> use `config.pool.concurrency`

## Resume modes

Scweet v4 supports three resume modes under `config.resume.mode`:

- `legacy_csv`: v3-compatible resume using max CSV `Timestamp` to override `since`.
- `db_cursor`: resume from SQLite checkpoint (`since` + `cursor`) only.
- `hybrid_safe`: try DB checkpoint first, then fallback to CSV timestamp behavior.

Important compatibility rule:

- If you instantiate through the legacy facade path (`from Scweet.scweet import Scweet`), resume is forced to `legacy_csv` behavior for compatibility.

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

## Modern v4 usage (recommended)

### Example: API engine + SQLite + hybrid resume

```python
from Scweet import Scweet

scweet = Scweet(
    engine="api",
    db_path="scweet_state.db",
    accounts_file="accounts.txt",
    manifest_url="https://example.com/manifest.json",
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

### Example: browser engine + cookies file

```python
from Scweet import Scweet

scweet = Scweet(
    engine="browser",
    db_path="scweet_state.db",
    cookies_file="cookies.json",
    config={
        "resume": {"mode": "legacy_csv"},
    },
)

profiles = scweet.get_user_information(handles=["x_born_to_die_x"], login=True)
```

## Backward-compatible usage example

```python
from Scweet.scweet import Scweet

# Deprecated import path, still supported in v4.x.
scweet = Scweet(
    env_path=".env",
    n_splits=5,
    concurrency=5,
    headless=True,
)

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
