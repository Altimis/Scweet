from __future__ import annotations

import csv
import json
import os
from pathlib import Path
from typing import Union


def write_csv(path: str, rows: Union[list[dict], list[list]], header: list[str], mode: str = "w") -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    with target.open(mode, newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        if mode == "w":
            writer.writerow(header)

        for row in rows or []:
            if isinstance(row, dict):
                values = []
                for key in header:
                    value = row.get(key, "")
                    if value is None:
                        value = ""
                    elif isinstance(value, (dict, list, tuple, set)):
                        value = json.dumps(value, ensure_ascii=False, default=str)
                    values.append(value)
                writer.writerow(values)
                continue
            if isinstance(row, (list, tuple)):
                values = []
                for value in row:
                    if value is None:
                        value = ""
                    elif isinstance(value, (dict, list, tuple, set)):
                        value = json.dumps(value, ensure_ascii=False, default=str)
                    values.append(value)
                writer.writerow(values)
                continue
            raise TypeError(f"Unsupported CSV row type: {type(row)!r}")


def write_csv_auto_header(path: str, rows: list[dict], *, mode: str = "w") -> list[str]:
    """Write dict rows to CSV with a computed header.

    If mode="a" and the file exists, this function will:
    - append if no new columns are needed
    - otherwise rewrite the file with a union header to avoid dropping fields
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        if mode == "w" and not target.exists():
            target.touch()
        return []

    new_header = sorted({str(key) for row in rows for key in (row or {}).keys()})

    if mode == "a" and target.exists() and target.stat().st_size > 0:
        with target.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            existing_header = list(reader.fieldnames or [])
            existing_rows = list(reader)

        if not existing_header:
            write_csv(str(target), rows, new_header, mode="w")
            return new_header

        union_header = list(existing_header)
        for key in new_header:
            if key not in existing_header:
                union_header.append(key)

        if union_header != existing_header:
            write_csv(str(target), existing_rows + rows, union_header, mode="w")
            return union_header

        write_csv(str(target), rows, existing_header, mode="a")
        return existing_header

    write_csv(str(target), rows, new_header, mode="w")
    return new_header


def write_json(path: str, rows: list[dict]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    payload = rows or []
    if not isinstance(payload, list):
        raise TypeError("rows must be a list of dicts")
    for row in payload:
        if not isinstance(row, dict):
            raise TypeError("rows must be a list of dicts")

    with target.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False)


def write_json_auto_append(path: str, rows: list[dict], *, mode: str = "w") -> None:
    """Write JSON array output with optional append support.

    - mode="w": write a full JSON array (overwrites)
    - mode="a": append elements to an existing JSON array in-place (resume-safe)
    """

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    if mode not in {"w", "a"}:
        raise ValueError("mode must be 'w' or 'a'")

    payload = rows or []
    if not isinstance(payload, list):
        raise TypeError("rows must be a list of dicts")
    for row in payload:
        if not isinstance(row, dict):
            raise TypeError("rows must be a list of dicts")

    if not payload:
        if mode == "w" or not target.exists():
            target.write_text("[]", encoding="utf-8")
        return

    if mode == "w" or not target.exists() or target.stat().st_size == 0:
        write_json(str(target), payload)
        return

    def _rewrite_with_merge(new_rows: list[dict]) -> None:
        """Fallback path: try to preserve existing JSON array contents."""

        merged: list[dict] = []
        try:
            existing_text = target.read_text(encoding="utf-8")
            existing_payload = json.loads(existing_text) if existing_text.strip() else []
            if isinstance(existing_payload, list):
                merged.extend([item for item in existing_payload if isinstance(item, dict)])
        except Exception:
            merged = []
        merged.extend(new_rows)
        write_json(str(target), merged)

    # mode="a": in-place append to an existing JSON array.
    try:
        with target.open("rb+") as handle:
            handle.seek(0, os.SEEK_END)
            end_pos = handle.tell()
            if end_pos <= 0:
                write_json(str(target), payload)
                return

            # Find last non-whitespace byte (should be ']').
            pos = end_pos - 1
            last_byte = b""
            while pos >= 0:
                handle.seek(pos)
                last_byte = handle.read(1)
                if last_byte not in b" \t\r\n":
                    break
                pos -= 1
            if pos < 0 or last_byte != b"]":
                # Unexpected/corrupt file; fall back to rewrite.
                _rewrite_with_merge(payload)
                return

            closing_bracket_pos = pos

            # Find previous non-whitespace byte before closing bracket to detect empty array.
            prev_pos = closing_bracket_pos - 1
            prev_byte = b""
            while prev_pos >= 0:
                handle.seek(prev_pos)
                prev_byte = handle.read(1)
                if prev_byte not in b" \t\r\n":
                    break
                prev_pos -= 1

            is_empty_array = prev_pos >= 0 and prev_byte == b"["

            # Truncate away closing bracket and any trailing whitespace.
            handle.truncate(closing_bracket_pos)
            handle.seek(closing_bracket_pos)

            prefix = b"" if is_empty_array else b","
            chunks = [json.dumps(row, ensure_ascii=False).encode("utf-8") for row in payload]
            handle.write(prefix + b",".join(chunks) + b"]\n")
    except Exception:
        _rewrite_with_merge(payload)
