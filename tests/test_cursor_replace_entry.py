"""A cursor that arrives as a TimelineReplaceEntry keeps the pagination alive.

X puts the Bottom cursor in the `entries` list of the first page. From the
second page it sends a `TimelineReplaceEntry` instruction that holds a
**singular** `entry` with `entryId: cursor-bottom-0`, and the `entries` list of
that instruction is absent.

A parser that reads only `entries` therefore loses the cursor at page 2 and
ends a chain after about 40 tweets, while the range still holds thousands. That
failure is easy to write by accident: it happened in a hand-written probe on
2026-09-15, and it produced two false findings before the real code path
refuted them.

The fixture is a trimmed real answer of X, captured 2026-09-15.
"""

import json
from pathlib import Path

from Scweet.api_engine import ApiEngine

FIXTURE = Path(__file__).parent / "fixtures" / "search_page2_replace_entry_cursor.json"


def _engine() -> ApiEngine:
    return ApiEngine(config={}, accounts_repo=None, manifest_provider=None)


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_the_fixture_holds_the_cursor_only_in_a_singular_entry():
    """Guard the fixture itself: if it ever carries the cursor in `entries`,
    the test below stops proving anything."""
    instructions = _payload()["data"]["search_by_raw_query"]["search_timeline"]["timeline"][
        "instructions"
    ]
    in_entries = [
        e
        for i in instructions
        for e in (i.get("entries") or [])
        if str(e.get("entryId", "")).startswith("cursor-")
    ]
    in_singular = [
        i.get("entry")
        for i in instructions
        if isinstance(i.get("entry"), dict)
        and str(i["entry"].get("entryId", "")).startswith("cursor-")
    ]
    assert not in_entries, "the fixture must carry no cursor in the entries list"
    assert in_singular, "the fixture must carry the cursor in a singular entry"


def test_the_parser_finds_a_cursor_that_arrives_as_a_replace_entry():
    tweets, cursor = _engine()._extract_tweets_and_cursor(_payload())
    assert tweets, "the page holds tweets"
    assert cursor, "the parser must find the cursor of a TimelineReplaceEntry"


def test_the_profile_parser_finds_it_too():
    """The profile timeline uses its own envelope and the same instruction shape."""
    instructions = _payload()["data"]["search_by_raw_query"]["search_timeline"]["timeline"][
        "instructions"
    ]
    profile_envelope = {
        "data": {"user": {"result": {"timeline": {"timeline": {"instructions": instructions}}}}}
    }
    tweets, cursor = _engine()._extract_profile_tweets_and_cursor(profile_envelope)
    assert tweets
    assert cursor
