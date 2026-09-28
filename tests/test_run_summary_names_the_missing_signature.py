"""A run that fails on 404 without the header tells the reader the cause and the action.

X answers 404 with an empty body to a request without the x-client-transaction-id header. A summary made
of five lines `status=404 detail=` told the reporter of 2026-09-28 nothing, and the run ended in a
class that reads as an expired cookie.
"""

from __future__ import annotations

from Scweet.http_utils import NO_SIGNATURE_CAUSE, NO_SIGNATURE_DETAIL
from Scweet.models import RunStats
from Scweet.runner import Runner


def _event(detail: str, status: int = 404) -> dict:
    return {"kind": "api_request", "username": "acct", "status_code": status, "detail": detail}


def test_the_summary_adds_the_cause_when_the_404s_carry_no_header():
    events = [_event(NO_SIGNATURE_DETAIL) for _ in range(4)]
    summary = Runner._build_run_failure_summary(RunStats(tasks_total=4), unresolved=4, error_events=events)
    assert NO_SIGNATURE_CAUSE in summary
    assert "fresh auth_token" in summary


def test_the_summary_stays_silent_when_the_404s_carried_the_header():
    """A 404 with the header is a stale query id or a removed item, and this cause would mislead."""
    events = [_event("") for _ in range(4)]
    summary = Runner._build_run_failure_summary(RunStats(tasks_total=4), unresolved=4, error_events=events)
    assert NO_SIGNATURE_CAUSE not in summary


def test_a_minority_of_missing_headers_does_not_name_the_cause():
    events = [_event(NO_SIGNATURE_DETAIL)] + [_event("rate limited", 429) for _ in range(3)]
    summary = Runner._build_run_failure_summary(RunStats(tasks_total=4), unresolved=4, error_events=events)
    assert NO_SIGNATURE_CAUSE not in summary
