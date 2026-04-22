from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
import uuid


_TS_FMT = "%Y-%m-%d_%H:%M:%S_UTC"


def split_time_intervals(
    since: str,
    until: str,
    n_intervals: int,
    *,
    exponential_count: int = 10,
    exponential_min_s: int = 900,
    exponential_max_s: int = 432000,
    exponential_growth: float = 2.0,
) -> list[tuple[str, str]]:
    """Split ``[since, until]`` into contiguous intervals (newest → oldest).

    Intervals are ordered for task scheduling: the window ending at ``until``
    appears first so concurrent workers dequeue recent time ranges before older
    ones. Contiguous coverage of ``[since, until]`` is unchanged.

    Up to ``min(exponential_count, n_intervals - 1)`` slices are carved from
    ``until`` backward. Nominal widths are ``exponential_min_s * exponential_growth**i``,
    each capped by ``exponential_max_s`` and by remaining span to ``since``.

    Any span left toward ``since`` is divided into ``n_intervals - E`` equal
    windows, where ``E`` is the number of exponential slices produced (fewer if
    the range is short). If exponential slices reach ``since`` exactly, no
    uniform windows are added.
    """
    since_dt = datetime.strptime(since, _TS_FMT)
    until_dt = datetime.strptime(until, _TS_FMT)
    total_seconds = (until_dt - since_dt).total_seconds()

    if total_seconds <= 0:
        return [(since, until)]

    n_intervals = max(1, int(n_intervals))
    if n_intervals == 1:
        return [(since, until)]

    exp_n_cfg = max(1, int(exponential_count))
    exp_min = max(1, int(exponential_min_s))
    exp_max = max(exp_min, int(exponential_max_s))
    gf = float(exponential_growth)
    if gf <= 1.0:
        gf = 2.0

    # Reserve at least one uniform slot when n_intervals > 1: E <= n_intervals - 1.
    e_target = min(exp_n_cfg, n_intervals - 1)

    widths = [min(exp_min * (gf**i), float(exp_max)) for i in range(e_target)]

    exp_rev: list[tuple[datetime, datetime]] = []
    cur_right = until_dt
    for wi in widths:
        if cur_right <= since_dt:
            break
        span_left = (cur_right - since_dt).total_seconds()
        if span_left <= 0:
            break
        seg = min(float(wi), span_left)
        cur_left = cur_right - timedelta(seconds=seg)
        if cur_left < since_dt:
            cur_left = since_dt
        exp_rev.append((cur_left, cur_right))
        cur_right = cur_left
        if cur_left <= since_dt:
            break

    exp_chrono = list(reversed(exp_rev))
    e_used = len(exp_chrono)

    remainder_start = cur_right
    rem_sec = (remainder_start - since_dt).total_seconds()

    uniform: list[tuple[datetime, datetime]] = []
    if rem_sec > 0:
        m_uniform = n_intervals - e_used
        if m_uniform < 1:
            m_uniform = 1
        step = rem_sec / m_uniform
        t_left = since_dt
        for j in range(m_uniform):
            if j == m_uniform - 1:
                t_right = remainder_start
            else:
                t_right = since_dt + timedelta(seconds=step * (j + 1))
            uniform.append((t_left, t_right))
            t_left = t_right

    out = uniform + exp_chrono
    return [(a.strftime(_TS_FMT), b.strftime(_TS_FMT)) for a, b in reversed(out)]


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
