from __future__ import annotations

from Scweet.resume import compute_query_hash, resolve_resume_start


class _CheckpointRepo:
    def __init__(self, checkpoint):
        self._checkpoint = checkpoint

    def get_checkpoint(self, query_hash: str):
        _ = query_hash
        return self._checkpoint


def test_resolve_resume_start_db_cursor_uses_checkpoint():
    repo = _CheckpointRepo({"since": "2025-01-04", "cursor": "CURSOR-1"})
    since, cursor = resolve_resume_start(
        mode="db_cursor",
        csv_path=None,
        requested_since="2025-01-01",
        resume_repo=repo,
        query_hash="q1",
    )

    assert since == "2025-01-04"
    assert cursor == "CURSOR-1"


def test_compute_query_hash_is_stable_across_key_order():
    request_a = {
        "since": "2025-01-01",
        "until": "2025-01-02",
        "words": ["btc", "eth"],
        "display_type": "Top",
    }
    request_b = {
        "display_type": "Top",
        "words": ["btc", "eth"],
        "until": "2025-01-02",
        "since": "2025-01-01",
    }

    hash_a = compute_query_hash(request_a, manifest_fingerprint="m1")
    hash_b = compute_query_hash(request_b, manifest_fingerprint="m1")
    hash_c = compute_query_hash(request_b, manifest_fingerprint="m2")

    assert hash_a == hash_b
    assert hash_a != hash_c
