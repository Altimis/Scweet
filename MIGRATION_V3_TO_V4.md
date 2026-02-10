# Migration guide: v3 -> v4

This guide explains what changed in Scweet v4, what stayed compatible, and how to migrate incrementally without breaking existing scripts.

## 1) What changed internally

Scweet v4 keeps the public facade but moves runtime internals to a new core.

- New internal core in `Scweet/v4/`.
- Async runner and in-memory task queue for orchestration.
- Account pooling and lifecycle state in SQLite.
- Resume checkpoints stored in SQLite (`resume_state`).
- API-only scraping core with manifest-backed behavior.

These are internal improvements. Most v3 user code can continue running unchanged.

## 2) What stayed compatible

The compatibility contract in v4.x keeps:

- Legacy class path still importable:
  - `from Scweet.scweet import Scweet`
- Preferred class path available:
  - `from Scweet import Scweet`
- Legacy method signatures preserved for:
  - `scrape` / `ascrape`
  - `get_user_information` / `aget_user_information`
  - `get_follows`, `get_followers`, `get_following`, `get_verified_followers`
  - async follow variants
- Legacy CSV filename behavior preserved (same naming logic via `save_dir` / `custom_csv_name`).

Output changes in v4 (breaking vs v3):

- `scrape` / `ascrape` now returns a `list[dict]` of raw tweet objects from the GraphQL response (`tweet_results.result`).
- CSV output is now a curated "important fields" schema (stable header) derived from those raw GraphQL tweet objects.
  - For full coverage, use JSON output (`config.output.format="json"` or `"both"`) or the returned `list[dict]`.

## 3) Deprecated in v4.x (planned removal in v5.0)

### Imports

- Deprecated: `from Scweet.scweet import Scweet`
- Replacement: `from Scweet import Scweet`

### Constructor args

- Deprecated: `n_splits`
  - Replacement: `config.pool.n_splits`
- Deprecated: `concurrency`
  - Replacement: `config.pool.concurrency`

All deprecated items still work in v4.x but emit `FutureWarning`.

## 4) Old API -> recommended v4 usage mapping

### Import path

```python
# Old (still supported in v4.x)
from Scweet.scweet import Scweet

# Recommended
from Scweet import Scweet
```

### Initialization

```python
# Legacy style (still supported)
scweet = Scweet(env_path=".env", n_splits=5, concurrency=5)

# Recommended v4 style
scweet = Scweet(
    db_path="scweet_state.db",
    accounts_file="accounts.txt",
    manifest_url="https://example.com/manifest.json",
    config={
        "pool": {"n_splits": 8, "concurrency": 4},
        "resume": {"mode": "hybrid_safe"},
    },
)
```

### Scrape call

No breaking signature changes were introduced for `scrape(...)` / `ascrape(...)`.

Return shape change:

- v3 returned a legacy-shaped mapping/dict with selected fields (historically aligned with browser/HTML extraction).
- v4 returns a list of raw GraphQL tweet dicts to preserve all fields.

## 5) Resume behavior migration notes

v4 introduces mode-based resume behavior:

- `legacy_csv`: parse existing CSV and override `since` from max timestamp (v3-style behavior).
- `db_cursor`: resume from SQLite checkpoint (`since` + `cursor`) only.
- `hybrid_safe`: use DB checkpoint first, fallback to CSV behavior.

Important behavior difference by import path:

- Legacy facade import (`Scweet.scweet`) always forces `legacy_csv` for compatibility.
- Preferred import (`Scweet`) uses configured `config.resume.mode` (default is hybrid-safe behavior).

If you are migrating from v3 and want identical resume semantics, keep legacy import or set:

```python
config={"resume": {"mode": "legacy_csv"}}
```

## 6) Account loading migration notes

v4 uses DB-first provisioning: account sources are imported into SQLite and the DB state is reused across runs.

### `.env` (legacy single-account)

`env_path=".env"` remains supported as a deterministic account provisioning source.

### `accounts.txt`

Use one line per account:

```text
username:password:email:email_password:2fa:auth_token
```

- Blank lines and `#` comments are ignored.
- Missing trailing fields are accepted.

### `cookies.json`

Accepted input forms:

- List of account objects.
- Object with `accounts: [...]`.
- Single account object.
- Mapping-like object where keys are usernames and values are cookie/account payloads.

## 7) Troubleshooting

### Warning: legacy import path

Symptom:

- `FutureWarning` mentioning `Scweet.scweet`.

Meaning:

- Your code is using the deprecated import path.

Action:

- Switch to `from Scweet import Scweet`.

### Warning: deprecated constructor args

Symptom:

- `FutureWarning` mentioning `mode`, `n_splits`, or `concurrency`.

Action:

- Move those settings to `engine` / `config.pool`.

### Accounts appear not to load

Checks:

- Confirm file path for `accounts_file` or `cookies_file`.
- Confirm JSON is valid for `cookies.json`.
- Confirm each account can derive a username or provides one explicitly.

### Resume confusion between CSV and DB cursor

Symptom:

- Resume starts from CSV date when DB checkpoint exists (or vice versa).

Checks:

- Verify import path:
  - `Scweet.scweet` forces `legacy_csv`.
  - `Scweet` honors configured `config.resume.mode`.
- Verify `resume=True` is enabled on scrape call.

### DB checkpoint ignored

Symptom:

- `db_cursor` or `hybrid_safe` did not use checkpoint.

Likely causes:

- Missing or malformed checkpoint (`since` absent/invalid).
- Query hash mismatch (different request inputs).

Behavior:

- Resume logic is fail-safe and falls back to requested `since` (and CSV fallback in hybrid mode).

## 8) Migration checklist

1. Change import to `from Scweet import Scweet`.
2. Move deprecated constructor args to modern config fields.
3. Decide resume mode explicitly (`legacy_csv`, `db_cursor`, or `hybrid_safe`).
4. Validate account source files (`accounts.txt` or `cookies.json`).
5. Run existing scrape flows and confirm warnings are resolved.
