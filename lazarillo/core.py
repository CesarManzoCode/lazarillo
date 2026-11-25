"""Stage `core`: project declarations of the target graph (CONTRACT §2, §5; D04).

The core is the set of untrusted nodes of `graph.ndjson`; no further reduction.
"""

import json
import sys
from pathlib import Path

from . import jsonio

CORE_FORMAT = "lazarillo-core/1"


class CoreError(Exception):
    pass


def load_graph(path) -> dict[str, dict]:
    """`graph.ndjson` as name -> row."""
    path = Path(path)
    if not path.is_file():
        raise CoreError(f"missing {path} (run the graph stage first)")
    nodes = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                nodes[row["name"]] = row
    return nodes


def read_lines(path) -> list[str]:
    path = Path(path)
    if not path.is_file():
        raise CoreError(f"missing {path} (run the graph stage first)")
    with open(path, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def read_toolchain(project: Path) -> str:
    path = Path(project) / "lean-toolchain"
    if not path.is_file():
        raise CoreError(f"missing {path}")
    return path.read_text(encoding="utf-8").strip()


def core_names(nodes: dict[str, dict]) -> list[str]:
    return sorted(name for name, row in nodes.items() if not row["trusted"])


def core_json(nodes: dict[str, dict], project_decls: int, target: str, toolchain: str) -> dict:
    if target not in nodes:
        raise CoreError(f"target {target} is not in graph.ndjson")
    core = core_names(nodes)
    return {
        "format": CORE_FORMAT,
        "target": target,
        "toolchain": toolchain,
        "project_decls": project_decls,
        "closure_decls": len(nodes),
        "core_decls": len(core),
        "ratio": round(len(core) / project_decls, 6) if project_decls else 0.0,
        "core": core,
    }


def run_core(args) -> int:
    out = Path(args.out)
    try:
        nodes = load_graph(out / "graph.ndjson")
        project_decls = len(read_lines(out / "project_decls.txt"))
        data = core_json(nodes, project_decls, args.theorem, read_toolchain(Path(args.project_dir)))
    except CoreError as e:
        print(f"lazarillo: core: {e}", file=sys.stderr)
        return 1
    jsonio.write_json(out / "core.json", data)
    return 0
