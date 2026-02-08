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
