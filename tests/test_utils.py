from __future__ import annotations

from Scweet.utils import as_str, normalize_proxy_payload


def test_as_str_returns_none_for_empty_and_none():
    assert as_str(None) is None
    assert as_str("") is None
    assert as_str("  ") is None


def test_as_str_strips_and_returns():
    assert as_str("  hello ") == "hello"
    assert as_str(42) == "42"
    assert as_str(0) == "0"


def test_normalize_proxy_payload_none_and_empty():
    assert normalize_proxy_payload(None) is None
    assert normalize_proxy_payload("") is None
    assert normalize_proxy_payload("  ") is None


def test_normalize_proxy_payload_url_string():
    assert normalize_proxy_payload("http://proxy:8080") == "http://proxy:8080"


def test_normalize_proxy_payload_json_string():
    result = normalize_proxy_payload('{"host": "proxy", "port": 8080}')
    assert result == {"host": "proxy", "port": 8080}


def test_normalize_proxy_payload_invalid_json_returns_string():
    assert normalize_proxy_payload("{bad json}") == "{bad json}"


def test_normalize_proxy_payload_dict_returns_copy():
    original = {"host": "proxy", "port": 8080}
    result = normalize_proxy_payload(original)
    assert result == original
    assert result is not original
