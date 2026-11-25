"""Command `blueprint`: calibration of the tree against a leanblueprint (CONTRACT §8; D10, D12;
RESEARCH §1).

Decisions inside the contract:
- A `%` starts a comment unless it is escaped (`\\%`); the rest of the line is dropped.
- The label of an environment is its first `\\label`; `\\lean` and `\\uses` are collected from
  the whole environment, nested environments included. Several environments with the same
  label merge their names and edges.
- A following `proof` belongs to the last labelled top-level environment of the same file;
  unlabelled environments in between do not break the link, a new file does. A `proof` is
  never a node: a `\\label` inside it (e.g. of a nested `equation`) is ignored.
- `BE` never contains a self edge `(a, a)`, as `PE` cannot.
- A missing root (label not in the blueprint, declaration not in the graph or the tree) gives
  empty sets, so the affected values are 0.0; the command still writes `calibration.json`.
"""

import re
import sys
from pathlib import Path

from . import jsonio
from .core import CoreError, load_graph, read_lines

CALIBRATION_FORMAT = "lazarillo-calibration/1"

_TOKEN = re.compile(r"\\(begin|end|label|lean|uses)\s*\{([^}]*)\}")


class BlueprintError(Exception):
    pass


# --- parser ----------------------------------------------------------------------

def strip_comments(text: str) -> str:
    out = []
    for line in text.split("\n"):
        i, cut = 0, len(line)
        while i < len(line):
            c = line[i]
            if c == "\\":
                i += 2
                continue
            if c == "%":
                cut = i
                break
            i += 1
        out.append(line[:cut])
    return "\n".join(out)


def _names(arg: str) -> list[str]:
    return [s.strip() for s in arg.split(",") if s.strip()]


def top_level_envs(text: str) -> list[dict]:
    """Top-level environments in order: {"env", "label", "lean", "uses"} (comments removed)."""
    envs, depth, cur = [], 0, None
    for m in _TOKEN.finditer(strip_comments(text)):
        cmd, arg = m.group(1), m.group(2)
        if cmd == "begin":
            if depth == 0:
                cur = {"env": arg.strip(), "label": None, "lean": [], "uses": []}
            depth += 1
        elif cmd == "end":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0:
                envs.append(cur)
                cur = None
        elif cur is not None:
            if cmd == "label":
                if cur["label"] is None and arg.strip():
                    cur["label"] = arg.strip()
            else:
                cur[cmd].extend(_names(arg))
    return envs


def parse_text(text: str, nodes: dict[str, dict]) -> None:
    """Add the nodes of one file to `nodes`: label -> {"lean": set, "uses": set}."""
    last = None
    for env in top_level_envs(text):
        if env["env"] == "proof":
            if last is not None:
                nodes[last]["uses"].update(env["uses"])
        elif env["label"] is not None:
            last = env["label"]
            node = nodes.setdefault(last, {"lean": set(), "uses": set()})
            node["lean"].update(env["lean"])
            node["uses"].update(env["uses"])


def parse_dir(tex_dir) -> dict[str, dict]:
    tex_dir = Path(tex_dir)
    if not tex_dir.is_dir():
        raise BlueprintError(f"--tex-dir is not a directory: {tex_dir}")
    nodes = {}
    for path in sorted(tex_dir.rglob("*.tex"), key=lambda p: p.relative_to(tex_dir).as_posix()):
        parse_text(path.read_text(encoding="utf-8", errors="replace"), nodes)
    return nodes


# --- calibration -----------------------------------------------------------------

def reachable(start, succ) -> set:
    seen, stack = set(), [start]
    while stack:
        u = stack.pop()
        if u in seen:
            continue
        seen.add(u)
        stack.extend(succ(u))
    return seen


def blueprint_closure(bp: dict[str, dict], root_label: str) -> set[str]:
    """`B`: labels reachable from the root label by `uses`."""
    if root_label not in bp:
        return set()
    return reachable(root_label, lambda u: bp[u]["uses"] if u in bp else ())


def graph_closure(graph: dict[str, dict], root_decl: str) -> set[str]:
    if root_decl not in graph:
        return set()
    return reachable(root_decl, lambda u: [d for d in (*graph[u]["type_deps"], *graph[u]["value_deps"])
                                           if d in graph])


def missing_in_graph(bp, b_labels, graph, root_decl) -> list[str]:
    closure = graph_closure(graph, root_decl)
    return sorted({n for lab in b_labels for n in bp[lab]["lean"]} - closure)


def labels_of(bp: dict[str, dict]) -> dict[str, set[str]]:
    out = {}
    for lab, node in bp.items():
        for n in node["lean"]:
            out.setdefault(n, set()).add(lab)
    return out


def tree_closure(tree_uses: dict[str, list[str]], root_decl: str) -> set[str]:
    """`T`: tree nodes reachable from the root declaration by `uses`."""
    if root_decl not in tree_uses:
        return set()
    return reachable(root_decl, lambda u: [v for v in tree_uses.get(u, ()) if v in tree_uses])


def projected_edges(tree_uses, t_nodes, u_set, label_map) -> set[tuple[str, str]]:
    """`PE`: label pairs joined by a `uses` path whose interior nodes are outside `U`."""
    pe = set()
    for x in sorted(t_nodes & u_set):
        ends, seen = set(), set()
        stack = list(tree_uses.get(x, ()))
        while stack:
            v = stack.pop()
            if v in u_set:
                ends.add(v)
                continue
            if v in seen or v not in t_nodes:
                continue
            seen.add(v)
            stack.extend(tree_uses.get(v, ()))
        for y in ends:
            for a in label_map[x]:
                for b in label_map[y]:
                    if a != b:
                        pe.add((a, b))
    return pe


def _ratio(num: int, den: int) -> float:
    return num / den if den else 0.0


def calibrate(bp, graph, project_decls, tree_uses, root_label, root_decl) -> dict:
    b_labels = blueprint_closure(bp, root_label)
    label_map = labels_of(bp)
    project = set(project_decls)
    u_set = {n for n in label_map if n in project}
    t_nodes = tree_closure(tree_uses, root_decl)
    pt = {lab for n in t_nodes & u_set for lab in label_map[n]}
    pb = {lab for lab in b_labels if lab in bp and bp[lab]["lean"] & project}
    pe = projected_edges(tree_uses, t_nodes, u_set, label_map)
    be = {(a, b) for a in pb for b in bp[a]["uses"] if b in pb and a != b}
    return {
        "format": CALIBRATION_FORMAT,
        "root_label": root_label,
        "root_decl": root_decl,
        "missing_in_graph": missing_in_graph(bp, b_labels & bp.keys(), graph, root_decl),
        "nodes": {"precision": _ratio(len(pt & pb), len(pt)), "recall": _ratio(len(pt & pb), len(pb))},
        "edges": {"precision": _ratio(len(pe & be), len(pe)), "recall": _ratio(len(pe & be), len(be))},
    }


def load_tree_uses(path) -> dict[str, list[str]]:
    path = Path(path)
    if not path.is_file():
        raise BlueprintError(f"missing {path} (run the tree stage first)")
    return {n["name"]: list(n["uses"]) for n in jsonio.read_json(path)["nodes"]}


def main(args) -> int:
    run = Path(args.run)
    try:
        bp = parse_dir(args.tex_dir)
        graph = load_graph(run / "graph.ndjson")
        project_decls = read_lines(run / "project_decls.txt")
        tree_uses = load_tree_uses(run / "tree.json")
    except (BlueprintError, CoreError) as e:
        print(f"lazarillo: {e}", file=sys.stderr)
        return 2
    result = calibrate(bp, graph, project_decls, tree_uses, args.root_label, args.root_decl)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    jsonio.write_json(out, result)
    return 0
