from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Tuple

_DATE_FMT = "%Y-%m-%d"
_TWITTER_CREATED_AT_FMT = "%a %b %d %H:%M:%S %z %Y"


def _parse_timestamp(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", ""))
    except Exception:
        pass
    try:
        return datetime.strptime(text, _TWITTER_CREATED_AT_FMT)
    except Exception:
        return None


def _max_csv_timestamp(csv_path: str) -> Optional[datetime]:
    max_dt = None
    with open(csv_path, "r", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if not header:
            return None
        candidates = ["Timestamp", "legacy.created_at", "created_at", "legacy.createdAt", "legacyCreatedAt"]
        ts_idx = None
        for name in candidates:
            if name in header:
                ts_idx = header.index(name)
                break
        if ts_idx is None:
            return None

        for row in reader:
            if len(row) <= ts_idx:
                continue
            timestamp_str = (row[ts_idx] or "").strip()
            if not timestamp_str:
                continue
            parsed = _parse_timestamp(timestamp_str)
            if parsed and (max_dt is None or parsed > max_dt):
                max_dt = parsed
    return max_dt


def legacy_csv_resume_since(csv_path: str, requested_since: str) -> str:
    """Return v3-compatible resume `since` based on the CSV max Timestamp."""

    try:
        csv_max_dt = _max_csv_timestamp(csv_path)
        if csv_max_dt is None:
            return requested_since
        requested_since_dt = datetime.strptime(str(requested_since).strip(), _DATE_FMT)
        if csv_max_dt.date() >= requested_since_dt.date():
            return csv_max_dt.strftime(_DATE_FMT)
        return requested_since
    except Exception:
        return requested_since


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
    normalized_mode = str(mode or "hybrid_safe").strip().lower()

    if normalized_mode == "legacy_csv":
        if not csv_path:
            return requested_since, None
        try:
            if not Path(csv_path).exists():
                return requested_since, None
            return legacy_csv_resume_since(csv_path, requested_since), None
        except Exception:
            return requested_since, None

    if normalized_mode == "db_cursor":
        checkpoint_result = _resume_from_checkpoint(resume_repo, query_hash)
        if checkpoint_result is None:
            return requested_since, None
        return checkpoint_result

    checkpoint_result = _resume_from_checkpoint(resume_repo, query_hash)
    if checkpoint_result is not None:
        return checkpoint_result

    if csv_path:
        try:
            if Path(csv_path).exists():
                return legacy_csv_resume_since(csv_path, requested_since), None
        except Exception:
            return requested_since, None
    return requested_since, None
