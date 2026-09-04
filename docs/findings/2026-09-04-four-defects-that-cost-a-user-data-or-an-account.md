# Four defects that cost a user data or an account

> This document uses ASD-STE100 Simplified Technical English.

Date: 2026-09-04. Status: measured. Each item below is reproduced in this repository, with the command.

## 1. A routine message from X blocks an account for 30 days

`api_engine.py:2123` tests `"auth" in message`. The word `author` contains `auth`.

```python
>>> from Scweet.api_engine import ApiEngine
>>> f = ApiEngine._map_graphql_errors_to_status
>>> f([{"message": "Tweet author restricted who can reply"}])
401
>>> f([{"message": "author you blocked"}])
401
>>> f([{"message": "Tweet.author_id is unavailable"}])
401
```

`cooldown.py` then reads that 401:

```python
if status_code in (401, 403):
    return int(status_code), now_ts + auth_cooldown_s, "auth_failed"
```

and `auth_cooldown_s` defaults to `30 * 24 * 60 * 60`, which is **30 days**.

So a message about one tweet in one page removes an account from the pool for a month. X sends messages of this
shape for a normal restricted reply, which is a common condition and not an error. A user who buys accounts pays
for this.

**No test covers `_map_graphql_errors_to_status`.**

The correction is to match a whole word and to require the evidence of a real authentication failure. A 401 from
a self-lookup for the account itself is reliable. A message inside a page of tweets is not.

## 2. The first empty page ends an interval

`config.py:34` sets `max_empty_pages` to 1. X sends an empty page in the middle of a chain while results remain,
so one gap ends the interval and the run reports success.

`runner.py` then logs `"Search done (no more results)"`, which is false: the stop came from our threshold and not
from X.

An independent measurement on one fixed corpus gave **500 tweets at the default and 16,100 at
`max_empty_pages=5`**, a factor of 32.

**A separate measurement shows the default is not the whole story.** A real order of 20,000 tweets with
`max_empty_pages=3` delivered 4,760, then 0, then 4,700 on 2026-09-04. So a value above 1 helps and it does not
by itself fill a large order. Read
`docs/findings/2026-09-04-a-large-order-fills-about-a-quarter.md`.

The precedence is correct through the documented path: `client.py:396` reads
`max_empty_pages or self._config.max_empty_pages`. A caller who builds a `Runner` directly gets the default of
`SearchRequest` instead, because `runner.py` reads the value of the request.

## 3. A limit is not a boundary, and a test says so

`runner.py` appends a complete page and tests the limit after. There is no slice, and `client.py` returns the
list without trimming. The overshoot is therefore up to `concurrency * page_size`.

Measured on 2026-09-04: a limit of 2,000 with a page size of 100 returned **2,400**, and with a page size of 20
returned **2,080**. A live run against X returned 2,340 for a limit of 2,000.

The behaviour is deliberate. `tests/test_runner.py` holds:

```
def test_runner_treats_limit_as_stop_signal_and_keeps_overshoot_from_last_page():
```

and it asserts 120 items for a limit of 100.

A library may choose that. But a caller who pays for each item, or who writes into a table with a fixed size,
needs `len(result) <= limit`. The honest fix is to trim before the return and to keep the current behaviour
behind an explicit option.

## 4. A failure is swallowed, then the log says it succeeded

`runner.py:479`:

```python
try:
    self.accounts_repo.upsert_account(normalized)
except Exception:
    pass
logger.info("Account repair succeeded via auth_token username=%s", ...)
return True
```

The write can fail and the next line reports success, and the function returns `True`. An operator who reads the
log believes the pool holds a repaired account.

An AST walk of the package counts **32 handlers that only `pass`**. Each one converts a fault into a wrong
result. The one above is the worst, because it also prints a false success.

## What these four have in common

Each one makes the library return less data, or fewer accounts, **without telling the caller**. A silent loss
does not become an issue report, so each of these can persist through many releases.

So the first correction is not a feature. It is to make each loss visible:

1. match a whole word before a 30-day block, and require real evidence
2. raise the default for `max_empty_pages`, and stop logging "no more results" when our own threshold stopped it
3. trim to the limit, and say when a page was cut
4. log a failure as a failure

## Two smaller faults, both confirmed

**`enable_wal` and `busy_timeout_ms` are dead fields.** `config.py:39` and `config.py:40` declare them, and a
search of the package finds no other file that reads either one. `storage.py:32` writes
`PRAGMA journal_mode=WAL` and `PRAGMA busy_timeout=5000` directly. So a user who sets `enable_wal=False` changes
nothing, and the library gives no warning. Either read the fields or remove them.

**The README contradicts the shipped default.** `README.md:258` and `README.md:298` both say that one account
"typically handles hundreds to a few thousand tweets per day". `config.py:33` sets `daily_tweets_limit` to 600.
So the library stops at 600 while the document promises up to a few thousand. A user reads the document, asks
for 2,000, receives 600, and has no way to know that a default of ours stopped it.

## What is not verified

The atomicity of a lease in `repos.py` is a reading of the code and not a measurement. Nobody ran two processes
against one database. Do not act on it before somebody does.
