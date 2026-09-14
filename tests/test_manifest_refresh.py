"""The manifest covers every operation, and a user can refresh it at will.

The failure mode this file guards: X rotates a query id, the id lives in a
lazy chunk that main.js does not carry, and the scrape silently keeps a stale
id for ever. Measured 2026-09-13: the reposters id from another source was
already one generation old while the chunk carried the current one.

The two fixtures are real captures of 2026-09-13, trimmed: the chunk-map
region of https://x.com/home, and the region of bundle.TweetEditHistory that
carries the Retweeters operation.
"""

import json
from pathlib import Path

from Scweet.manifest import (
    _DEFAULT_MANIFEST,
    _OPERATION_NAME_TO_KEY,
    _extract_chunk_script_entries,
    _fill_missing_operations,
    _scrape_missing_from_chunks,
    ManifestModel,
)

FIXTURES = Path(__file__).parent / "fixtures"
HOME_TEXT = (FIXTURES / "home_chunk_maps.html").read_text(encoding="utf-8")
CHUNK_TEXT = (FIXTURES / "chunk_with_retweeters.js").read_text(encoding="utf-8")


class _ChunkResponse:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


class _ChunkSession:
    """Serves the captured chunk for its URL and an empty file for the rest."""

    def __init__(self):
        self.fetched: list[str] = []

    def get(self, url: str, timeout: int = 0):
        self.fetched.append(url)
        if "bundle.TweetEditHistory." in url:
            return _ChunkResponse(200, CHUNK_TEXT)
        return _ChunkResponse(200, "var empty = 1;")


def test_every_operation_of_the_map_holds_a_default_id_and_an_endpoint():
    for key in _OPERATION_NAME_TO_KEY.values():
        assert _DEFAULT_MANIFEST["query_ids"].get(key), key
        assert _DEFAULT_MANIFEST["endpoints"].get(key), key
    model = ManifestModel.model_validate(_DEFAULT_MANIFEST)
    assert len(model.query_ids) == len(_OPERATION_NAME_TO_KEY)


def test_the_page_of_x_yields_the_chunk_names_and_hashes():
    entries = _extract_chunk_script_entries(HOME_TEXT)
    assert len(entries) > 400, "the real page carries hundreds of chunks"
    names = {name for name, _ in entries}
    assert "bundle.TweetEditHistory" in names
    for _, chunk_hash in entries[:50]:
        assert len(chunk_hash) in (7, 16)


def test_the_chunk_sweep_finds_the_id_that_main_js_lacks():
    session = _ChunkSession()
    query_ids: dict[str, str] = {}
    endpoints: dict[str, str] = {}
    _scrape_missing_from_chunks(
        session, HOME_TEXT, {"Retweeters": "reposters"}, query_ids, endpoints,
        timeout=5, max_fetches=30,
    )
    # The value below is read by hand from the captured chunk.
    assert query_ids["reposters"] == "iH7h2J19n7Xd1swL4cNTNg"
    assert "Retweeters" in endpoints["reposters"]


def test_the_sweep_stops_at_the_find_and_never_walks_every_chunk():
    session = _ChunkSession()
    _scrape_missing_from_chunks(
        session, HOME_TEXT, {"Retweeters": "reposters"}, {}, {},
        timeout=5, max_fetches=30,
    )
    entries = _extract_chunk_script_entries(HOME_TEXT)
    assert 0 < len(session.fetched) < min(30, len(entries)), (
        "the priority order must find the id in few fetches"
    )


def test_a_sweep_that_finds_nothing_keeps_the_bundled_id():
    class _EmptySession:
        def get(self, url, timeout=0):
            return _ChunkResponse(200, "var empty = 1;")

    query_ids: dict[str, str] = {}
    endpoints: dict[str, str] = {}
    _scrape_missing_from_chunks(
        _EmptySession(), HOME_TEXT, {"Retweeters": "reposters"}, query_ids, endpoints,
        timeout=5, max_fetches=3,
    )
    assert "reposters" not in query_ids
    _fill_missing_operations(query_ids, endpoints)
    assert query_ids["reposters"] == _DEFAULT_MANIFEST["query_ids"]["reposters"]


def test_the_client_reports_each_changed_id(tmp_path):
    """refresh_manifest returns old and new, so a user sees what rotated."""
    from Scweet.client import Scweet

    client = Scweet(db_path=str(tmp_path / "state.db"), provision=False)

    fresh = json.loads(json.dumps(_DEFAULT_MANIFEST))
    fresh["query_ids"]["search_timeline"] = "NEW_ID_AFTER_ROTATION"

    provider = client._manifest_provider
    provider.scrape_from_x_sync = lambda *, strict=False, force=False: (
        ManifestModel.model_validate(fresh)
    )
    changes = client.refresh_manifest()
    assert changes == {
        "search_timeline": {
            "old": _DEFAULT_MANIFEST["query_ids"]["search_timeline"],
            "new": "NEW_ID_AFTER_ROTATION",
        }
    }


def test_the_cli_offers_the_refresh(capsys, monkeypatch, tmp_path):
    import Scweet.cli as cli_mod
    from Scweet.cli import build_parser

    class _FakeClient:
        def refresh_manifest(self):
            return {"reposters": {"old": "aaa", "new": "bbb"}}

    monkeypatch.setattr(cli_mod, "_make_client", lambda args: _FakeClient())
    args = build_parser().parse_args(["refresh-manifest"])
    args.func(args)
    out = capsys.readouterr().out
    assert "reposters: aaa -> bbb" in out
