"""Every external import of the package maps to a declared requirement.

The failure mode: a module imports a package that only a transitive
dependency installs. One resolver change then breaks the install.
"""

import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = ROOT / "Scweet"

# The import name on the left, the distribution name in requirements.txt on the right.
IMPORT_TO_DISTRIBUTION = {
    "bs4": "beautifulsoup4",
    "curl_cffi": "curl_cffi",
    "dotenv": "python-dotenv",
    "pydantic": "pydantic",
    "sqlalchemy": "SQLAlchemy",
    "sqlmodel": "sqlmodel",
    "x_client_transaction": "XClientTransaction",
}


def _normalize(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def _declared_distributions() -> set:
    names = set()
    for raw in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        for separator in ("==", ">=", "<=", "~=", "!=", ">", "<", "["):
            line = line.split(separator, 1)[0]
        names.add(_normalize(line))
    return names


def _imported_top_level_names() -> set:
    found = set()
    for path in PACKAGE.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.level == 0 and node.module:
                    found.add(node.module.split(".")[0])
    return found


def test_every_mapped_import_is_declared():
    declared = _declared_distributions()
    for import_name, distribution in IMPORT_TO_DISTRIBUTION.items():
        assert _normalize(distribution) in declared, (
            f"the package imports {import_name!r}, so requirements.txt "
            f"must declare {distribution!r}"
        )


def test_no_external_import_outside_the_map():
    if not hasattr(sys, "stdlib_module_names"):
        pytest.skip("sys.stdlib_module_names needs Python 3.10")
    external = set()
    for name in _imported_top_level_names():
        if name in ("Scweet", "__future__"):
            continue
        if name in sys.stdlib_module_names:
            continue
        external.add(name)
    unmapped = external - set(IMPORT_TO_DISTRIBUTION)
    assert not unmapped, (
        f"imports without a mapped distribution: {sorted(unmapped)}; "
        "add each one to IMPORT_TO_DISTRIBUTION and to requirements.txt"
    )
