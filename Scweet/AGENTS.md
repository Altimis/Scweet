The importable package. Every module is flat here, with no sub-package. `pip install Scweet` installs this
directory.

> This document uses ASD-STE100 Simplified Technical English.

## The modules, by weight

| Module | Lines | Function |
|---|---:|---|
| `api_engine.py` | 2,648 | It builds each GraphQL request, sends it, and parses the answer. The largest and the most fragile file, because X changes its answers. |
| `runner.py` | 1,392 | It plans the intervals, starts the workers, leases the accounts, and decides when a task continues or stops. |
| `auth.py` | 927 | It turns credentials into a session. It reads an accounts file, and it repairs a token. |
| `repos.py` | 821 | The lease of an account in SQLite, the heartbeat, the release, and the cooldown. |
| `client.py` | 816 | The public class `Scweet`. Every method that a user calls lives here. |
| `db.py` | 662 | The schema of SQLite and the connection. |
| `manifest.py` | 471 | It reads the query IDs of X. An old query ID answers 404 for every request. |
| `query.py` | 404 | It joins the structured filters into one search string for X. |
| `cli.py` | 326 | The command line. `python -m Scweet`. |
| `config.py` | ~90 | `ScweetConfig`. **Every parameter belongs here.** |
| `limiter.py` | ~50 | The token bucket for each account. |
| `scheduler.py` | ~70 | It divides a period into intervals. |

## Invariants. A defect in one of these is silent

- **`scheduler.split_time_intervals` runs one time, before the first request.** It creates `n_splits` intervals
  and no interval is divided again. A worker follows one chain of pages for each interval, and it stops when X
  sends no cursor, because `should_continue_with_cursor` in `runner.py` reads `continue_with_cursor` from
  `api_engine.py`, which is `bool(cursor)`. **Measured 2026-09-04: an order of 20,000 tweets over three months
  delivered a median of 23.5%.** A user sees no message.
- **`api_engine.py` parses the answer of X, and X changes it.** A parser that expects a field which X renames
  returns an empty page, and an empty page looks the same as the end of the results. Take every fixture from a
  real response.
- **`manifest.py` holds the query IDs, and a stale ID answers 404 for every account.** A 404 from every account
  therefore describes our configuration and not the accounts. Never retire an account from one 404 when the
  other endpoints also fail.
- **A lease in `repos.py` is atomic and it must stay atomic.** It writes the lease and the timestamp in one
  statement. A read and then a write lets two workers take the same account.
- **A cooldown that is too long removes an account that a user paid for.** `auth_cooldown_s` defaults to 30
  days. Apply that only when the credentials are proven dead, which means a self-lookup that answers 401 or 403.
  `_map_graphql_errors_to_status` decides this. It reads `AUTH_FAILURE_MESSAGES` and `AUTH_FAILURE_CODES`, and a
  phrase or a code there must describe the session and never one tweet. Measured 2026-09-04: code 89 is
  "Invalid or expired token" and code 32 is "Could not authenticate you".
- **`limiter.py` paces requests evenly.** `refill_rate = requests_per_min / 60` and `min_delay_s` defaults to
  2.0. X counts the total inside a window of 15 minutes, so an even pace makes a short run slow and it protects
  nothing. Measured on a comparable engine: an even pace made a run of 400 tweets take 373 seconds in place of
  41 seconds.
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
  `api_engine.py` logs a warning, because it drops the account from the pool. 30 bare `except: pass` handlers
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
