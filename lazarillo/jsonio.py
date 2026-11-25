"""Deterministic JSON and NDJSON writers (CONTRACT §5)."""

import json
import os
from pathlib import Path


def dumps_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def dumps_ndjson_line(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


def _write_text(path, text: str) -> None:
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    os.replace(tmp, path)


def write_json(path, obj) -> None:
    _write_text(path, dumps_json(obj))


def write_ndjson(path, rows) -> None:
    _write_text(path, "".join(dumps_ndjson_line(r) for r in rows))


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
