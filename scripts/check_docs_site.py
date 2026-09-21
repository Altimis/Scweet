"""Prove that the built site holds the text of the repository.

The workflow and a contributor run this same file, so the check on a machine and the check in CI cannot
disagree. Run it after `mkdocs build`.

It answers three questions:

1. Does every page of the navigation exist in `site/`?
2. Does the page of the reference hold every section of `DOCUMENTATION.md`?
3. Does any page hold a link to a file that the site does not serve?
"""

from __future__ import annotations

import html
import os
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SITE = _ROOT / "site"

# The page of the site, and the file at the root that holds its text.
_PAGES = {
    "documentation": "DOCUMENTATION.md",
    "changelog": "CHANGELOG.md",
    "contributing": "CONTRIBUTING.md",
}


def _fail(message: str) -> None:
    print(f"FAIL: {message}")
    sys.exit(1)


def main() -> None:
    if not _SITE.is_dir():
        _fail("site/ is absent. Run `mkdocs build --strict` first.")

    # 1. every page exists
    for page in ["index", *_PAGES]:
        name = "index.html" if page == "index" else f"{page}/index.html"
        if not (_SITE / name).is_file():
            _fail(f"the site holds no page {name}")
    print(f"ok   every page of the navigation exists ({1 + len(_PAGES)} pages)")

    # 2. the reference holds every section of the file at the root
    for page, source in _PAGES.items():
        root_text = (_ROOT / source).read_text(encoding="utf-8")
        built = (_SITE / page / "index.html").read_text(encoding="utf-8")
        heads = [line[3:].strip() for line in root_text.splitlines() if line.startswith("## ")]
        # The builder escapes `&` into `&amp;` and leaves an apostrophe as it is. `html.escape` with
        # `quote=False` therefore gives the form that the page holds.
        missing = [h for h in heads if html.escape(h, quote=False) not in built]
        if missing:
            _fail(f"the page {page} misses these sections of {source}: {missing}")
        print(f"ok   {page} holds all {len(heads)} sections of {source}")

    # 3. no page links to a file that the site does not serve
    served = {p.relative_to(_SITE).as_posix() for p in _SITE.rglob("*") if p.is_file()}
    broken: list[str] = []
    for page_file in _SITE.rglob("index.html"):
        text = page_file.read_text(encoding="utf-8")
        here = page_file.parent.relative_to(_SITE)
        for href in re.findall(r'href="([^"]+)"', text):
            if href.startswith(("http", "#", "mailto:", "//")):
                continue
            # An anchor points inside a page. Keep the path and drop the anchor.
            path_part = href.split("#", 1)[0]
            if not path_part:
                continue
            # `os.path.normpath` resolves a `..` segment, which Material uses for every asset.
            target = os.path.normpath((here / path_part).as_posix()).strip("/")
            candidates = {target, f"{target}/index.html", f"{target}.html"}
            if target in ("", ".") or candidates & served:
                continue
            broken.append(f"{here.as_posix() or 'index'} -> {href}")
    if broken:
        _fail(f"these links reach no page of the site: {sorted(set(broken))[:10]}")
    print("ok   every internal link reaches a page of the site")

    print("\nThe site is complete and it holds the text of the repository.")


if __name__ == "__main__":
    main()
