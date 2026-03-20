from __future__ import annotations

import json
from pathlib import Path

from Scweet.auth import load_cookies_payload, load_env_account


def _write(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    return path


def test_load_env_account_creds_only(tmp_path):
    env_path = _write(
        tmp_path / ".env",
        "\n".join(
            [
                "# legacy v3 keys",
                "EMAIL=alice@example.com",
                "EMAIL_PASSWORD=mailpass",
                "USERNAME=alice",
                "PASSWORD=pass123",
                "OTP_SECRET=otp-secret",
                "",
            ]
        ),
    )

    records = load_env_account(str(env_path))
    assert len(records) == 1
    record = records[0]

    assert record["username"] == "alice"
    assert record["email"] == "alice@example.com"
    assert record["email_password"] == "mailpass"
    assert record["password"] == "pass123"
    assert record["two_fa"] == "otp-secret"
    assert record["auth_token"] is None


def test_load_env_account_auth_token_and_ct0(tmp_path):
    env_path = _write(
        tmp_path / ".env",
        "\n".join(
            [
                "AUTH_TOKEN=tok-1",
                "CT0=csrf-1",
            ]
        ),
    )

    records = load_env_account(str(env_path))
    assert len(records) == 1
    record = records[0]

    assert record["auth_token"] == "tok-1"
    assert record["csrf"] == "csrf-1"
    assert record["cookies_json"]["auth_token"] == "tok-1"
    assert record["cookies_json"]["ct0"] == "csrf-1"
    assert record["username"].startswith("auth_")


def test_load_env_account_auth_token_only(tmp_path):
    env_path = _write(tmp_path / ".env", "AUTH_TOKEN=tok-2\n")

    records = load_env_account(str(env_path))
    assert len(records) == 1
    record = records[0]

    assert record["auth_token"] == "tok-2"
    assert record["csrf"] is None
    assert record["cookies_json"]["auth_token"] == "tok-2"
    assert record["username"].startswith("auth_")


def test_load_env_account_derives_username_from_email_localpart(tmp_path):
    env_path = _write(
        tmp_path / ".env",
        "\n".join(
            [
                "EMAIL=bob@example.com",
                "PASSWORD=pass",
            ]
        ),
    )

    records = load_env_account(str(env_path))
    assert len(records) == 1
    record = records[0]
    assert record["username"] == "bob"


def test_load_cookies_payload_accepts_cookie_dict_and_cookie_list_and_json_string():
    dict_payload = {"auth_token": "tok-a", "ct0": "csrf-a", "guest_id": "guest-a"}
    list_payload = [{"name": "auth_token", "value": "tok-b"}, {"name": "ct0", "value": "csrf-b"}]
    json_payload = json.dumps({"auth_token": "tok-c", "ct0": "csrf-c", "guest_id": "guest-c"})

    dict_record = load_cookies_payload(dict_payload)[0]
    list_record = load_cookies_payload(list_payload)[0]
    json_record = load_cookies_payload(json_payload)[0]

    assert dict_record["auth_token"] == "tok-a"
    assert dict_record["csrf"] == "csrf-a"
    assert dict_record["cookies_json"]["ct0"] == "csrf-a"
    assert dict_record["cookies_json"]["guest_id"] == "guest-a"

    assert list_record["auth_token"] == "tok-b"
    assert list_record["csrf"] == "csrf-b"
    assert list_record["cookies_json"]["ct0"] == "csrf-b"

    assert json_record["auth_token"] == "tok-c"
    assert json_record["csrf"] == "csrf-c"
    assert json_record["cookies_json"]["ct0"] == "csrf-c"
    assert json_record["cookies_json"]["guest_id"] == "guest-c"


def test_load_cookies_payload_accepts_cookie_header_string_and_raw_token_string():
    header = "auth_token=tok-h; ct0=csrf-h; other=value"
    raw_token = "tok-direct"

    header_record = load_cookies_payload(header)[0]
    token_record = load_cookies_payload(raw_token)[0]

    assert header_record["auth_token"] == "tok-h"
    assert header_record["csrf"] == "csrf-h"
    assert header_record["cookies_json"]["ct0"] == "csrf-h"
    assert header_record["cookies_json"]["other"] == "value"

    assert token_record["auth_token"] == "tok-direct"
    assert token_record["csrf"] is None
    assert token_record["cookies_json"]["auth_token"] == "tok-direct"
    assert token_record["username"].startswith("auth_")


def test_load_cookies_payload_treats_existing_path_string_as_cookies_file(tmp_path):
    cookies_txt = _write(
        tmp_path / "cookies.txt",
        "\n".join(
            [
                "# Netscape HTTP Cookie File",
                ".x.com\tTRUE\t/\tTRUE\t0\tauth_token\ttok-path",
                ".x.com\tTRUE\t/\tTRUE\t0\tct0\tcsrf-path",
            ]
        ),
    )

    record = load_cookies_payload(str(cookies_txt))[0]
    assert record["auth_token"] == "tok-path"
    assert record["csrf"] == "csrf-path"
    assert record["cookies_json"]["auth_token"] == "tok-path"
    assert record["cookies_json"]["ct0"] == "csrf-path"


def test_load_cookies_payload_accepts_accounts_list_and_mapping_forms():
    payload = {
        "accounts": [
            {"username": "acct1", "cookies": {"auth_token": "t1", "ct0": "c1"}},
            {"user": "acct2", "cookies_json": {"auth_token": "t2", "ct0": "c2"}},
        ]
    }
    mapping = {
        "alice": {"auth_token": "ta", "ct0": "ca"},
        "bob": [{"name": "auth_token", "value": "tb"}, {"name": "ct0", "value": "cb"}],
    }

    records = load_cookies_payload(payload)
    assert [r["username"] for r in records] == ["acct1", "acct2"]

    mapped = load_cookies_payload(mapping)
    by_username = {r["username"]: r for r in mapped}
    assert by_username["alice"]["auth_token"] == "ta"
    assert by_username["alice"]["csrf"] == "ca"
    assert by_username["bob"]["auth_token"] == "tb"
    assert by_username["bob"]["csrf"] == "cb"
