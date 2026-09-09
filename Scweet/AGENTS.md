The importable package. Every module is flat here, with no sub-package. `pip install Scweet` installs this
directory.

> This document uses ASD-STE100 Simplified Technical English.

## The modules, by weight

| Module | Lines | Function |
|---|---:|---|
| `api_engine.py` | 2,736 | It builds each GraphQL request, sends it, and parses the answer. The largest and the most fragile file, because X changes its answers. |
| `runner.py` | 1,568 | It plans the intervals, starts the workers, leases the accounts, and decides when a task continues or stops. |
| `auth.py` | 927 | It turns credentials into a session. It reads an accounts file, and it repairs a token. |
| `repos.py` | 821 | The lease of an account in SQLite, the heartbeat, the release, and the cooldown. |
| `client.py` | 816 | The public class `Scweet`. Every method that a user calls lives here. |
| `db.py` | 662 | The schema of SQLite and the connection. |
| `manifest.py` | 471 | It reads the query IDs of X. An old query ID answers 404 for every request. |
| `query.py` | 404 | It joins the structured filters into one search string for X. |
| `cli.py` | 326 | The command line. `python -m Scweet`. |
| `config.py` | 139 | `ScweetConfig`. **Every parameter belongs here.** |
| `transaction.py` | 216 | It builds the `x-client-transaction-id` header. Without it X answers 404. |
| `limiter.py` | ~50 | The token bucket for each account. |
| `scheduler.py` | ~70 | It divides a period into intervals. |

## Invariants. A defect in one of these is silent

- **`scheduler.split_time_intervals` runs once, and an interval is divided again when a chain truncates.** A cursor chain of X stops at a depth limit while tweets remain. When a chain ends on a full page with no cursor, `runner.py` continues from the time of the oldest tweet it saw (`narrow_interval`), re-querying only the unfetched older part, and halves the interval (`subdivide_interval`) only when that time is not usable. Both are bounded by `scheduler_min_interval_s` and `max_interval_depth`, and the global set of seen ids drops any overlap.
- **`api_engine.py` parses the answer of X, and X changes it.** A parser that expects a field which X renames
  returns an empty page, and an empty page looks the same as the end of the results. Take every fixture from a
  real response.
- **`manifest.py` holds the query IDs, and a stale ID answers 404 for every account.** A 404 from every account
  therefore describes our configuration and not the accounts. Never retire an account from one 404 when the
  other endpoints also fail.
- **The bootstrap of the manifest and of the transaction id reads `https://x.com/home`.** Measured 2026-09-09:
  `https://x.com` answers about 33,000 bytes and holds no `main.js` reference and no `"ondemand.s"` marker,
  while `/home` answers about 297,000 bytes and holds both, with no cookie. `handle_x_migration` of
  `x_client_transaction` reads `https://x.com` itself, so `transaction.py` retries against `home_url` when the
  page of the migration holds no marker. A missing `x-client-transaction-id` header gives 404 with an empty
  body for every request.
- **A path that builds a session fills the `{session}` placeholder with
  `fill_proxy_session_placeholder`.** A literal placeholder is not a valid session name and the provider
  answers 407. Four paths need it: `account_session.py`, the check on lease in `runner.py`, `transaction.py`,
  and `bootstrap_cookies_from_auth_token` in `auth.py`.
- **A lease in `repos.py` is atomic and it must stay atomic.** It writes the lease and the timestamp in one
  statement. A read and then a write lets two workers take the same account.
- **A 401 or 403 from a page never gives the 30-day block on its own.** The worker confirms with
  `ApiEngine.probe_account_alive`, a self-lookup of the account's own handle. `compute_cooldown` gives the long
  block only when `proven_dead` is true, which means the self-lookup also failed. An unconfirmed 401 gives a
  short cooldown (`auth_unconfirmed`). A session that cannot be built is proven dead. See B1 in
  `docs/plans/2026-09-04-the-path-to-a-production-ready-library.md`.
- **The limiter paces to the window of X, not to the gap between requests.** `TokenBucketLimiter` holds
  `window_request_limit` (50) tokens and refills over `rate_limit_window_s` (900s), and it starts full. A short
  run bursts and waits nothing; a long run slows to the refill rate. `min_delay_s` (1.0) is only a floor between
  two requests of one account, so a burst does not arrive at wire speed. Do not pace evenly across the window: X
  counts the total in a window, and an even delay made a run of 400 tweets take 373 seconds instead of 41.
  `requests_per_min` is deprecated and the limiter ignores it.
- **A run waits for a cooldown before it fails.** `Runner._acquire_leases_with_wait` waits up to
  `pool_wait_max_s` and retries every `pool_wait_poll_s`. A cooldown expires, so a run with a small pool
  finishes instead of failing.
- **A cooldown that is too long removes an account that a user paid for.** `auth_cooldown_s` defaults to 30
  days. Apply that only when the credentials are proven dead, which means a self-lookup that answers 401 or 403.
  `_map_graphql_errors_to_status` decides this. It reads `AUTH_FAILURE_MESSAGES` and `AUTH_FAILURE_CODES`, and a
  phrase or a code there must describe the session and never one tweet. Measured 2026-09-04: code 89 is
  "Invalid or expired token" and code 32 is "Could not authenticate you".
- **`client.py` carries 11 constructor arguments already.** Narrow this surface. Do not add a twelfth.
- **There is no `py.typed` in this directory.** Every annotation in these files is invisible to mypy and to
  pyright in a consumer project.

## Conventions

- **A parameter belongs in `config.py`.** If you write a number in `runner.py` or `api_engine.py`, a user cannot
  change it and a reader cannot find it.
- **A module raises. It does not print and it does not exit.** `exceptions.py` holds the types. A caller
  decides.
- **An exception must not be swallowed, and a write that fails must not log success.** `_attempt_account_repair`
  in `runner.py` returns False and logs a warning when `upsert_account` fails, and a failed `release` in
  `api_engine.py` logs a warning, because it drops the account from the pool. 31 bare `except: pass` handlers
  remain; correct one when you touch its file. `except Exception: pass` converts a fault into a wrong result, and a
  wrong result reaches the user as missing data with no cause.
- **Never log a secret.** An `auth_token`, a cookie, a `ct0`, a password, and a 2FA secret each belong to a real
  account. Log a username and a status.
- **One term for one thing.** The code uses `account`, `lease`, `task`, `interval`, and `cursor`. Do not
  introduce a synonym.

## Where to change what

| To change | Edit |
|---|---|
| how far a run reaches | `runner.py` and `scheduler.py` |
| what a page contains | `api_engine.py` |
| a default | `config.py` only |
| the health of an account | `repos.py` and `cooldown.py` |
| the public surface | `client.py`. Narrow it, do not grow it |
| the search string | `query.py` |
