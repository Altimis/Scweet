"""Tests for output functions (CSV, JSON) — no credentials needed."""
from __future__ import annotations

import csv
import json

import pytest

from Scweet.outputs import write_csv, write_csv_auto_header, write_json, write_json_auto_append


# ── write_csv_auto_header ───────────────────────────────────────────────


def test_write_csv_auto_header_basic(tmp_path):
    path = str(tmp_path / "out.csv")
    rows = [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    header = write_csv_auto_header(path, rows)
    assert set(header) == {"a", "b"}

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)
    assert len(data) == 2
    assert data[0]["a"] == "1"


def test_write_csv_auto_header_append(tmp_path):
    path = str(tmp_path / "out.csv")
    rows1 = [{"a": 1, "b": 2}]
    write_csv_auto_header(path, rows1)

    # Append with a new column "c" — should trigger union header rewrite
    rows2 = [{"a": 5, "c": 6}]
    header = write_csv_auto_header(path, rows2, mode="a")
    assert "c" in header

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)
    assert len(data) == 2
    assert data[1]["c"] == "6"


def test_write_csv_auto_header_append_same_columns(tmp_path):
    path = str(tmp_path / "out.csv")
    rows1 = [{"x": 1, "y": 2}]
    write_csv_auto_header(path, rows1)

    rows2 = [{"x": 3, "y": 4}]
    write_csv_auto_header(path, rows2, mode="a")

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        data = list(reader)
    assert len(data) == 2


def test_write_csv_auto_header_empty_noop(tmp_path):
    path = str(tmp_path / "out.csv")
    result = write_csv_auto_header(path, [])
    assert result == []


# ── write_json / write_json_auto_append ─────────────────────────────────


def test_write_json_basic(tmp_path):
    path = str(tmp_path / "out.json")
    rows = [{"id": 1}, {"id": 2}]
    write_json(path, rows)

    data = json.loads(open(path, encoding="utf-8").read())
    assert len(data) == 2
    assert data[0]["id"] == 1


def test_write_json_auto_append_write_mode(tmp_path):
    path = str(tmp_path / "out.json")
    rows = [{"id": 1}]
    write_json_auto_append(path, rows, mode="w")

    data = json.loads(open(path, encoding="utf-8").read())
    assert len(data) == 1


def test_write_json_auto_append(tmp_path):
    path = str(tmp_path / "out.json")
    write_json_auto_append(path, [{"id": 1}], mode="w")
    write_json_auto_append(path, [{"id": 2}, {"id": 3}], mode="a")

    data = json.loads(open(path, encoding="utf-8").read())
    assert len(data) == 3
    assert data[2]["id"] == 3


def test_write_json_auto_append_to_empty_array(tmp_path):
    path = str(tmp_path / "out.json")
    open(path, "w", encoding="utf-8").write("[]")

    write_json_auto_append(path, [{"id": 99}], mode="a")
    data = json.loads(open(path, encoding="utf-8").read())
    assert len(data) == 1
    assert data[0]["id"] == 99


def test_write_json_auto_append_corrupt_fallback(tmp_path):
    path = str(tmp_path / "out.json")
    open(path, "w", encoding="utf-8").write("not valid json {{{")

    write_json_auto_append(path, [{"id": 42}], mode="a")
    data = json.loads(open(path, encoding="utf-8").read())
    assert len(data) == 1
    assert data[0]["id"] == 42


def test_write_json_auto_append_empty_rows_noop(tmp_path):
    path = str(tmp_path / "out.json")
    write_json_auto_append(path, [], mode="w")
    data = json.loads(open(path, encoding="utf-8").read())
    assert data == []


# ── client._save_output ─────────────────────────────────────────────────


def test_save_output_csv(tmp_path):
    from Scweet import Scweet, ScweetConfig

    cfg = ScweetConfig(save_dir=str(tmp_path), save_format="csv")
    s = Scweet(db_path=str(tmp_path / "state.db"), config=cfg, provision=False)
    rows = [{"tweet_id": "1", "text": "hello"}]
    s._save_output(rows, "search", "csv")
    assert (tmp_path / "search.csv").exists()


def test_save_output_json(tmp_path):
    from Scweet import Scweet, ScweetConfig

    cfg = ScweetConfig(save_dir=str(tmp_path), save_format="json")
    s = Scweet(db_path=str(tmp_path / "state.db"), config=cfg, provision=False)
    rows = [{"tweet_id": "1", "text": "hello"}]
    s._save_output(rows, "search", "json")
    path = tmp_path / "search.json"
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data) == 1


def test_save_output_both(tmp_path):
    from Scweet import Scweet, ScweetConfig

    cfg = ScweetConfig(save_dir=str(tmp_path))
    s = Scweet(db_path=str(tmp_path / "state.db"), config=cfg, provision=False)
    rows = [{"tweet_id": "1", "text": "hello"}]
    s._save_output(rows, "search", "both")
    assert (tmp_path / "search.csv").exists()
    assert (tmp_path / "search.json").exists()


def test_save_output_empty_noop(tmp_path):
    from Scweet import Scweet, ScweetConfig

    cfg = ScweetConfig(save_dir=str(tmp_path))
    s = Scweet(db_path=str(tmp_path / "state.db"), config=cfg, provision=False)
    s._save_output([], "search", "csv")
    assert not (tmp_path / "search.csv").exists()
