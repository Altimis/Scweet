"""DOCUMENTATION.md describes the library of this release, and not an older one.

Each test below failed at least once on 2026-09-21, before the audit corrected the document. A release that
adds a method, a setting, a flag, an exception or a field of a record now fails here until the document names
it.

The tests read the code and never a list written by hand. A list by hand becomes wrong in the same way that
the document became wrong.
"""

from __future__ import annotations

import ast
import inspect
import re
from pathlib import Path

import pytest

from Scweet import exceptions as scweet_exceptions
from Scweet.client import Scweet
from Scweet.config import ScweetConfig

_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def doc() -> str:
    return (_ROOT / "DOCUMENTATION.md").read_text(encoding="utf-8")


def _section(doc: str, title: str) -> str:
    """The text of one section, from its heading to the next heading of the same level."""
    assert f"## {title}" in doc, f"the document holds no section {title!r}"
    return doc.split(f"## {title}", 1)[1].split("\n## ", 1)[0]


class TestThePublicSurface:
    def test_every_method_of_the_client_appears(self, doc):
        methods = [m for m in dir(Scweet) if not m.startswith("_") and callable(getattr(Scweet, m))]
        # An async method carries the prefix `a` and the same name, so the document covers the pair once.
        sync = [m for m in methods if not (m.startswith("a") and m[1:] in methods)]
        missing = sorted(m for m in sync if f"{m}(" not in doc)
        assert missing == [], f"the document names no {missing}"

    def test_every_field_of_the_configuration_appears(self, doc):
        missing = sorted(f for f in ScweetConfig.model_fields if f not in doc)
        assert missing == [], f"the table of the configuration holds no {missing}"

    def test_every_default_of_the_configuration_is_correct(self, doc):
        """A default in the document that the code does not hold sends a user to the wrong value.

        Read the row of the table of the configuration only. A method also documents a parameter of the same
        name, and its default is "config value", which means the value of the configuration.
        """
        section = _section(doc, "Configuration Reference")
        wrong = []
        for name, field in ScweetConfig.model_fields.items():
            # A cell of a type holds an escaped pipe, as in `str \| dict \| None`. Split on a pipe that no
            # backslash precedes.
            for line in section.splitlines():
                if not line.startswith(f"| `{name}`"):
                    continue
                cells = re.split(r"(?<!\\)\|", line)
                if len(cells) < 4:
                    continue
                stated = cells[3].strip().strip("`").strip()
                if stated in ("", "-", "—"):
                    break
                real = str(field.default)
                # `"auto"` in the document against `ApiHttpMode.AUTO` in the code is one value.
                if stated.strip("\"'").lower() in (real.lower(), real.split(".")[-1].lower()):
                    break
                if stated.replace(",", "") == real:
                    break
                # `2592000.0` for a field of the type float against `2592000` in the code is one value.
                try:
                    if float(stated.replace(",", "")) == float(real):
                        break
                except ValueError:
                    pass
                wrong.append((name, stated, real))
                break
        assert wrong == [], f"the document states a wrong default: {wrong}"


class TestTheErrorsAUserCatches:
    def test_every_exception_class_appears(self, doc):
        classes = sorted(
            name
            for name, obj in vars(scweet_exceptions).items()
            if inspect.isclass(obj) and issubclass(obj, Exception)
        )
        section = _section(doc, "Error Handling")
        missing = [c for c in classes if c not in section]
        assert missing == [], f"the section Error Handling names no {missing}"

    def test_the_document_names_the_import_that_works(self, doc):
        """Eight classes reach the top level, and the rest need the module. A wrong path fails at once."""
        section = _section(doc, "Error Handling")
        import Scweet as package

        for name in re.findall(r"\b([A-Z][A-Za-z]*(?:Error|Exhausted|Failed))\b", section):
            if not hasattr(scweet_exceptions, name):
                continue
            if hasattr(package, name):
                continue
            # The class needs the module, so the section must show that path.
            assert "from Scweet.exceptions import" in section, (
                f"{name} does not reach the top level, and the section shows no other path"
            )


class TestTheCommandLine:
    def test_every_flag_appears(self, doc):
        source = (_ROOT / "Scweet" / "cli.py").read_text(encoding="utf-8")
        flags = sorted(set(re.findall(r'add_argument\(\s*"(--[a-z0-9-]+)"', source)))
        missing = [f for f in flags if f not in doc]
        assert missing == [], f"the document names no {missing}"

    def test_every_subcommand_appears(self, doc):
        source = (_ROOT / "Scweet" / "cli.py").read_text(encoding="utf-8")
        subcommands = sorted(set(re.findall(r'add_parser\(\s*"([a-z-]+)"', source)))
        section = _section(doc, "CLI")
        missing = [c for c in subcommands if c not in section]
        assert missing == [], f"the section CLI names no {missing}"


class TestTheShapeOfARow:
    def test_every_field_of_a_tweet_record_appears(self, doc):
        from Scweet.models import TweetRecord

        section = _section(doc, "Output Schemas")
        missing = sorted(f for f in TweetRecord.model_fields if f not in section)
        assert missing == [], f"the section Output Schemas names no {missing}"

    def test_the_section_shows_one_row(self, doc):
        """A reader of 894 words about the shape of a row needs to see one row."""
        section = _section(doc, "Output Schemas")
        assert "```" in section, "the section holds no example of a row"


class TestEveryExampleIsValidPython:
    def test_every_block_parses(self, doc):
        blocks = re.findall(r"```python\n(.*?)```", doc, re.S)
        assert len(blocks) > 30, "the document lost its examples"
        bad = []
        for index, block in enumerate(blocks, start=1):
            try:
                ast.parse(block)
            except SyntaxError as error:
                bad.append((index, str(error)))
        assert bad == [], f"these blocks do not parse: {bad}"

    def test_no_example_calls_a_method_that_does_not_exist(self, doc):
        """The table of the migration names the methods of version 4, so read only the blocks."""
        blocks = re.findall(r"```python\n(.*?)```", doc, re.S)
        ghosts = set()
        for block in blocks:
            for name in re.findall(r"\bs\.([a-z_]+)\(", block):
                if not hasattr(Scweet, name):
                    ghosts.add(name)
        assert ghosts == set(), f"an example calls {sorted(ghosts)}, which the client does not hold"

    def test_no_example_passes_an_argument_that_the_method_refuses(self, doc):
        blocks = re.findall(r"```python\n(.*?)```", doc, re.S)
        problems = set()
        for block in blocks:
            for call in re.finditer(r"\bs\.(a?[a-z_]+)\(([^)]*)\)", block, re.S):
                name, arguments = call.group(1), call.group(2)
                method = getattr(Scweet, name, None)
                if method is None or not callable(method):
                    continue
                try:
                    signature = inspect.signature(method)
                except (TypeError, ValueError):
                    continue
                if any(p.kind == p.VAR_KEYWORD for p in signature.parameters.values()):
                    continue
                for keyword in re.findall(r"(\w+)\s*=", arguments):
                    if keyword not in signature.parameters:
                        problems.add(f"{name}(… {keyword}=…)")
        assert problems == set(), f"an example passes an argument that the method refuses: {problems}"


class TestOneSubjectHoldsOneSection:
    def test_the_manifest_holds_one_section(self, doc):
        """Two sections described the query ids, and the second named no way to refresh them in a run."""
        headings = re.findall(r"^## (.+)$", doc, re.M)
        about_manifest = [h for h in headings if "Query ID" in h or "Manifest" in h]
        assert len(about_manifest) == 1, f"two sections describe the manifest: {about_manifest}"

    def test_that_section_names_the_method_and_the_setting(self, doc):
        """A user needs both: the refresh at startup, and the refresh during a run."""
        section = _section(doc, "Manifest Refresh")
        assert "manifest_scrape_on_init" in section
        assert "refresh_manifest()" in section
        assert "scweet refresh-manifest" in section
