from __future__ import annotations

import json
from typing import Any


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def flatten_for_csv(value: Any, *, sep: str = ".", max_depth: int = 30) -> dict[str, Any]:
    """Flatten nested dict/list structures into a single-level dict.

    - Dicts are flattened using dot-separated keys.
    - Lists are flattened by index (e.g. "entities.hashtags.0.text").
    - Non-scalar leaf values are serialized as JSON strings.
    """

    out: dict[str, Any] = {}

    def _recurse(node: Any, prefix: str, depth: int) -> None:
        if depth > max_depth:
            if prefix:
                out[prefix] = _json_dumps(node)
            return

        if isinstance(node, dict):
            for key in sorted(node.keys(), key=lambda k: str(k)):
                child_prefix = f"{prefix}{sep}{key}" if prefix else str(key)
                _recurse(node.get(key), child_prefix, depth + 1)
            return

        if isinstance(node, list):
            for idx, item in enumerate(node):
                child_prefix = f"{prefix}{sep}{idx}" if prefix else str(idx)
                _recurse(item, child_prefix, depth + 1)
            return

        if isinstance(node, (tuple, set)):
            out[prefix] = _json_dumps(list(node))
            return

        if prefix:
            out[prefix] = node
        else:
            out["value"] = node

    _recurse(value, "", 0)
    return out

