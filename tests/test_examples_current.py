"""The example scripts stay runnable and current.

The failure mode: a release adds or renames a method, and the example scripts
keep calling the old surface. A user copies an example that no longer works.
This test compiles each example and asserts that every method it calls exists
on the client. It makes no network call.
"""

import ast
import re
from pathlib import Path

from Scweet import Scweet

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
SCRIPTS = ["sync_example.py", "async_example.py"]


def test_each_example_compiles():
    for name in SCRIPTS:
        source = (EXAMPLES / name).read_text(encoding="utf-8")
        ast.parse(source)  # a syntax error raises here


def test_every_method_an_example_calls_exists_on_the_client():
    called: set[str] = set()
    for name in SCRIPTS:
        source = (EXAMPLES / name).read_text(encoding="utf-8")
        called.update(re.findall(r"s\.(a?[a-z_]+)\(", source))
    missing = sorted(m for m in called if not hasattr(Scweet, m))
    assert not missing, f"the examples call methods the client lacks: {missing}"


def test_the_examples_lead_with_the_auth_token_path():
    """The constructor call of each example uses the documented first path.

    It matches `s = Scweet(...)`, the real assignment, not a `Scweet(...)` that
    appears inside a comment or the import line.
    """
    for name in SCRIPTS:
        source = (EXAMPLES / name).read_text(encoding="utf-8")
        match = re.search(r"s = Scweet\(([^)]*)\)", source)
        assert match is not None, f"{name} holds no `s = Scweet(...)` call"
        assert "auth_token=" in match.group(1), f"{name} does not open with the auth_token path"
