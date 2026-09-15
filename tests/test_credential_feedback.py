"""A bad credential says so at once, and every loader accepts the same shapes.

Two failure modes, both measured 2026-09-14:

1. A dead auth_token gave 0 warnings at construction. The import counted the
   records it processed, not the usable ones, so the guard of the client never
   fired. The pool then held total=1, eligible=0, and the first search raised
   an error that named cooldowns.
2. A standard browser-extension export gave [] from `cookies_file=` and one
   account from `cookies=`. The same data, a different result, because the two
   loaders held different shape walks.
"""

import json
import warnings
from pathlib import Path

import Scweet.auth as auth
from Scweet.auth import import_accounts_to_db, load_cookies_json, load_cookies_payload

# The shape a browser extension exports: a list of cookie dicts with name/value.
EXTENSION_EXPORT = [
    {"domain": ".x.com", "name": "auth_token", "value": "aaaabbbbcccc", "path": "/"},
    {"domain": ".x.com", "name": "ct0", "value": "ddddeeeeffff", "path": "/"},
]


def test_a_file_and_an_inline_payload_accept_the_same_export(tmp_path):
    path = tmp_path / "export.json"
    path.write_text(json.dumps(EXTENSION_EXPORT), encoding="utf-8")

    from_file = load_cookies_json(str(path))
    from_inline = load_cookies_payload(EXTENSION_EXPORT)

    assert len(from_inline) == 1
    assert len(from_file) == 1, "the file loader dropped an export that works inline"
    assert from_file[0].get("auth_token") == from_inline[0].get("auth_token")


def test_the_account_records_file_shape_still_loads(tmp_path):
    """The one-loader change must not drop the documented cookies.json shape."""
    payload = [
        {"username": "a1", "cookies": {"auth_token": "t1", "ct0": "c1"}},
        {"username": "a2", "cookies": {"auth_token": "t2", "ct0": "c2"}},
    ]
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    records = load_cookies_json(str(path))
    assert [r["username"] for r in records] == ["a1", "a2"]


def test_the_import_counts_usable_accounts_and_not_processed_records(tmp_path, monkeypatch):
    # A dead token: the ct0 bootstrap fails, which is what X does for one.
    monkeypatch.setattr(auth, "bootstrap_cookies_from_auth_token", lambda *a, **k: None)
    count = import_accounts_to_db(
        str(tmp_path / "s.db"),
        cookies_payload={"auth_token": "dead_token_value"},
    )
    assert count == 0, "a processed but unusable record must not count"


def test_a_usable_account_still_counts(tmp_path):
    count = import_accounts_to_db(
        str(tmp_path / "s.db"),
        cookies_payload=[{"username": "ok1", "cookies": {"auth_token": "t", "ct0": "c"}}],
    )
    assert count == 1


def test_a_dead_token_warns_at_construction(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "bootstrap_cookies_from_auth_token", lambda *a, **k: None)
    from Scweet.client import Scweet

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        Scweet(auth_token="dead_token_value", db_path=str(tmp_path / "s.db"))

    messages = [str(w.message) for w in caught]
    assert any("no usable accounts" in m for m in messages), messages
    assert any("auth_token" in m for m in messages), "the warning names the credential"
