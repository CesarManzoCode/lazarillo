"""Deterministic JSON and NDJSON writers (CONTRACT §5)."""

import json
import os
from contextlib import contextmanager
from pathlib import Path


def dumps_json(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + "\n"


def dumps_ndjson_line(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")) + "\n"


@contextmanager
def _atomic(path):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        yield f
    os.replace(tmp, path)


def _write_text(path, text: str) -> None:
    with _atomic(path) as f:
        f.write(text)


def write_json(path, obj) -> None:
    _write_text(path, dumps_json(obj))


def write_ndjson(path, rows) -> None:
    with _atomic(path) as f:
        for r in rows:
            f.write(dumps_ndjson_line(r))


def write_lines(path, lines) -> None:
    with _atomic(path) as f:
        for line in lines:
            f.write(line + "\n")


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
