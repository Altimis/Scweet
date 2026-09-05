from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import uuid


_TS_FMT = "%Y-%m-%d_%H:%M:%S_UTC"
# X returns a tweet time as "Wed Jan 02 19:47:19 +0000 2008".
_TWITTER_TS_FMT = "%a %b %d %H:%M:%S %z %Y"


def parse_tweet_time(ts: Any) -> Optional[datetime]:
    """Parse the time of a tweet into a naive UTC datetime, or None.

    It accepts the format that X returns, an ISO string, and an epoch. The result is naive UTC so it compares
    with the interval bounds, which are naive UTC.
    """
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).replace(tzinfo=None)
        except Exception:
            return None
    text = str(ts).strip()
    if not text:
        return None
    try:
        dt = datetime.strptime(text, _TWITTER_TS_FMT)
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc).replace(tzinfo=None) if dt.tzinfo else dt
    except Exception:
        return None


def narrow_interval(
    since: str,
    until: str,
    oldest_seen: Any,
    min_interval_seconds: int,
) -> list[tuple[str, str]]:
    """Continue an interval from the oldest tweet it returned, instead of halving it.

    A cursor chain returns tweets newest first and truncates near the newest end, so the tweets it missed are
    older than the oldest one it returned. Re-querying `[since, oldest]` fetches only those, with almost no
    overlap, where a half re-fetches the whole newer part. Returns `[(since, boundary)]` when the boundary sits
    inside the interval and leaves a span above the floor, else an empty list so the caller falls back to a
    half.
    """
    dt = parse_tweet_time(oldest_seen)
    if dt is None:
        return []
    try:
        since_dt = datetime.strptime(since, _TS_FMT)
        until_dt = datetime.strptime(until, _TS_FMT)
    except Exception:
        return []
    floor = max(1, int(min_interval_seconds))
    if not (since_dt < dt < until_dt):
        return []
    if (dt - since_dt).total_seconds() < floor:
        return []
    return [(since, dt.strftime(_TS_FMT))]


def split_time_intervals(
    since: str,
    until: str,
    n_intervals: int,
    min_interval_seconds: int,
) -> list[tuple[str, str]]:
    """Split [since, until] into bounded intervals of at least `min_interval_seconds`."""
    since_dt = datetime.strptime(since, _TS_FMT)
    until_dt = datetime.strptime(until, _TS_FMT)
    total_seconds = (until_dt - since_dt).total_seconds()

    if total_seconds <= 0:
        return [(since, until)]

    intervals_count = max(1, int(n_intervals))
    min_interval_seconds = max(1, int(min_interval_seconds))
    max_intervals_allowed = max(1, int(total_seconds // min_interval_seconds))
    intervals_count = min(intervals_count, max_intervals_allowed)

    interval_seconds = total_seconds / intervals_count
    intervals: list[tuple[str, str]] = []
    for idx in range(intervals_count):
        start_dt = since_dt + timedelta(seconds=idx * interval_seconds)
        if idx == intervals_count - 1:
            end_dt = until_dt
        else:
            end_dt = since_dt + timedelta(seconds=(idx + 1) * interval_seconds)
        intervals.append((start_dt.strftime(_TS_FMT), end_dt.strftime(_TS_FMT)))
    return intervals


def subdivide_interval(
    since: str,
    until: str,
    min_interval_seconds: int,
) -> list[tuple[str, str]]:
    """Split one interval into two halves.

    A cursor chain of X stops at a depth limit while tweets remain in the time range. To reach the rest, the
    range must be narrower, so the caller re-queries each half. Returns two halves, or an empty list when a half
    would fall below `min_interval_seconds`, which stops the division from running for ever.
    """
    since_dt = datetime.strptime(since, _TS_FMT)
    until_dt = datetime.strptime(until, _TS_FMT)
    total_seconds = (until_dt - since_dt).total_seconds()
    floor = max(1, int(min_interval_seconds))
    if total_seconds <= floor * 2:
        return []
    mid_dt = since_dt + timedelta(seconds=total_seconds / 2)
    mid = mid_dt.strftime(_TS_FMT)
    return [(since, mid), (mid, until)]


def build_tasks_for_intervals(
    base_query: dict[str, Any],
    run_id: str,
    priority: int,
    intervals: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Build queue-ready task documents for each interval."""
    tasks: list[dict[str, Any]] = []
    for since, until in intervals:
        tasks.append(
            {
                "task_id": str(uuid.uuid4()),
                "run_id": run_id,
                "priority": int(priority),
                "query": {
                    "raw": dict(base_query or {}),
                    "since": since,
                    "until": until,
                    "cursor": None,
                },
                "stats": {"pages": 0, "tweets": 0},
            }
        )
    return tasks
