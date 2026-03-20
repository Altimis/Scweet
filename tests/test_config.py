from __future__ import annotations

import pytest
from pydantic import ValidationError

from Scweet import ScweetConfig
from Scweet import configure_logging


def test_public_config_symbols_are_exported():
    assert ScweetConfig is not None
    assert configure_logging is not None
    assert callable(configure_logging)


def test_scweetconfig_flat_fields():
    cfg = ScweetConfig(
        db_path="state.db",
        concurrency=3,
        proxy="http://localhost:8080",
        api_http_mode="sync",
        n_splits=7,
        lease_ttl_s=333,
    )

    assert cfg.db_path == "state.db"
    assert cfg.api_http_mode.value == "sync"
    assert cfg.concurrency == 3
    assert cfg.n_splits == 7
    assert cfg.lease_ttl_s == 333


def test_proxy_validation_rejects_invalid_proxy():
    with pytest.raises(ValidationError):
        ScweetConfig(proxy={"host": "127.0.0.1"})
