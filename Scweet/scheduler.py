from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import uuid


_TS_FMT = "%Y-%m-%d_%H:%M:%S_UTC"


def split_time_intervals(
    since: str,
    until: str,
    n_intervals: int,
    min_interval_seconds: int,
) -> list[tuple[str, str]]:
    """Split [since, until] into bounded intervals using actor-style semantics."""
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
