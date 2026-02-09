from __future__ import annotations

import csv
import json
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
                writer.writerow([row.get(key, "") for key in header])
                continue
            if isinstance(row, (list, tuple)):
                writer.writerow(list(row))
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
