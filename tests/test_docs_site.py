"""The site of the documentation holds the text of the release.

`docs_hooks.py` copies DOCUMENTATION.md, CHANGELOG.md and CONTRIBUTING.md from the root of the repository into
`docs/` before each build. One file therefore holds each text, and a release cannot publish an old copy.

A symbolic link also works for `mkdocs build`. It does not work for `mkdocs serve`, so a contributor who reads
the site on their machine meets a page with the code 404. The hook copies the file instead.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]

# Each page of the navigation, and the file at the root that holds its text. `index.md` is the only page
# that the site owns.
_GENERATED = {
    "documentation.md": "DOCUMENTATION.md",
    "changelog.md": "CHANGELOG.md",
    "contributing.md": "CONTRIBUTING.md",
}


@pytest.fixture(scope="module")
def mkdocs_config() -> str:
    path = _ROOT / "mkdocs.yml"
    assert path.is_file(), "the site needs mkdocs.yml at the root"
    return path.read_text(encoding="utf-8")


def test_the_hook_runs_before_a_build(mkdocs_config):
    """Without the hook, a fresh clone builds a site with three pages absent."""
    assert "hooks:" in mkdocs_config
    assert "docs_hooks.py" in mkdocs_config
    assert (_ROOT / "docs_hooks.py").is_file()


def test_the_hook_names_every_page_of_the_navigation(mkdocs_config):
    """A page in the navigation with no source is a page with the code 404."""
    hook = (_ROOT / "docs_hooks.py").read_text(encoding="utf-8")
    for page, source in _GENERATED.items():
        assert page in mkdocs_config, f"the navigation names no page {page}"
        assert page in hook and source in hook, f"the hook copies no {source} to {page}"


def test_every_source_of_a_page_exists(mkdocs_config):
    for source in _GENERATED.values():
        assert (_ROOT / source).is_file(), f"the site needs {source} at the root"


def test_the_build_stops_for_a_broken_link(mkdocs_config):
    """`strict` turns a broken link into a failure, so a release cannot publish one."""
    assert "strict: true" in mkdocs_config


def test_the_home_page_belongs_to_the_site(mkdocs_config):
    """`index.md` holds the first path of a new user. The hook must not overwrite it."""
    hook = (_ROOT / "docs_hooks.py").read_text(encoding="utf-8")
    assert "index.md" not in hook, "the hook must not write over the home page"
    assert (_ROOT / "docs" / "index.md").is_file()


def test_the_tools_that_build_the_site_hold_an_exact_version():
    """MkDocs 2.0 removes the system of plugins, so a floating version can break the build."""
    req = (_ROOT / "docs-requirements.txt").read_text(encoding="utf-8")
    for package in ("mkdocs==", "mkdocs-material=="):
        assert package in req, f"{package} needs an exact version"


def test_the_workflow_builds_and_verifies_the_site():
    workflow = (_ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
    assert "mkdocs build --strict" in workflow
    assert "docs-requirements.txt" in workflow
    # The workflow runs the same file that `make docs-check` runs, so the two results agree.
    assert "scripts/check_docs_site.py" in workflow


def test_a_deploy_needs_a_person():
    """A push must not publish the site. A person starts the deploy after they read the artifact."""
    workflow = (_ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
    deploy = workflow.split("Publish to GitHub Pages")[1]
    assert "workflow_dispatch" in deploy and "inputs.deploy" in deploy, (
        "the deploy must read a manual input, so a push cannot publish the site"
    )


def test_the_build_keeps_the_site_for_a_review():
    """A reviewer reads the built site before it reaches the public."""
    workflow = (_ROOT / ".github" / "workflows" / "docs.yml").read_text(encoding="utf-8")
    assert "upload-artifact" in workflow


def test_a_contributor_holds_one_command_for_each_step():
    """`make docs-serve` reads the site on a machine, and `make docs-check` verifies it."""
    assert (_ROOT / "scripts" / "check_docs_site.py").is_file()
    makefile = (_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "docs-check" in makefile and "check_docs_site.py" in makefile
    assert "docs-serve" in makefile


class TestTheServerDoesNotRebuildForEver:
    """`mkdocs serve` watches `docs/`, and the hook writes into `docs/`.

    An unconditional write therefore starts a loop: the write raises an event, the event starts a build, and
    the build writes again. Measured 2026-09-21 before the guard: 2,047 rebuilds, and the page of a reader
    refreshed without a stop.
    """

    def test_the_hook_writes_only_for_a_change_of_the_text(self, tmp_path):
        import importlib.util

        spec = importlib.util.spec_from_file_location("docs_hooks", _ROOT / "docs_hooks.py")
        hooks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hooks)

        docs = tmp_path / "docs"
        docs.mkdir()
        config = {"config_file_path": str(_ROOT / "mkdocs.yml"), "docs_dir": str(docs)}

        hooks.on_pre_build(config)
        target = docs / "documentation.md"
        first = target.stat().st_mtime_ns

        hooks.on_pre_build(config)
        assert target.stat().st_mtime_ns == first, (
            "the second call wrote the same text again, so `mkdocs serve` rebuilds for ever"
        )

    def test_the_hook_writes_when_the_text_changes(self, tmp_path):
        import importlib.util

        spec = importlib.util.spec_from_file_location("docs_hooks", _ROOT / "docs_hooks.py")
        hooks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hooks)

        docs = tmp_path / "docs"
        docs.mkdir()
        config = {"config_file_path": str(_ROOT / "mkdocs.yml"), "docs_dir": str(docs)}
        hooks.on_pre_build(config)
        target = docs / "documentation.md"
        target.write_text("an old copy", encoding="utf-8")

        hooks.on_pre_build(config)
        assert target.read_text(encoding="utf-8") != "an old copy", "the hook must replace an old copy"

    def test_the_server_watches_each_document_at_the_root(self):
        """Without this, an edit of DOCUMENTATION.md changes nothing on the screen of a contributor."""
        hook = (_ROOT / "docs_hooks.py").read_text(encoding="utf-8")
        assert "def on_serve" in hook
        assert "server.watch" in hook
