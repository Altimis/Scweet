# The path to a production ready library

> This document uses ASD-STE100 Simplified Technical English.

Date: 2026-09-04. Status: a plan. No item here is done.

## Where the library stands

The library works for a small order and it loses data on a large one, and it does not say so. Two measurements
set the work below.

**An order of 20,000 tweets over three months fills about 23.5%.** Measured on 2026-09-04. All 254 tests pass
while that is true. Read `docs/findings/2026-09-04-a-large-order-fills-about-a-quarter.md`.

**Six defects each return less data, or fewer accounts, without a message.** Read
`docs/findings/2026-09-04-four-defects-that-cost-a-user-data-or-an-account.md`. Every item is reproduced with the
command that shows it.

A fault that is silent stays open, because a user who cannot see a loss cannot report it. That is the reason for
the order below, and it is the reason that the first phase adds no feature and changes no default.

Therefore the order of the work is: first make a loss visible, then stop the loss, then improve the package.
A feature added before this order is complete makes the library larger and not better.

## Phase 0: release what is already written

`Scweet/__version__.py` holds `5.3.1`. `CHANGELOG.md` documents 5.3.1 with the date 2026-05-19. PyPI serves
**5.3 from 2026-04-14**, and no tag `v5.3.1` exists. So a correction that was written 3.5 months ago reaches no
user.

The correction in `b868fee` replaces the upstream function `get_ondemand_file_url` with
`_extract_ondemand_url` in `Scweet/transaction.py`. Measured on 2026-09-04: the upstream function works today,
and both functions return the same URL for the live login page of X. **So 5.3 is not broken.** The value of the
release is that the local extraction survives a change in the format of the manifest of X, and the upstream
version did not. Ship it as an improvement, not as an emergency.

- [ ] tag `v5.3.1` and publish to PyPI
- [ ] state in `CHANGELOG.md` that the two extractions agree today

## Phase 1: make each silent loss visible

This phase changes no default. It adds a message. A user must learn what the library did not return.

- [ ] **A stop that comes from a threshold says so.** `runner.py` logs `"Search done (no more results)"` when
      `max_empty_pages` stops an interval. That sentence describes X, and the cause is our own threshold. Log
      the cause and the value of the parameter.
- [ ] **A run reports the fill.** When a caller asks for N and the run returns fewer, say the number and the
      reason. A user who asks for 20,000 and receives 4,760 must not believe that X holds 4,760.
- [ ] **A page that is cut says so.** See Phase 3.
- [x] **A failure logs as a failure.** Done 2026-09-05. `_attempt_account_repair` swallowed a failed
      `upsert_account`, then logged `"Account repair succeeded"` and returned `True`. It now returns `False` and
      logs a warning, and the swallowed `release` in `api_engine.py` logs a warning too. The count of bare
      `except: pass` handlers is 30. `tests/test_swallowed_failures.py` holds 5 tests; a mutation fails 3.

A test for each item asserts the message. Read `tests/AGENTS.md` for the gaps in the suite.

## Phase 2: stop the losses that cost an account

- [x] **Match a whole word before a 30-day block.** Done 2026-09-04. `api_engine.py` tested `"auth" in message`,
      and the word `author` contains `auth`, so `"Tweet author restricted who can reply"` mapped to 401 and
      `cooldown.py` gave the account 30 days. `AUTH_FAILURE_MESSAGES` now holds a phrase only when X sends it for
      the whole session, and `AUTH_FAILURE_CODES` holds the codes 32 and 89 from captured answers of X. The same
      work corrected the opposite fault: the real message of a dead session mapped to nothing.
      `tests/test_graphql_error_mapping.py` holds 21 tests, and 4 mutations each fail one.
- [x] **A run waits for a cooldown instead of ending.** Done 2026-09-05. `Runner._acquire_leases_with_wait`
      waits up to `pool_wait_max_s` (120s) and retries every `pool_wait_poll_s` (5s). `pool_wait_max_s=0` keeps
      the old immediate failure. `tests/test_pool_wait.py` holds 3 tests; a mutation that removes the wait fails 2.
- [x] **An account leaves the pool only on proven-dead evidence.** Done 2026-09-05 (moved from Phase 2). A page
      401/403 gives a short cooldown and triggers `ApiEngine.probe_account_alive`, a self-lookup of the account's
      own handle. Only a self-lookup that also fails gives the 30-day block. The per-endpoint status columns were
      dropped: the long block now depends on the shared credentials, so nothing per-endpoint remains to track.
      `tests/test_proven_dead_evidence.py` and `tests/test_cooldown.py` cover it; 3 mutations each fail a test.

## Phase 3: correctness of the public contract

- [ ] **Raise the default of `max_empty_pages`.** `config.py:34` sets 1, so the first gap in a chain ends an
      interval. A measurement on one fixed corpus gave 500 tweets at the default and 16,100 at 5. Choose the new
      default from a measurement and record the number.
- [ ] **Divide an interval that still holds tweets.** `split_time_intervals` runs one time, before the first
      request, and no interval is divided again. This is the cause of the fill of 23.5%, and it is the largest
      change in this plan. It needs a test that plans several intervals against a fake page source and asserts
      the total.
- [ ] **Make a limit a boundary.** Measured: a limit of 2,000 returns 2,340, which is 17% above. The current
      behaviour is deliberate, because `tests/test_runner.py` asserts 120 items for a limit of 100. Trim before
      the return, say when a page was cut, and keep the old behaviour behind an explicit option. A caller who
      bills for each item needs `len(result) <= limit`.
- [ ] **Read the dead fields or remove them.** `enable_wal` and `busy_timeout_ms` in `config.py` are read
      nowhere. `storage.py:32` sets both PRAGMA values directly. A user who changes either field changes
      nothing and receives no warning.
- [ ] **Align the README with the shipped default.** `README.md:258` and `README.md:298` promise "hundreds to a
      few thousand tweets per day" for one account. `config.py:33` stops at 600. Correct the number, or raise
      the default and give the measurement.

## Phase 4: the package

Each item below is verified absent on 2026-09-04.

- [ ] **`py.typed`.** The count in the repository is 0, so mypy and pyright see no type from Scweet, whatever
      the annotations say.
- [ ] **Move metadata to PEP 621.** `pyproject.toml` holds only the build system and pytest. `setup.py` holds
      the metadata.
- [ ] **Extend the matrix past 3.12.** CI runs 3.9 to 3.12.
- [ ] **Automate the release.** `.github/workflows/` holds `tests.yml` only. Add a workflow that a tag starts,
      that fails when the tag and the version disagree, that fails when `CHANGELOG.md` holds no entry for the
      tag, and that publishes with a trusted publisher. The stranded 5.3.1 is the reason this matters.
- [ ] **`SECURITY.md` and `.github/dependabot.yml`.** Both are absent.
- [ ] **Do not build a documentation site yet.** A README that a reader finishes beats a site that nobody
      opens. A site is a later choice and not a correction.

## What this plan does not include

- **A hosted backend inside the library.** A survey of 10 comparable Python libraries found 0 that ship one,
  and a search of the issues of this repository found 0 requests for one. A control search for "proxy" and
  "docker" returned results, so the absence is real. A user supplies their own accounts and their own proxies,
  and that is the design.
- **A twelfth argument for `Scweet.__init__`.** The constructor already carries 11.
- **A change to the atomicity of a lease in `repos.py`.** That concern comes from a reading of the code and not
  from a measurement. Nobody ran two processes against one database. Measure it first.

## How to know that the plan worked

Repeat the measurement in `docs/findings/2026-09-04-a-large-order-fills-about-a-quarter.md`: an order of 20,000
tweets over three months. The target is a fill of 90% or more in 9 runs of 10, with no run that ends with
`AccountPoolExhausted` while a cooldown is shorter than the time that remains. Also assert that a limit of 2,000
returns 2,000 or fewer.
