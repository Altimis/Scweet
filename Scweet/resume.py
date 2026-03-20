from __future__ import annotations

import hashlib
import json
from typing import Any, Optional, Tuple


def compute_query_hash(search_request: dict, manifest_fingerprint: Optional[str] = None) -> str:
    payload = dict(search_request or {})
    payload.pop("initial_cursor", None)
    payload.pop("query_hash", None)
    if manifest_fingerprint is not None:
        payload["manifest_fingerprint"] = str(manifest_fingerprint)
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_checkpoint(resume_repo: Any, query_hash: str) -> Optional[dict[str, Any]]:
    if resume_repo is None or not hasattr(resume_repo, "get_checkpoint"):
        return None
    checkpoint = resume_repo.get_checkpoint(query_hash)
    if not isinstance(checkpoint, dict):
        return None
    raw_since = checkpoint.get("since")
    if not isinstance(raw_since, str) or not raw_since.strip():
        return None
    since = raw_since.strip()
    cursor = checkpoint.get("cursor")
    if cursor is not None and not isinstance(cursor, str):
        cursor = str(cursor)
    return {
        "since": since,
        "cursor": cursor,
    }


def _resume_from_checkpoint(
    resume_repo: Any,
    query_hash: str,
) -> Optional[Tuple[str, Optional[str]]]:
    try:
        checkpoint = _safe_checkpoint(resume_repo, query_hash)
    except Exception:
        return None
    if checkpoint is None:
        return None
    return checkpoint["since"], checkpoint["cursor"]


def resolve_resume_start(
    mode: str,
    csv_path: Optional[str],
    requested_since: str,
    resume_repo,
    query_hash: str,
) -> Tuple[str, Optional[str]]:
    checkpoint_result = _resume_from_checkpoint(resume_repo, query_hash)
    if checkpoint_result is None:
        return requested_since, None
    return checkpoint_result
