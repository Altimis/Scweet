# A large order fills about a quarter, and the user gets no message

> This document uses ASD-STE100 Simplified Technical English.

Date: 2026-09-04. Status: measured, not yet corrected.

## The measurement

Three runs, one query, 25 accounts, one residential proxy:

```
query      bitcoin OR ethereum OR crypto
sort       Latest
period     2026-06-01 to 2026-09-01
limit      20000
```

| Run | Delivered | Fill | Seconds |
|---:|---:|---:|---:|
| 1 | 4,760 | 23.8% | 27 |
| 2 | **0** | 0.0% | 0 |
| 3 | 4,700 | 23.5% | 20 |

Run 2 ended with `AccountPoolExhausted: No eligible accounts (total=25, cooldown=25)`.

A comparable engine that divides an interval further delivered **20,000 three times of three** on the same
query, with the same 25 accounts and the same proxy, in 353, 436 and 357 seconds. So the data exists in the
period and X returns it. The limit is in this library.

A smaller order works. A limit of 2,000 over one month returned 2,340 in 21 seconds, so the fault appears
between 2,000 and 20,000.

## The mechanism

`scheduler.split_time_intervals` divides the period one time, into `n_splits` intervals, before the first
request. A worker then follows one chain of pages for each interval:

```python
# runner.py, in the worker loop
should_continue_with_cursor = (
    not stop_due_to_empty_pages
    and bool((response or {}).get("continue_with_cursor"))
    and bool(next_cursor)
)
```

and `continue_with_cursor` is `bool(cursor)` in `api_engine.py`. So a worker continues while X sends a cursor and
it stops when X does not. **No interval is ever divided again.** When the chain for an interval ends before that
interval is exhausted, the tweets that remain in the period are never requested.

An engine that fills the order divides instead. In one measured run, 153 of 194 intervals ended on a cap of 6
pages and **each one queued a continuation**, so the work divided about 194 times where this library used 40
intervals.

## Two separate faults, and the second is easier

1. **The plan does not divide.** This needs a change in `runner.py` and `scheduler.py`, and it needs a test that
   asserts the total across several intervals.
2. **`AccountPoolExhausted` ends the run instead of waiting.** Every account held a cooldown at that moment, and
   a cooldown expires. A bounded wait would have finished the run. This is a smaller change and it removes the
   0% case.

## Why nobody reported it

The run reports success. It returns 4,760 tweets and raises nothing, so a user believes that X holds 4,760
tweets for their query. A user cannot report a fault that they cannot see, so this one produced no issue report.

## What to measure after a correction

Repeat the three runs above. The target is 90% fill or more in 9 of 10 runs, and no run that ends with
`AccountPoolExhausted` while a cooldown is shorter than the time that remains.

Also assert the boundary: a limit of 2,000 must return 2,000 or fewer, and it returned 2,340.
