"""Copy the documents at the root of the repository into `docs/` before a build.

One file holds each text, so the site cannot fall behind a release. A symbolic link also works for
`mkdocs build`, but `mkdocs serve` does not follow one: a contributor who reads the site on their machine then
meets a page with the code 404. A copy works for both commands.
"""

from __future__ import annotations

from pathlib import Path

# A line that holds this marker reaches a reader of GitHub only. The build removes it from the page of the
# site, because a reader who sits on the site needs no link to the site.
_SITE_ONLY_MARKER = "<!-- github-only -->"

# The file at the root of the repository, and the name of the page that it becomes.
_ROOT_PAGES = {
    "DOCUMENTATION.md": "documentation.md",
    "CHANGELOG.md": "changelog.md",
    "CONTRIBUTING.md": "contributing.md",
}


def _for_the_site(text: str) -> str:
    """Remove each line that belongs to a reader of GitHub and not to a reader of the site.

    A file at the root serves two readers. A reader of GitHub needs the line that points at the site. A reader
    who already sits on the site does not: that line told them to go where they already are.

    A line that holds the marker below leaves the page of the site. It stays in the file at the root.
    """
    lines = [line for line in text.splitlines() if _SITE_ONLY_MARKER not in line]
    # The removal leaves two empty lines where the note was. Keep one.
    cleaned: list[str] = []
    for line in lines:
        if not line.strip() and cleaned and not cleaned[-1].strip():
            continue
        cleaned.append(line)
    return "\n".join(cleaned) + "\n"


def on_pre_build(config, **kwargs) -> None:
    root = Path(config["config_file_path"]).parent
    docs_dir = Path(config["docs_dir"])
    for source_name, page_name in _ROOT_PAGES.items():
        source = root / source_name
        if not source.is_file():
            raise FileNotFoundError(f"the site needs {source_name} at the root of the repository")
        target = docs_dir / page_name
        new_text = _for_the_site(source.read_text(encoding="utf-8")).encode("utf-8")
        # Write only for a change of the text. `mkdocs serve` watches `docs/`, so an unconditional write
        # starts a loop: the write raises an event, the event starts a build, and the build writes again.
        if target.is_file() and target.read_bytes() == new_text:
            continue
        target.write_bytes(new_text)


def on_serve(server, config, **kwargs):
    """Watch each document at the root, so `mkdocs serve` rebuilds when you edit the real file.

    `mkdocs serve` watches `docs/` and `mkdocs.yml` only. The text lives at the root, so without this the
    server never sees an edit of DOCUMENTATION.md.
    """
    root = Path(config["config_file_path"]).parent
    for source_name in _ROOT_PAGES:
        server.watch(str(root / source_name))
    return server
