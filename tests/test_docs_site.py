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


class TestEveryDocumentPointsAtTheSite:
    """A reader who opens any document finds the site. A reader of PyPI finds it in the sidebar."""

    SITE = "https://altimis.github.io/Scweet/"

    def test_each_document_names_the_site(self):
        for name in ("README.md", "DOCUMENTATION.md", "CONTRIBUTING.md", "CHANGELOG.md"):
            text = (_ROOT / name).read_text(encoding="utf-8")
            assert "altimis.github.io/Scweet" in text, f"{name} does not name the site"

    def test_the_badge_of_the_readme_opens_the_site(self):
        """The badge said `#documentation`, which held the reader inside one long file."""
        readme = (_ROOT / "README.md").read_text(encoding="utf-8")
        badge = readme.split('alt="Documentation"')[0]
        assert self.SITE in badge.rsplit("<a href=", 1)[1], (
            "the badge of the documentation must open the site"
        )

    def test_pypi_shows_the_site_in_the_sidebar(self):
        setup = (_ROOT / "setup.py").read_text(encoding="utf-8")
        assert "project_urls" in setup
        assert f'"Documentation": "{self.SITE}"' in setup

    def test_the_generated_pages_stay_out_of_git(self):
        """A copy in git becomes a second source, and the two fall apart."""
        ignore = (_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for page in ("docs/documentation.md", "docs/changelog.md", "docs/contributing.md"):
            assert page in ignore, f"{page} is generated, so git must ignore it"
        # `index.md` belongs to the site, so it stays in git.
        assert "docs/index.md" not in ignore


class TestThePageOfTheSiteDoesNotPointAtTheSite:
    """A file at the root serves two readers, and one line does not suit both.

    `DOCUMENTATION.md` opens with a line that sends a reader of GitHub to the site. That line also reached the
    page of the site, where it told a reader to go where they already were. The build removes each line that
    holds the marker `<!-- github-only -->`.
    """

    def test_the_build_removes_a_line_for_github_only(self):
        import importlib.util

        spec = importlib.util.spec_from_file_location("docs_hooks", _ROOT / "docs_hooks.py")
        hooks = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hooks)

        source = "# Title\n\n> Read it on the site. <!-- github-only -->\n\nThe real text.\n"
        result = hooks._for_the_site(source)
        assert "github-only" not in result
        assert "Read it on the site" not in result
        assert "The real text." in result
        assert "# Title" in result

    def test_the_file_at_the_root_keeps_the_line(self):
        """A reader of GitHub needs it. Only the page of the site loses it."""
        text = (_ROOT / "DOCUMENTATION.md").read_text(encoding="utf-8")
        assert "altimis.github.io/Scweet" in text
        assert "<!-- github-only -->" in text, (
            "the note must carry the marker, or it reaches the page of the site"
        )

    def test_the_built_reference_page_does_not_send_a_reader_to_the_site(self):
        built = _ROOT / "site" / "documentation" / "index.html"
        if not built.is_file():
            import pytest as _pytest

            _pytest.skip("run `make docs` first")
        html = built.read_text(encoding="utf-8")
        assert "Read this as a site" not in html
        assert "reads better on the documentation site" not in html
