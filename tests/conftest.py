from __future__ import annotations

import sys
from pathlib import Path


def _add_package_root() -> None:
    repo_root = Path(__file__).resolve().parent.parent  # Scweet/ repo root
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))


_add_package_root()


def pytest_configure(config):
    config.addinivalue_line("markers", "integration: requires real Twitter/X credentials")
