"""Stage `core`: project declarations of the target graph (CONTRACT §2, §5; D04).

The core is the set of untrusted nodes of `graph.ndjson`; no further reduction.
`graph.ndjson` and `project_decls.txt` are read line by line: the stage keeps only the
core names and two counters, never the graph.
"""

import json
import sys
from pathlib import Path

from . import jsonio

CORE_FORMAT = "lazarillo-core/1"


class CoreError(Exception):
    pass


def _missing(path: Path) -> CoreError:
    return CoreError(f"missing {path} (run the graph stage first)")


def _rows(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def iter_graph(path):
    """Rows of `graph.ndjson`, one at a time."""
    path = Path(path)
    if not path.is_file():
        raise _missing(path)
    return _rows(path)


def load_graph(path, keep=None) -> dict[str, dict]:
    """`graph.ndjson` as name -> row.

    With `keep(row)`, only the rows it accepts are retained and their `type_deps` and
    `value_deps` are cut to retained names. The file is read twice in stream (names first,
    rows second) and every retained name is one shared string, so memory follows the
    retained rows, not the graph."""
    if keep is None:
        return {row["name"]: row for row in iter_graph(path)}
    names = {}
    for row in iter_graph(path):
        if keep(row):
            names[row["name"]] = row["name"]
    nodes = {}
    for row in iter_graph(path):
        name = names.get(row["name"])
        if name is None:
            continue
        row["name"] = name
        row["type_deps"] = [names[d] for d in row["type_deps"] if d in names]
        row["value_deps"] = [names[d] for d in row["value_deps"] if d in names]
        nodes[name] = row
    return nodes


def project_or(*extra: str):
    """`keep` for `load_graph`: untrusted rows and the rows named in `extra`."""
    return lambda row: not row["trusted"] or row["name"] in extra


def read_lines(path) -> list[str]:
    path = Path(path)
    if not path.is_file():
        raise _missing(path)
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def count_lines(path) -> int:
    path = Path(path)
    if not path.is_file():
        raise _missing(path)
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def read_toolchain(project: Path) -> str:
    path = Path(project) / "lean-toolchain"
    if not path.is_file():
        raise CoreError(f"missing {path}")
    return path.read_text(encoding="utf-8").strip()


def core_names(nodes: dict[str, dict]) -> list[str]:
    return sorted(name for name, row in nodes.items() if not row["trusted"])


def core_record(closure_decls: int, core: list[str], project_decls: int, target: str, toolchain: str) -> dict:
    return {
        "format": CORE_FORMAT,
        "target": target,
        "toolchain": toolchain,
        "project_decls": project_decls,
        "closure_decls": closure_decls,
        "core_decls": len(core),
        "ratio": round(len(core) / project_decls, 6) if project_decls else 0.0,
        "core": core,
    }


def core_json(nodes: dict[str, dict], project_decls: int, target: str, toolchain: str) -> dict:
    if target not in nodes:
        raise CoreError(f"target {target} is not in graph.ndjson")
    return core_record(len(nodes), core_names(nodes), project_decls, target, toolchain)


def stream_core(graph_path, project_decls: int, target: str, toolchain: str) -> dict:
    """`core_json` over `graph.ndjson` read in stream."""
    closure, core, found = 0, [], False
    for row in iter_graph(graph_path):
        closure += 1
        found = found or row["name"] == target
        if not row["trusted"]:
            core.append(row["name"])
    if not found:
        raise CoreError(f"target {target} is not in graph.ndjson")
    core.sort()  # already sorted by the graph stage; in place, no copy
    return core_record(closure, core, project_decls, target, toolchain)


def run_core(args) -> int:
    out = Path(args.out)
    try:
        project_decls = count_lines(out / "project_decls.txt")
        data = stream_core(out / "graph.ndjson", project_decls, args.theorem,
                           read_toolchain(Path(args.project_dir)))
    except CoreError as e:
        print(f"lazarillo: core: {e}", file=sys.stderr)
        return 1
    jsonio.write_json(out / "core.json", data)
    return 0
