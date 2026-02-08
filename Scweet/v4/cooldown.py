from __future__ import annotations

import random
import time
from typing import Any, Optional, Tuple


def _iter_config_sections(config: Any):
    yield config
    section_names = ("pool", "runtime", "engine", "storage", "accounts", "operations", "resume", "output", "manifest")
    if isinstance(config, dict):
        for name in section_names:
            yield config.get(name)
        return
    for name in section_names:
        yield getattr(config, name, None)


def _config_value(config: Any, key: str, default: Any) -> Any:
    for section in _iter_config_sections(config):
        if section is None:
            continue
        if isinstance(section, dict):
            if key in section and section[key] is not None:
                return section[key]
            continue
        if hasattr(section, key):
            value = getattr(section, key)
            if value is not None:
                return value
    return default


def parse_rate_limit_reset(headers: Optional[dict]) -> Optional[int]:
    if not headers:
        return None
    value = headers.get("x-rate-limit-reset") or headers.get("X-Rate-Limit-Reset")
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def compute_cooldown(
    status_code: Optional[int], headers: Optional[dict], config
) -> Tuple[int, float, Optional[str]]:
    now_ts = time.time()
    cooldown_default_s = float(_config_value(config, "cooldown_default_s", 120))
    transient_cooldown_s = float(_config_value(config, "transient_cooldown_s", 120))
    auth_cooldown_s = float(_config_value(config, "auth_cooldown_s", 30 * 24 * 60 * 60))
    cooldown_jitter_s = max(0.0, float(_config_value(config, "cooldown_jitter_s", 10)))
    jitter = random.uniform(0, cooldown_jitter_s) if cooldown_jitter_s > 0 else 0.0

    if status_code in (401, 403, 404):
        return int(status_code), now_ts + auth_cooldown_s, "auth_failed"

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
