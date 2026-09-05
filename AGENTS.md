Scweet is an MIT Python library. It reads tweets from X/Twitter through the private GraphQL API of X, the same
interface that the website uses. A user supplies their own X accounts and their own proxies. The state of the
accounts lives in SQLite.

> This document uses ASD-STE100 Simplified Technical English. All documents in this repository use it.

A user runs this library against their own accounts. A defect that loses data therefore costs them the data and
the time of the accounts, and a defect that blocks an account costs them money. Correctness and an honest message
come before a feature.

## Map

- `Scweet/` — the importable package. Every module is flat inside it, with no sub-package.
- `tests/` — 21 files and about 254 tests. A pytest marker selects the level.
- `examples/` — short scripts that a reader can run.
- `docs/` — the engineering documents. Read `docs/AGENTS.md`.
- `.github/workflows/tests.yml` — the only gate. It runs the unit tests on Python 3.9 to 3.12.

## The shape of a request

```
Scweet.search()            the public method, in client.py
  Runner.run_search()      runner.py. It plans, then it starts the workers
    split_time_intervals()  scheduler.py. It divides the period into n_splits intervals
    queue.enqueue()         queue.py. One task for each interval
    acquire_leases()        repos.py. One account for each worker, from SQLite
      ApiEngine.search_tweets()   api_engine.py. One page for each request
```

## Invariants. A defect in one of these is silent

- **An interval is planned one time and it is never divided again.** `split_time_intervals` creates `n_splits`
  intervals before the run starts. A worker then follows one chain of pages for each interval and it stops when
  X sends no cursor: `should_continue_with_cursor` in `runner.py` reads `continue_with_cursor`, which is
  `bool(cursor)` in `api_engine.py`. **Measured on 2026-09-04: an order of 20,000 tweets over three months
  delivered 4,760, then 0, then 4,700, which is a median fill of 23.5%.** A user receives a quarter of the data
  that they asked for and no message that explains it.
- **A limit is a target and not a boundary.** Measured on 2026-09-04: a limit of 2,000 returned 2,340, which is
  17% above. Any code that bills for each item must not depend on the limit.
- **A run waits a bounded time for a cooldown before it fails.** When every account holds a cooldown, the run
  waits up to `pool_wait_max_s` (120s) and retries every `pool_wait_poll_s` (5s), because a cooldown expires.
  It ends with `AccountPoolExhausted` only after the wait. Set `pool_wait_max_s` to 0 to fail at once.
- **The default daily caps are small.** `daily_requests_limit` is 30 and `daily_tweets_limit` is 600. One
  account therefore delivers 600 tweets in a day with the defaults. A user who asks for more receives less and
  the cause is a default, not X.
- **The limiter paces each request evenly.** `TokenBucketLimiter` sets `refill_rate = requests_per_min / 60`
  and `min_delay_s` defaults to 2.0. X counts the total inside a window of 15 minutes and not the gap between
  two requests, so an even pace makes a short run slow with no benefit.
- **X permits about 50 search requests for each account in each 15 minutes.** Measured on 2026-08-31:
  the header `x-rate-limit-limit` was 50 and request 51 answered 429. Give a measurement if you change a rate.
- **An account costs money and a user cannot replace one quickly.** Any code that gives an account a long
  cooldown must first separate a dead account from a bad request. When the cause is unknown, apply a short
  cooldown.
- **A phrase in `AUTH_FAILURE_MESSAGES` describes the session and never one tweet.** `api_engine.py` tested the
  substring `"auth"`, and the word `author` contains it, so `"Tweet author restricted who can reply"` mapped to
  401 and `cooldown.py` removed the account for 30 days. For the same reason the list holds no `"not authorized"`
  and no `"authorization: denied"`: X sends both for one tweet of a protected account. A code in
  `AUTH_FAILURE_CODES` needs a captured answer of X. The set holds 32 and 89 only.
- **The package ships no `py.typed`.** Therefore mypy and pyright see no type from Scweet, whatever the
  annotations in the source say.

## Commands

```bash
pip install -e .
pytest tests/ -q                              # every test
pytest tests/ -q --ignore=tests/test_integration.py    # what CI runs
pytest tests/test_runner.py -q                # one file
python -m Scweet --help                       # the CLI
```

## Conventions

- **All configuration is in `Scweet/config.py`, in one `ScweetConfig` class.** Each field is flat and it holds
  a default. Do not put a fixed parameter value in `runner.py` or `api_engine.py`.
- **Do not add an argument to `Scweet.__init__`.** The constructor already carries 11. The plan is to narrow
  this surface and not to grow it.
- **A public method returns data. It does not print and it does not exit.** A caller decides what to do with an
  error.
- **An error message names a cause and an action.** "No eligible accounts" tells a user nothing they can act
  on. "Every account is on a cooldown for N seconds. Add an account, or wait." does.
- **Never write a secret to a log or to an output file.** An `auth_token`, a cookie, a password, and a 2FA
  secret each identify a real account of a real person.
- **A default must be safe for a first run and honest about its cost.** A default that silently returns 600
  tweets is worse than a default that returns an error which explains the cap.

## Testing

A change is complete when a test fails without it.

- Prove a new guard is necessary: remove the guard and confirm that the test fails.
- **Never invent the shape of a response from X.** Take a fixture from a real response. A fixture that is more
  simple than the real data gives a false result.
- `tests/test_integration.py` needs real accounts and CI skips it. A change to the engine must still run it
  locally.
- **The gap that matters:** no test asserts that a run across several intervals collects what it asked for. That
  is why the fill of 23.5% reached a released version.

## Git

- The subject of a commit is `<area>: <a sentence in lower case that describes the change in behaviour>`. The
  area is one of `engine`, `accounts`, `api`, `cli`, `docs`, `ci`, `deps`, or `packaging`.
- The subject states the new fact that a user sees. Write `engine: a run divides an interval that still holds
  tweets`. Do not write `fix pagination`.
- The body gives the reason: what was not possible before, what happens now, and each number that you measured.
- One commit for each change in behaviour, including its tests and its documents.
- `CHANGELOG.md` carries a line for each release that a user can act on.

## For agents

- Read the nearest `AGENTS.md` before you change the code in a directory.
- An `AGENTS.md` file describes only the current state. A reason belongs in `docs/decisions/`. The history is in
  git.
- A change to a public signature, a default, or a behaviour also updates the `AGENTS.md` files and
  `DOCUMENTATION.md` in the same commit.
- **Measure before you claim.** Run a command and give its output. A claim about the behaviour of X or about the
  speed of this library needs a number and a date.
