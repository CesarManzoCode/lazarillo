"""Stage `tree`: explanation tree over the core, structure and goal states (CONTRACT §2, §5; D05, D10;
RESEARCH §3.10).

Decisions inside the contract:
- `uses` of a node never lists the node itself (an inductive is in its own `all` block).
- A node whose module has no source file, or that `Goals.lean` does not report, keeps
  `file`/`range`/`statement` null, `tactic_proof` false and `goals` empty.
- `nodes` are ordered by depth, then name; `children` and `uses` by name.
- After the structure, `explain.explain_tree` fills `llm` and `explanation` and the stage
  writes `tree.html`; if the model step fails, the stage fails and writes neither file.
"""

import json
import sys
from collections import deque
from pathlib import Path

from . import explain, jsonio
from .audit import module_file, source_roots
from .config import REPO, ConfigError, lean_env
from .core import CoreError, load_graph
from .kernels import KernelsError, run_logged

TREE_FORMAT = "lazarillo-tree/1"
GOALS_LEAN = REPO / "lean" / "Goals.lean"


class TreeError(Exception):
    pass


# --- structure -------------------------------------------------------------------

def _project(nodes: dict[str, dict], name: str) -> bool:
    return name in nodes and not nodes[name]["trusted"]


def collapsed_uses(nodes: dict[str, dict], name: str) -> list[str]:
    """Direct non-internal project dependencies of `name`; an internal dependency is replaced
    by the non-internal project declarations reachable from it through internals only (§2)."""
    row = nodes[name]
    out, seen = set(), set()
    stack = [d for d in (*row["type_deps"], *row["value_deps"]) if _project(nodes, d)]
    while stack:
        d = stack.pop()
        if d in seen:
            continue
        seen.add(d)
        dep = nodes[d]
        if not dep["internal"]:
            out.add(d)
            continue
        stack.extend(e for e in (*dep["type_deps"], *dep["value_deps"]) if _project(nodes, e))
    out.discard(name)
    return sorted(out)


def bfs(nodes: dict[str, dict], target: str, depth_limit) -> dict[str, dict]:
    """name -> {"depth", "parent", "uses"} for the nodes of the tree. Each level is expanded
    in alphabetical order, so a node's parent is the first one by name at the previous depth."""
    if not _project(nodes, target):
        raise TreeError(f"target {target} is not in the core")
    if nodes[target]["internal"]:
        raise TreeError(f"target {target} is internal")
    uses = {}
    tree = {target: {"depth": 0, "parent": None}}
    level, depth = [target], 0
    while level:
        if depth_limit != "all" and depth >= depth_limit:
            break
        nxt = []
        for u in level:
            uses[u] = collapsed_uses(nodes, u)
            for v in uses[u]:
                if v not in tree:
                    tree[v] = {"depth": depth + 1, "parent": u}
                    nxt.append(v)
        level, depth = sorted(nxt), depth + 1
    for name, info in tree.items():
        u = uses[name] if name in uses else collapsed_uses(nodes, name)
        info["uses"] = [v for v in u if v in tree]
    return tree


def structure(nodes: dict[str, dict], target: str, depth_limit) -> list[dict]:
    """Tree nodes with the graph fields; source fields empty."""
    tree = bfs(nodes, target, depth_limit)
    children = {name: [] for name in tree}
    for name, info in tree.items():
        if info["parent"] is not None:
            children[info["parent"]].append(name)
    out = []
    for name in sorted(tree, key=lambda n: (tree[n]["depth"], n)):
        info = tree[name]
        out.append({
            "name": name,
            "kind": nodes[name]["kind"],
            "module": nodes[name]["module"],
            "file": None,
            "range": None,
            "depth": info["depth"],
            "parent": info["parent"],
            "children": sorted(children[name]),
            "uses": info["uses"],
            "statement": None,
            "tactic_proof": False,
            "goals": [],
            "explanation": None,
        })
    return out


# --- goal states -----------------------------------------------------------------

def locate(tree_nodes: list[dict], project: Path) -> dict[str, tuple[str, str]]:
    """Fill `file` (relative to PROJECT_DIR) by module, with the rule of `source_scan`.
    Returns file -> (absolute path, module), one entry per distinct file, sorted by file."""
    project = Path(project)
    roots = source_roots(project)
    cache, files = {}, {}
    for n in tree_nodes:
        mod = n["module"]
        if mod not in cache:
            path = module_file(roots, project, mod)
            cache[mod] = None
            if path is not None:
                try:
                    rel = path.resolve().relative_to(project.resolve()).as_posix()
                except ValueError:
                    rel = path.as_posix()
                cache[mod] = rel
                files.setdefault(rel, (str(path.resolve()), mod))
        n["file"] = cache[mod]
    return dict(sorted(files.items()))


def read_goals(path: Path) -> dict[str, dict]:
    """`Goals.lean` output as name -> row."""
    rows = {}
    if not Path(path).is_file():
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                rows[row["name"]] = row
    return rows


def merge_goals(tree_nodes: list[dict], by_file: dict[str, dict[str, dict]]) -> None:
    """Fill `range`, `statement`, `tactic_proof` and `goals` from the rows of each node's file."""
    for n in tree_nodes:
        row = by_file.get(n["file"], {}).get(n["name"])
        if row is None:
            continue
        n["range"] = row.get("range")
        n["statement"] = row.get("statement")
        tactics = row.get("tactics") or []
        n["tactic_proof"] = bool(tactics)
        n["goals"] = [{"tactic": t["tactic"], "range": t["range"], "before": list(t["before"])}
                      for t in tactics]


def run_goals(project: Path, file: str, module: str, dest: Path, log: Path, env: dict) -> int:
    """`lake env lean --run lean/Goals.lean <dest> <file> <module>` from PROJECT_DIR."""
    cmd = ["lake", "env", "lean", "--run", str(GOALS_LEAN), str(dest), file, module]
    return run_logged(cmd, project, env, log)


def collect_goals(files: dict[str, tuple[str, str]], project: Path, out: Path, run=run_goals,
                  env: dict | None = None) -> dict[str, dict[str, dict]]:
    """One `Goals.lean` per distinct file, in series; file -> name -> row."""
    work = out / "work" / "tree"
    work.mkdir(parents=True, exist_ok=True)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    env = env if env is not None else lean_env()
    by_file = {}
    for i, (rel, (path, module)) in enumerate(files.items()):
        dest = work / f"goals-{i:04d}.ndjson"
        log = out / "logs" / f"tree-goals-{i:04d}.log"
        dest.unlink(missing_ok=True)
        code = run(project, path, module, dest, log, env)
        if code != 0:
            print(f"lazarillo: tree: Goals.lean exited {code} on {rel} (see {log})", file=sys.stderr)
        by_file[rel] = read_goals(dest)
    return by_file


def tree_json(args, tree_nodes: list[dict], llm: dict) -> dict:
    return {
        "format": TREE_FORMAT,
        "target": args.theorem,
        "depth_limit": args.depth,
        "explain_depth": args.explain_depth,
        "llm": llm,
        "nodes": tree_nodes,
    }


def run_tree(args, run=run_goals, explainer=explain.explain_tree) -> int:
    out = Path(args.out).resolve()
    project = Path(args.project_dir).resolve()
    try:
        nodes = load_graph(out / "graph.ndjson")
        tree_nodes = structure(nodes, args.theorem, args.depth)
        files = locate(tree_nodes, project)
        merge_goals(tree_nodes, collect_goals(files, project, out, run=run))
        llm = explainer(tree_nodes, args.explain_depth, out)
    except (TreeError, CoreError, KernelsError, ConfigError, explain.ExplainError) as e:
        print(f"lazarillo: tree: {e}", file=sys.stderr)
        return 1
    data = tree_json(args, tree_nodes, llm)
    jsonio.write_json(out / "tree.json", data)
    explain.write_tree_html(out / "tree.html", data)
    return 0
