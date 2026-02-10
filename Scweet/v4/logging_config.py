from __future__ import annotations

import logging
import sys
from typing import Optional, TextIO, Union


Level = Union[int, str]

_SIMPLE_FMT = "%(asctime)s %(levelname)s %(name)s | %(message)s"
_DETAILED_FMT = "%(asctime)s %(levelname)s %(name)s:%(lineno)d | %(message)s"


def configure_logging(
    *,
    level: Level = "INFO",
    profile: str = "simple",
    force: bool = False,
    stream: Optional[TextIO] = None,
    fmt: Optional[str] = None,
    datefmt: str = "%Y-%m-%d %H:%M:%S",
    show_api_http: Optional[bool] = None,
    api_level: Optional[Level] = None,
    transaction_level: Optional[Level] = None,
) -> None:
    """Configure Scweet logging (opt-in).

    Libraries should not configure global logging automatically. This helper is intended
    for users running Scweet in scripts/notebooks who want consistent, visible logs.

    Args:
        level: Base log level for the "Scweet" logger tree.
        profile:
            - "simple": high-level flow logs, suppress per-request API logs by default.
            - "detailed": include file/line and enable per-request API logs by default.
        force: If True, replaces existing handlers on the "Scweet" logger. This is useful in
            notebooks where logging is often pre-configured.
        stream: Output stream (defaults to sys.stdout).
        fmt: Optional custom formatter string. If unset, a sensible default is used.
        datefmt: datetime format string.
        show_api_http: If True, enable API request logs. If False, suppress them. If None,
            defaults depend on profile.
        api_level: Override the level for Scweet.v4.api_engine (if set).
        transaction_level: Override the level for Scweet.v4.transaction (if set).
    """

    profile_value = str(profile or "simple").strip().lower()
    if profile_value not in {"simple", "detailed"}:
        profile_value = "simple"

    if show_api_http is None:
        show_api_http = profile_value == "detailed"

    if stream is None:
        stream = sys.stdout

    if fmt is None:
        fmt = _DETAILED_FMT if profile_value == "detailed" else _SIMPLE_FMT

    scweet_logger = logging.getLogger("Scweet")
    if force:
        scweet_logger.handlers.clear()

    if not scweet_logger.handlers:
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
        scweet_logger.addHandler(handler)

    scweet_logger.setLevel(level)
    scweet_logger.propagate = False

    # Module-specific noise control.
    resolved_api_level: Level
    if api_level is not None:
        resolved_api_level = api_level
    else:
        resolved_api_level = "INFO" if show_api_http else "WARNING"

    resolved_transaction_level: Level
    if transaction_level is not None:
        resolved_transaction_level = transaction_level
    else:
        resolved_transaction_level = "INFO" if profile_value == "detailed" else "WARNING"

    logging.getLogger("Scweet.v4.api_engine").setLevel(resolved_api_level)
    logging.getLogger("Scweet.v4.transaction").setLevel(resolved_transaction_level)
