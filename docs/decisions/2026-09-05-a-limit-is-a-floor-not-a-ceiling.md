# A limit is a floor, not a ceiling

> This document uses ASD-STE100 Simplified Technical English.

Date: 2026-09-05. Status: active.

## Context

`search(limit=N)` can return a few more than `N` tweets. A complete page is appended and the limit is tested
after, so the result overshoots by up to `concurrency * page_size`. Measured on 2026-09-04: a limit of 2,000
with a page size of 100 returned 2,400.

An earlier note listed this as a defect and proposed to trim the result to the limit.

## Decision

Keep the overshoot. `limit` is the smallest number of tweets to collect, not the largest. A caller who asks for
2,000 and receives 2,340 keeps the extra 340.

## Why

The user owns the data. The library scrapes with the user's own accounts and proxies, and the tweets belong to
the user. Nothing bills per tweet, so an extra tweet costs the user nothing and it may be useful. To throw away a
tweet that the library already fetched and parsed is waste.

This differs from a hosted service that bills for each item. There, a limit must bind, because an overshoot is a
charge the customer did not ask for. The library has no such constraint.

## What this means for the code

- `search` and `get_profile_tweets` return at least `limit` tweets when the query holds that many, and they may
  return a few more.
- Do not add a trim. The test `test_runner_treats_limit_as_stop_signal_and_keeps_overshoot_from_last_page` pins
  this behaviour. Keep it.
- Document `limit` as "the minimum number of tweets to collect" so a user is not surprised.

## Examine again if

The library grows a mode that bills per item, or a user reports that an exact count is a hard requirement for
their use.
