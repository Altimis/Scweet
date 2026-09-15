"""The README and the documentation teach the same first path.

The failure mode, measured 2026-09-15: the README quickstart taught
`auth_token` while DOCUMENTATION.md recommended `cookies.json`, so a new user
read two different first steps. This test pins both to one path, so they cannot
drift apart again.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
DOCS = (ROOT / "DOCUMENTATION.md").read_text(encoding="utf-8")


def _first_scweet_call(text: str) -> str:
    """The first `Scweet(...)` constructor call in the text."""
    marker = "Scweet("
    index = text.find(marker)
    assert index != -1, "the document holds no Scweet(...) call"
    end = text.find(")", index)
    return text[index:end]


def test_the_readme_first_call_uses_the_auth_token_path():
    assert "auth_token=" in _first_scweet_call(README)


def test_the_documentation_first_call_uses_the_auth_token_path():
    assert "auth_token=" in _first_scweet_call(DOCS)


def test_both_documents_start_with_the_same_credential():
    def credential(call: str) -> str:
        for name in ("auth_token=", "cookies_file=", "cookies=", "env_path=", "db_path="):
            if name in call:
                return name
        return "none"

    assert credential(_first_scweet_call(README)) == credential(_first_scweet_call(DOCS))


def test_the_readme_quickstart_code_block_has_no_placeholder_proxy():
    """The first code block once carried a proxy `host:port` that passes the
    validator, so a copy of it sent a request to a host named `host`."""
    quickstart = README[README.find("## Python Quickstart") : README.find("### Proxies")]
    assert "@host:port" not in quickstart, "a placeholder proxy in the runnable block"
    # The runnable first block names no proxy at all.
    first_block = quickstart[quickstart.find("```python") : quickstart.find("```", quickstart.find("```python") + 3)]
    assert "proxy=" not in first_block
