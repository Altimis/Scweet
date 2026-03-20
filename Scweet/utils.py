from __future__ import annotations

import json
from typing import Any, Optional


def as_str(value: Any) -> Optional[str]:
    """Convert value to stripped string, returning None for empty/None."""
    if value is None:
        return None
    text = str(value).strip()
    return text if text else None


def normalize_proxy_payload(payload: Any) -> Any:
    """Normalize a proxy payload into a stable python value.

    Accepted forms: None, str (URL or JSON), dict (host/port or http/https mapping).
    """
    if payload is None:
        return None
    if isinstance(payload, str):
        stripped = payload.strip()
        if not stripped:
            return None
        if stripped.startswith("{") or stripped.startswith("[") or stripped.startswith('"'):
            try:
                return json.loads(stripped)
            except Exception:
                return stripped
        return stripped
    if isinstance(payload, dict):
        return dict(payload)
    return payload
