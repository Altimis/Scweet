"""The bootstrap of the request signature reads an account that X accepts, the newest first.

The failure mode, reproduced 2026-09-28 with one state file: a first run with a revoked token left a row
marked ``unusable``, a second run with a fresh token added a second row, and the bootstrap of the
transaction id read the first row. X answered its login page to that row, no header was built, and every
request of the fresh account answered 404.
"""

from __future__ import annotations

from Scweet import Scweet
from Scweet.auth import import_accounts_to_db


def _accepting_bootstrap(auth_token: str, timeout_s: int = 30, *, proxy=None):
    return {"auth_token": auth_token, "ct0": f"csrf-{auth_token}", "twid": "u=1"}


def _rejecting_bootstrap(auth_token: str, timeout_s: int = 30, *, proxy=None, outcome=None):
    if outcome is not None:
        outcome["rejected"] = True
    return None


def _import(db_path: str, token: str, bootstrap_fn) -> None:
    import_accounts_to_db(db_path, cookies_payload={"auth_token": token}, bootstrap_fn=bootstrap_fn)


def test_the_bootstrap_skips_a_rejected_row_and_reads_the_newest_usable_row_first(tmp_path):
    db_path = str(tmp_path / "state.db")
    _import(db_path, "older-good", _accepting_bootstrap)
    _import(db_path, "revoked", _rejecting_bootstrap)
    _import(db_path, "newest-good", _accepting_bootstrap)

    client = Scweet(db_path=db_path)
    sets = client._cookie_sets_for_transaction_init()

    tokens = [item["cookies"]["auth_token"] for item in sets]
    assert tokens == ["newest-good", "older-good"], tokens
    assert all(item["cookies"].get("ct0") for item in sets)
    assert all(item["username"] for item in sets)


def test_a_state_file_with_only_a_rejected_row_gives_no_bootstrap_account(tmp_path):
    """The provider then reports the rejected page instead of a silent None."""
    db_path = str(tmp_path / "state.db")
    _import(db_path, "revoked", _rejecting_bootstrap)

    client = Scweet(db_path=db_path)
    assert client._cookie_sets_for_transaction_init() == []
    assert client._get_cookies_for_transaction_init() is None


def test_the_manifest_scrape_gets_the_same_cookies_and_the_proxy(tmp_path):
    db_path = str(tmp_path / "state.db")
    _import(db_path, "good", _accepting_bootstrap)

    client = Scweet(db_path=db_path, proxy="http://user:pass@proxy.example.com:8000")
    kwargs = client._bootstrap_page_kwargs()
    assert kwargs["proxy"] == "http://user:pass@proxy.example.com:8000"
    assert kwargs["cookies"]["auth_token"] == "good" and kwargs["cookies"]["ct0"]


def test_the_pool_message_names_a_rejected_token(tmp_path):
    """`AccountPoolExhausted` reads the blocked counts. `missing_csrf=1` reads as a defect of the import;
    `rejected_auth_token=1` reads as the verdict of X, which is what happened."""
    db_path = str(tmp_path / "state.db")
    _import(db_path, "revoked", _rejecting_bootstrap)

    counts = Scweet(db_path=db_path)._accounts_repo.eligibility_diagnostics()["blocked_counts"]
    assert counts.get("rejected_auth_token") == 1
    assert "missing_csrf" not in counts
