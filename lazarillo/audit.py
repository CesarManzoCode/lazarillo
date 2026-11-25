"""Stage `audit`: axioms, uses, source scan, statement, semantic frontier and reference
fidelity (CONTRACT §2, §5; D09, D17; RESEARCH §3.4, §3.5).

Decisions inside the contract:
- `statement_decls` and `frontier` start from the project constants of the target's type,
  so the target itself is not listed; traversal never enters the trusted base.
- When comparing fingerprints with the reference, a `thm` compares only its type: by §2
  every theorem of a reference is stated with `sorry`, so its value never matches.
"""

import json
import re
import shutil
import subprocess
import sys
import tomllib
from collections import deque
from pathlib import Path

from . import jsonio
from .config import ALLOWED_AXIOMS, lean_env
from .core import CoreError, load_graph
from .graph import GraphError, Olean, run_extractor

AUDIT_FORMAT = "lazarillo-audit/1"
REFERENCE_DIR = "reference"
REFERENCE_SOURCE = "reference/Reference.lean"
REFERENCE_EXPORT = "reference/reference.ndjson"
REFERENCE_MODULE = "LazarilloRef"
TRUSTED_ROOTS = ("Mathlib", "Init", "Std", "Lean")

NATIVE_MARKERS = ("native", "ofReduceBool", "ofReduceNat", "trustCompiler")
VALUE_KINDS = ("def", "opaque", "inductive", "ctor", "rec")

TOKEN_RE = re.compile(r"(?<![\w.'])(sorry|admit|native_decide)(?![\w'])")
AXIOM_LINE_RE = re.compile(r"^\s*((private|protected|noncomputable|unsafe)\s+)*axiom\s")
IMPORT_RE = re.compile(r"^\s*(?:(?:public|meta)\s+)*import\s+(.*)$")
HEADER_RE = re.compile(r"^\s*(module|prelude)\s*$")
_OPEN_RE = re.compile(r"/-|--")
_NEST_RE = re.compile(r"/-|-/")


class AuditError(Exception):
    pass


# --- graph facts -----------------------------------------------------------------

def axioms(nodes: dict[str, dict]) -> list[str]:
    return sorted(n for n, r in nodes.items() if r["kind"] == "axiom")


def uses(nodes: dict[str, dict]) -> dict:
    axs = axioms(nodes)
    return {
        "sorry": "sorryAx" in nodes,
        "native_decide": [a for a in axs if any(m in a for m in NATIVE_MARKERS)],
        "project_axioms": [a for a in axs if not nodes[a]["trusted"]],
    }


def _project_closure(nodes: dict[str, dict], target: str, follow_value) -> list[str]:
    """Project nodes reachable from the project constants of the target's type; type edges
    always, value edges when `follow_value(row)`; trusted nodes are never entered."""
    if target not in nodes:
        raise AuditError(f"target {target} is not in graph.ndjson")

    def project(name):
        row = nodes.get(name)
        return row is not None and not row["trusted"]

    start = [d for d in nodes[target]["type_deps"] if project(d)]
    seen = set(start)
    queue = deque(start)
    while queue:
        row = nodes[queue.popleft()]
        deps = list(row["type_deps"])
        if follow_value(row):
            deps += row["value_deps"]
        for d in deps:
            if d not in seen and project(d):
                seen.add(d)
                queue.append(d)
    return sorted(seen)


def statement_decls(nodes: dict[str, dict], target: str) -> list[str]:
    return _project_closure(nodes, target, lambda row: False)


def frontier(nodes: dict[str, dict], target: str) -> list[str]:
    return _project_closure(nodes, target, lambda row: row["kind"] in VALUE_KINDS)


def core_lemmas(nodes: dict[str, dict]) -> list[dict]:
    return [{"name": n, "module": r["module"], "kind": r["kind"]}
            for n, r in sorted(nodes.items())
            if not r["trusted"] and not r["internal"] and r["kind"] == "thm"]


# --- sources ---------------------------------------------------------------------

def strip_comments(text: str) -> str:
    """Remove `--` line comments and nested `/- … -/` block comments, keeping line breaks."""
    out, pos, n = [], 0, len(text)
    while True:
        m = _OPEN_RE.search(text, pos)
        if m is None:
            out.append(text[pos:])
            break
        out.append(text[pos:m.start()])
        if m.group() == "--":
            j = text.find("\n", m.end())
            if j < 0:
                break
            pos = j
            continue
        depth, i = 1, m.end()
        while depth:
            k = _NEST_RE.search(text, i)
            if k is None:
                i = n
                break
            depth += 1 if k.group() == "/-" else -1
            i = k.end()
        out.append(" " + "\n" * text.count("\n", m.start(), i))
        pos = i
    return "".join(out)


def imports_of(stripped: str) -> list[str]:
    """Modules of `import`, `public import` and `meta import` lines, in order."""
    mods = []
    for line in stripped.splitlines():
        m = IMPORT_RE.match(line)
        if m:
            mods += [t for t in m.group(1).split() if t != "all"]
    return mods


def scan_text(stripped: str) -> dict:
    counts = {"sorry": 0, "admit": 0, "native_decide": 0}
    for m in TOKEN_RE.finditer(stripped):
        counts[m.group(1)] += 1
    counts["axiom"] = sum(1 for line in stripped.splitlines() if AXIOM_LINE_RE.match(line))
    return counts


def source_roots(project: Path) -> list[Path]:
    """PROJECT_DIR, then each `srcDir` of its `lakefile.toml` (package, libraries, executables)."""
    project = Path(project)
    roots = [project]
    lakefile = project / "lakefile.toml"
    if lakefile.is_file():
        with open(lakefile, "rb") as f:
            cfg = tomllib.load(f)
        dirs = [cfg.get("srcDir")]
        for key in ("lean_lib", "lean_exe"):
            dirs += [t.get("srcDir") for t in cfg.get(key, []) if isinstance(t, dict)]
        for d in dirs:
            if isinstance(d, str) and (project / d) not in roots:
                roots.append(project / d)
    return roots


def module_file(roots: list[Path], project: Path, module: str) -> Path | None:
    """First `A/B.lean` under a source root that is not inside `.lake/`."""
    rel = Path(*module.split(".")).with_suffix(".lean")
    for root in roots:
        p = root / rel
        if p.is_file():
            try:
                parts = p.resolve().relative_to(Path(project).resolve()).parts
            except ValueError:
                parts = p.parts
            if ".lake" not in parts:
                return p
    return None


def project_modules(project: Path, module: str) -> list[tuple[str, Path]]:
    """`module` and every module it imports transitively that has a source file, depth first."""
    roots = source_roots(project)
    seen, out = set(), []

    def visit(mod):
        if mod in seen:
            return
        seen.add(mod)
        path = module_file(roots, project, mod)
        if path is None:
            return
        out.append((mod, path))
        for imp in imports_of(strip_comments(path.read_text(encoding="utf-8"))):
            visit(imp)

    visit(module)
    return out


def source_scan(project: Path, module: str) -> dict:
    total = {"files": 0, "sorry": 0, "admit": 0, "axiom": 0, "native_decide": 0}
    for _, path in project_modules(project, module):
        total["files"] += 1
        for k, v in scan_text(strip_comments(path.read_text(encoding="utf-8"))).items():
            total[k] += v
    return total


# --- reference -------------------------------------------------------------------

def _body(text: str) -> str:
    """Text after the header (`module`, `prelude` and import lines, blank lines between)."""
    lines = text.splitlines(keepends=True)
    stripped = strip_comments(text).splitlines()
    end = 0
    for i, line in enumerate(stripped):
        if IMPORT_RE.match(line) or HEADER_RE.match(line):
            end = i + 1
        elif line.strip():
            break
    return "".join(lines[end:])


def flatten(project: Path, module: str) -> tuple[str, list[str]]:
    """The challenge module with each project import pasted once, in dependency order, and
    the imports of the trusted base hoisted to the top (CONTRACT §2). Returns text, imports."""
    roots = source_roots(project)
    if module_file(roots, project, module) is None:
        raise AuditError(f"no source file for challenge module {module} under {project}")
    seen, hoisted, bodies = set(), [], []

    def visit(mod):
        seen.add(mod)
        path = module_file(roots, project, mod)
        text = path.read_text(encoding="utf-8")
        for imp in imports_of(strip_comments(text)):
            if imp in seen:
                continue
            if module_file(roots, project, imp) is not None:
                visit(imp)
            else:
                seen.add(imp)
                hoisted.append(imp)
        body = _body(text)
        if body and not body.endswith("\n"):
            body += "\n"
        bodies.append(f"-- lazarillo: flattened from {mod}\n{body}")

    visit(module)
    for imp in hoisted:
        if imp.split(".")[0] not in TRUSTED_ROOTS:
            print(f"lazarillo: audit: reference imports {imp}, which is not Mathlib, Init, Std or Lean",
                  file=sys.stderr)
    head = "".join(f"import {imp}\n" for imp in hoisted)
    return head + "\n" + "\n".join(bodies), hoisted


def _run_logged(cmd: list[str], cwd: Path, env: dict, log_path: Path) -> int:
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"$ {' '.join(cmd)}  (cwd {cwd})\n")
        log.flush()
        try:
            proc = subprocess.run(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
        except OSError as e:
            raise AuditError(f"cannot run {cmd[0]}: {e}") from None
        log.write(f"[exit {proc.returncode}]\n")
    return proc.returncode


def compile_reference(project: Path, out: Path, env: dict) -> list[dict]:
    """`lake env lean Reference.lean -o LazarilloRef.olean` from PROJECT_DIR, then
    `lean/Extract.lean` over that `.olean`; returns its declarations."""
    src = out / REFERENCE_SOURCE
    olean = out / REFERENCE_DIR / f"{REFERENCE_MODULE}.olean"
    logs = out / "logs"
    work = out / "work" / "audit"
    logs.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    log = logs / "audit-reference-compile.log"
    code = _run_logged(["lake", "env", "lean", str(src), "-o", str(olean)], project, env, log)
    if code != 0:
        raise AuditError(f"reference does not compile (exit {code}, see {log})")
    nd = work / "reference-decls.ndjson"
    try:
        run_extractor(project, [Olean(REFERENCE_MODULE, olean, olean.stat().st_size, False)],
                      nd, logs / "audit-reference-extract.log", env)
    except GraphError as e:
        raise AuditError(str(e)) from None
    with open(nd, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _same(row: dict, ref: dict) -> bool:
    if row["hash_type"] != ref["hash_type"]:
        return False
    return row["kind"] == "thm" or row["hash_value"] == ref["hash_value"]


def frontier_diff(nodes: dict[str, dict], front: list[str], ref_rows: list[dict]) -> dict:
    ref = {r["name"]: r for r in ref_rows}
    fset = set(front)
    return {
        "changed": sorted(n for n in front if n in ref and not _same(nodes[n], ref[n])),
        "missing_in_reference": sorted(n for n in front if n not in ref),
        "out_of_frontier_changed": sorted(
            n for n, r in ref.items()
            if n not in fset and n in nodes and not nodes[n]["trusted"] and not _same(nodes[n], r)),
    }


def empty_diff() -> dict:
    return {"changed": [], "missing_in_reference": [], "out_of_frontier_changed": []}


def prepare_reference(args, project: Path, out: Path) -> list[str]:
    """Write `OUT/reference/Reference.lean` from `--challenge-module` or `--reference`;
    returns its imports."""
    (out / REFERENCE_DIR).mkdir(parents=True, exist_ok=True)
    dest = out / REFERENCE_SOURCE
    if args.challenge_module:
        text, imports = flatten(project, args.challenge_module)
        with open(dest, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        return imports
    shutil.copyfile(args.reference, dest)
    return imports_of(strip_comments(dest.read_text(encoding="utf-8")))


def judge_reference(project: Path, out: Path, target: str, env: dict):
    """Comparator verdict of the reference against `core.ndjson` (CONTRACT §5); exports the
    reference to `reference/reference.ndjson` with roots R. Completed in k1-05."""
    return None


# --- stage -----------------------------------------------------------------------

def audit_json(args, nodes: dict[str, dict], project: Path, out: Path, env=None) -> dict:
    target = args.theorem
    if target not in nodes:
        raise AuditError(f"target {target} is not in graph.ndjson")
    axs = axioms(nodes)
    front = frontier(nodes, target)
    reference, diff, comparator = None, empty_diff(), None
    if args.challenge_module or args.reference:
        env = env if env is not None else lean_env()
        imports = prepare_reference(args, project, out)
        diff = frontier_diff(nodes, front, compile_reference(project, out, env))
        reference = {"source": REFERENCE_SOURCE, "imports": imports,
                     "export": REFERENCE_EXPORT, "module": REFERENCE_MODULE}
        if (out / "core.ndjson").is_file():
            comparator = judge_reference(project, out, target, env)
    return {
        "format": AUDIT_FORMAT,
        "target": target,
        "axioms": axs,
        "nonstandard_axioms": [a for a in axs if a not in ALLOWED_AXIOMS],
        "uses": uses(nodes),
        "source_scan": source_scan(project, nodes[target]["module"]),
        "statement_decls": statement_decls(nodes, target),
        "frontier": front,
        "core_lemmas": core_lemmas(nodes),
        "reference": reference,
        "frontier_diff": diff,
        "statement_changed": bool(diff["changed"] or diff["missing_in_reference"]),
        "comparator": comparator,
    }


def run_audit(args) -> int:
    out = Path(args.out).resolve()
    project = Path(args.project_dir).resolve()
    try:
        data = audit_json(args, load_graph(out / "graph.ndjson"), project, out)
    except (AuditError, CoreError) as e:
        print(f"lazarillo: audit: {e}", file=sys.stderr)
        return 1
    jsonio.write_json(out / "audit.json", data)
    return 0
