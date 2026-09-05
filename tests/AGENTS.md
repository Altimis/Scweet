The tests for the package. 22 files and about 275 tests. They pass in about 12 seconds.

> This document uses ASD-STE100 Simplified Technical English.

## Levels

A pytest marker selects the level. `tests/conftest.py` declares one marker:

| Marker | What the test can use | Does CI run it? |
|---|---|---|
| *(none)* | logic only. No network and no real account. | yes |
| `integration` | real accounts of X and real requests | **no** |

```bash
pytest tests/ -q                                       # every test
pytest tests/ -q --ignore=tests/test_integration.py    # exactly what CI runs
pytest tests/test_runner.py -q                         # one file
```

`conftest.py` adds the repository root to `sys.path`, so a test runs without an install.

## Rules

- **A change is complete when a test fails without it.** Prove that a new guard is necessary: remove the guard
  and confirm that the test fails.
- **Never invent the shape of a response from X.** A fixture that is more simple than the real data gives a
  false result, because the work of the parser is to accept what X actually sends.
- **A test that needs a real account carries the `integration` marker.** X permits about 50 search requests for
  each account in each 15 minutes. Count the requests in a test. A careless test leaves the account of the
  contributor rate-limited.
- **Never put a real credential in a test or in a fixture.** No `auth_token`, no cookie, no password.
- The name of a test describes the behaviour. The docstring states the failure mode in plain words. Do not put
  the number of an issue in a name.

## The gaps that matter. Read these before you add a test

These are measured facts about this suite, not opinions.

1. **No test asserts that a run across several intervals collects what it asked for.** This is the gap that let
   a real defect reach a release. Measured on 2026-09-04: an order of 20,000 tweets over three months delivered
   4,760, then 0, then 4,700, a median fill of 23.5%. Every one of the 254 tests passed while that was true. A
   test that plans several intervals with a fake page source, and asserts the total, would have caught it.
2. **No test covers the continuation of a cursor across an interval boundary.** `should_continue_with_cursor` in
   `runner.py` decides how far a run reaches, and nothing pins its behaviour.
3. **No test asserts that a limit is a boundary.** Measured on 2026-09-04: a limit of 2,000 returned 2,340,
   which is 17% above. A test that asks for N and asserts `len(result) <= N` would have caught it.
4. **There is no fixture directory and no captured response from X.** `tests/test_api_engine.py` holds 784 lines
   and no mock, so it builds its data inline. A real captured page belongs in a file, so a reader can see what X
   sends.
5. **`tests/test_integration.py` never runs in CI.** The workflow passes
   `--ignore=tests/test_integration.py`. So the only tests that touch a real account run when a person
   remembers. State in a pull request whether you ran them.

## Where a silent defect costs a user most

1. how far a run reaches, in `runner.py` and `scheduler.py`
2. whether a limit binds, in `runner.py`
3. the health of an account and the length of a cooldown, in `repos.py` and `cooldown.py`
4. the parse of a page, in `api_engine.py`, because an empty parse looks the same as the end of the data

## Capturing a log in a test

Do not use `caplog` for a Scweet log. `Scweet/logging_config.py` sets `propagate = False` on the `Scweet`
logger, and `caplog` attaches to the root logger, so it captures nothing once logging is configured. A test that
uses `caplog` passes on a fresh process and fails in CI. Attach a handler to the named logger instead. Read the
`runner_logs` fixture in `tests/test_swallowed_failures.py`.
