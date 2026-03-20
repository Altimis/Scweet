from __future__ import annotations

import random
import time
from typing import Any, Optional, Tuple


def _cfg(config: Any, key: str, default: Any) -> Any:
    if config is None:
        return default
    if isinstance(config, dict):
        value = config.get(key)
        return value if value is not None else default
    value = getattr(config, key, None)
    return value if value is not None else default


def _header_value(headers: Optional[dict], *keys: str) -> Any:
    if not headers:
        return None
    for key in keys:
        if key in headers:
            return headers.get(key)
    lowered = {str(k).lower(): v for k, v in dict(headers).items()}
    for key in keys:
        value = lowered.get(str(key).lower())
        if value is not None:
            return value
    return None


def parse_rate_limit_reset(headers: Optional[dict]) -> Optional[int]:
    value = _header_value(headers, "x-rate-limit-reset")
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def parse_rate_limit_remaining(headers: Optional[dict]) -> Optional[int]:
    value = _header_value(headers, "x-rate-limit-remaining")
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def effective_status_with_rate_limit_headers(status_code: Optional[int], headers: Optional[dict]) -> int:
    effective_status = int(status_code or 0)
    remaining = parse_rate_limit_remaining(headers)
    if effective_status == 200 and remaining is not None and remaining <= 0:
        return 429
    return effective_status


def compute_cooldown(
    status_code: Optional[int], headers: Optional[dict], config
) -> Tuple[int, float, Optional[str]]:
    now_ts = time.time()
    cooldown_default_s = float(_cfg(config, "cooldown_default_s", 120))
    transient_cooldown_s = float(_cfg(config, "transient_cooldown_s", 120))
    auth_cooldown_s = float(_cfg(config, "auth_cooldown_s", 30 * 24 * 60 * 60))
    cooldown_jitter_s = max(0.0, float(_cfg(config, "cooldown_jitter_s", 10)))
    jitter = random.uniform(0, cooldown_jitter_s) if cooldown_jitter_s > 0 else 0.0

    if status_code in (401, 403):
        return int(status_code), now_ts + auth_cooldown_s, "auth_failed"

    # 404 from GraphQL typically means stale query IDs, not bad auth.
    # Use a short transient cooldown so the account can retry quickly.
    if status_code == 404:
        return int(status_code), now_ts + transient_cooldown_s + jitter, "transient"

    if status_code == 429:
        reset_ts = parse_rate_limit_reset(headers or {})
        if reset_ts and reset_ts > now_ts:
            return 1, float(reset_ts), "rate_limit"
        return 1, now_ts + cooldown_default_s + jitter, "rate_limit"

    transient = False
    if status_code is not None:
        if status_code in (598, 599):
            transient = True
        if 500 <= status_code < 600:
            transient = True
    if transient:
        return 1, now_ts + transient_cooldown_s + jitter, "transient"

    return 1, 0.0, None
