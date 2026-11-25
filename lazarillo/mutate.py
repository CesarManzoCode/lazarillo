"""Command `mutate`: seeded mutations of the flattened reference, judged by Comparator and
audited by fingerprints (CONTRACT §2, §5, §7; D09, D10; RESEARCH §1, §3.4, §3.5, §3.11).

Decisions inside the contract:
- A declaration block starts at the line of `def <name>` / `abbrev <name>` (modifiers on that
  line included; docstrings and attribute lines above it are not) and ends before the next
  non-blank line indented no deeper than that line, other than a continuation (`|`, `where`,
  `termination_by`, `decreasing_by`, `deriving`); trailing blank or comment-only lines are
  dropped. Its full name is the open `namespace`s plus the declared identifier (`_root_.`
  resets it); `section`, `mutual` and `end` are tracked so closed namespaces do not leak.
- The body of a definition starts after the first `:=` outside brackets; without one (pattern
  matching, `where` structures) it starts after the declared identifier. Operators only match
  outside comments and string literals.
- M1 rewrites ASCII decimal literals not glued to an identifier, a `.` or a `'` (`p.1`, `x2`
  and `1.5` stay); M2 rewrites `<`, `≤`, `<=`, `>`, `≥`, `>=` when they are not part of a
  longer operator (`<|`, `=>`, `<;>`, `>>=` stay) and not the `ℝ≥0` notation; `<=` and `>=`
  become `<` and `>`. Candidates of one site come in the order M1, M2, M3 (each by position),
  then C0.
- C0 inserts the line `-- lazarillo: C0 control` before the second line of the body; for a
  body on one line, the rest of that line moves below the comment.
- Frontier sites are the non-internal frontier names whose block is found in the reference, in
  the (alphabetical) order of `frontier`. Out-of-frontier sites skip definitions the reference
  already declares (a copy would clash) or whose block is not found in their module's file.
  The copy goes inside `noncomputable section` within its namespace: that keeps
  noncomputable definitions compiling and does not change any term.
- Ids follow the order in which candidates are tried: every frontier candidate, then the
  out-of-frontier ones until 10 have compiled; `candidates` counts all of them.
- `OUT/<id>/` is emptied before each candidate. A compiled candidate whose export, Comparator
  run or extraction cannot start is an error of the command (exit 1); Comparator rejecting is
  a result.
"""

import json
import re
import shutil
import sys
from dataclasses import dataclass, replace
from itertools import chain
from pathlib import Path

from . import audit, jsonio, kernels
from .config import ConfigError, lean_env, work_dir
from .core import CoreError, load_graph
from .graph import GraphError, Olean, run_extractor

MUTATIONS_FORMAT = "lazarillo-mutations/1"
MODULE = audit.REFERENCE_MODULE
OUT_OF_FRONTIER = 10
C0_LINE = "-- lazarillo: C0 control"

DEF_RE = re.compile(r"^([ \t]*)(?:@\[[^\]\n]*\]\s*)?"
                    r"(?:(?:private|protected|noncomputable|partial|unsafe|nonrec|public|meta)\s+)*"
                    r"(?:def|abbrev)\s+([^\s(\[{:]+)")
NAMESPACE_RE = re.compile(r"^\s*namespace\s+(\S+)")
SECTION_RE = re.compile(r"^\s*(?:@\[[^\]\n]*\]\s*)?(?:(?:noncomputable|public|private)\s+)*section(?:\s|$)")
MUTUAL_RE = re.compile(r"^\s*mutual(?:\s|$)")
END_RE = re.compile(r"^\s*end(?:\s|$)")
CONTINUATION_RE = re.compile(r"^\s*(?:\||(?:where|termination_by|decreasing_by|deriving)(?:\s|$))")

M1_RE = re.compile(r"(?<![\w.'])(?<!ℝ≥)[0-9]+(?![\w.'])")
M2_RE = re.compile(r"<=|>=|<|>|≤|≥")
M3_RE = re.compile(r"[∧∨]")
OP_CHARS = frozenset("<>=-|$*&!:+~^%/;?@\\")
SWAP = {"<": "≤", "≤": "<", "<=": "<", ">": "≥", "≥": ">", ">=": ">", "∧": "∨", "∨": "∧"}
OPEN_BRACKETS = "([{⟨"
CLOSE_BRACKETS = ")]}⟩"


class MutateError(Exception):
    pass


@dataclass(frozen=True)
class Block:
    start: int   # offset of the declaration line
    end: int     # offset just after the block
    body: int    # offset where the body starts
    indent: int  # columns before the declaration line


@dataclass(frozen=True)
class Candidate:
    site: str
    operator: str
    in_frontier: bool
    text: str


# --- source text -----------------------------------------------------------------

def mask(text: str) -> str:
    """`text` with comments (`--`, nested `/- -/`) and string literals blanked to spaces;
    line breaks and offsets are kept."""
    out = list(text)
    n, i = len(text), 0

    def blank(a, b):
        for k in range(a, b):
            if out[k] != "\n":
                out[k] = " "

    while i < n:
        if text.startswith("--", i):
            j = text.find("\n", i)
            j = n if j < 0 else j
        elif text.startswith("/-", i):
            depth, j = 1, i + 2
            while j < n and depth:
                if text.startswith("/-", j):
                    depth, j = depth + 1, j + 2
                elif text.startswith("-/", j):
                    depth, j = depth - 1, j + 2
                else:
                    j += 1
        elif text[i] == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            j = min(j + 1, n)
        else:
            i += 1
            continue
        blank(i, j)
        i = j
    return "".join(out)


def _offsets(lines: list[str]) -> list[int]:
    offs = [0]
    for line in lines:
        offs.append(offs[-1] + len(line))
    return offs


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" \t"))


def _assign(masked: str, start: int, end: int) -> int | None:
    """Offset just after the first `:=` outside brackets in `masked[start:end]`."""
    depth = 0
    for i in range(start, end):
        c = masked[i]
        if c in OPEN_BRACKETS:
            depth += 1
        elif c in CLOSE_BRACKETS:
            depth -= 1
        elif depth == 0 and masked.startswith(":=", i):
            return i + 2
    return None


def locate(text: str, name: str) -> Block | None:
    """The block of `def`/`abbrev` declaring the full name `name` in `text`, if any."""
    masked = mask(text)
    lines = masked.splitlines(keepends=True)
    offs = _offsets(lines)
    scopes: list[list[str]] = []
    for i, line in enumerate(lines):
        m = DEF_RE.match(line)
        if m:
            ident = m.group(2)
            if ident.startswith("_root_."):
                full = ident[len("_root_."):]
            else:
                full = ".".join([c for s in scopes for c in s] + [ident])
            if full == name:
                return _block(masked, lines, offs, i, m)
        elif (ns := NAMESPACE_RE.match(line)):
            scopes.append(ns.group(1).split("."))
        elif SECTION_RE.match(line) or MUTUAL_RE.match(line):
            scopes.append([])
        elif END_RE.match(line) and scopes:
            scopes.pop()
    return None


def _block(masked: str, lines: list[str], offs: list[int], i: int, m: re.Match) -> Block:
    indent = len(m.group(1))
    j = i + 1
    while j < len(lines):
        line = lines[j]
        if line.strip() and _indent(line) <= indent and not CONTINUATION_RE.match(line):
            break
        j += 1
    while j > i + 1 and not lines[j - 1].strip():
        j -= 1
    start, end = offs[i], offs[j]
    after_name = start + m.end()
    body = _assign(masked, after_name, end)
    return Block(start, end, after_name if body is None else body, indent)


# --- operators -------------------------------------------------------------------

def _m2_ok(masked: str, a: int, b: int) -> bool:
    before = masked[a - 1] if a > 0 else " "
    after = masked[b] if b < len(masked) else " "
    if before in OP_CHARS or after in OP_CHARS:
        return False
    return not (masked[a:b] == "≥" and before == "ℝ")


def occurrences(masked: str, start: int, end: int) -> list[tuple[str, int, int, str]]:
    """`(operator, a, b, replacement)` for every M1, M2, M3 site in `masked[start:end]`,
    by operator and then by position."""
    region = masked[:end]
    out = [("M1", m.start(), m.end(), str(int(m.group()) + 1)) for m in M1_RE.finditer(region, start)]
    out += [("M2", m.start(), m.end(), SWAP[m.group()]) for m in M2_RE.finditer(region, start)
            if _m2_ok(masked, m.start(), m.end())]
    out += [("M3", m.start(), m.end(), SWAP[m.group()]) for m in M3_RE.finditer(region, start)]
    return out


def mutations(text: str, block: Block) -> list[tuple[str, str]]:
    """`(operator, mutated text)` for each operator occurrence in the body of `block`."""
    return [(op, text[:a] + repl + text[b:])
            for op, a, b, repl in occurrences(mask(text), block.body, block.end)]


def control(text: str, block: Block) -> str:
    """C0: a comment line inside the body; the term does not change."""
    nl = text.find("\n", block.body, block.end)
    pad = " " * (block.indent + 2)
    if 0 <= nl and nl + 1 < block.end:
        return text[:nl + 1] + pad + C0_LINE + "\n" + text[nl + 1:]
    rest_end = nl if nl >= 0 else block.end
    rest = text[block.body:rest_end].lstrip()
    return text[:block.body] + "\n" + pad + C0_LINE + "\n" + pad + rest + text[rest_end:]


# --- candidates ------------------------------------------------------------------

def site_candidates(text: str, block: Block, site: str, in_frontier: bool) -> list[Candidate]:
    """Every operator occurrence of the body, then the control."""
    out = [Candidate(site, op, in_frontier, t) for op, t in mutations(text, block)]
    out.append(Candidate(site, "C0", in_frontier, control(text, block)))
    return out


def frontier_candidates(ref_text: str, frontier: list[str], nodes: dict[str, dict]) -> list[Candidate]:
    out = []
    for name in frontier:
        row = nodes.get(name)
        if row is None or row["internal"]:
            continue
        block = locate(ref_text, name)
        if block is not None:
            out += site_candidates(ref_text, block, name, True)
    return out


def leaf_defs(nodes: dict[str, dict], core: list[str], frontier: list[str]) -> list[str]:
    """Non-internal `def`s of the core outside the frontier whose dependencies are all in the
    trusted base, alphabetically."""
    fset = set(frontier)
    out = []
    for name in sorted(core):
        row = nodes.get(name)
        if row is None or name in fset or row["internal"] or row["kind"] != "def":
            continue
        deps = (*row["type_deps"], *row["value_deps"])
        if all(d in nodes and nodes[d]["trusted"] for d in deps):
            out.append(name)
    return out


def leaf_copy(ref_text: str, name: str, source: str) -> tuple[str, Block] | None:
    """The reference with the source block of `name` pasted at the end inside its namespace,
    and the block of the copy."""
    block = locate(source, name)
    if block is None:
        return None
    snippet = source[block.start:block.end]
    if not snippet.endswith("\n"):
        snippet += "\n"
    prefix = name.rpartition(".")[0]
    head = ref_text if ref_text.endswith("\n") else ref_text + "\n"
    head += f"\n-- lazarillo: copy of {name}\n"
    if prefix:
        head += f"namespace {prefix}\n"
    head += "noncomputable section\n\n"
    tail = "\nend\n" + (f"end {prefix}\n" if prefix else "")
    start = len(head)
    copy = replace(block, start=start, end=start + len(snippet), body=start + block.body - block.start)
    return head + snippet + tail, copy


def leaf_candidate(text: str, block: Block, site: str) -> Candidate:
    """The first applicable operator of the copy (M1, M2, M3 by position), else C0."""
    muts = mutations(text, block)
    if muts:
        return Candidate(site, muts[0][0], False, muts[0][1])
    return Candidate(site, "C0", False, control(text, block))


def leaf_candidates(ref_text: str, nodes: dict[str, dict], core: list[str], frontier: list[str],
                    read_source):
    """Out-of-frontier candidates, lazily; `read_source(module)` gives the module's text or None."""
    for name in leaf_defs(nodes, core, frontier):
        if locate(ref_text, name) is not None:
            continue
        source = read_source(nodes[name]["module"])
        if source is None:
            continue
        copy = leaf_copy(ref_text, name, source)
        if copy is not None:
            yield leaf_candidate(*copy, name)


def candidate_id(n: int) -> str:
    return f"m{n:03d}"


def numbered(cands, start: int = 1):
    for n, cand in enumerate(cands, start):
        yield candidate_id(n), cand


# --- verdicts --------------------------------------------------------------------

def compare_statements(text: str):
    """`report.compare_statements.judgement` of a raw `lake comparator --json` output."""
    try:
        data = json.loads(text[text.index("{"):])
        return data["report"]["compare_statements"]["judgement"]
    except (ValueError, KeyError, TypeError):
        return None


def classify(statement_changed: bool, in_frontier: bool) -> str:
    if statement_changed:
        return "statement_change"
    return "no_change" if in_frontier else "out_of_frontier"


# --- running ---------------------------------------------------------------------

def source_reader(project: Path):
    roots = audit.source_roots(project)

    def read(module: str) -> str | None:
        path = audit.module_file(roots, project, module)
        return None if path is None else path.read_text(encoding="utf-8")

    return read


def corpus_name(project: Path, run: Path) -> str:
    """Name of the `work/corpora/<name>.fetch.json` whose `project_dir` is PROJECT_DIR, else
    the name of RUN_DIR (`work/runs/<corpus>`)."""
    corpora = work_dir() / "corpora"
    for path in sorted(corpora.glob("*.fetch.json")) if corpora.is_dir() else ():
        try:
            record = jsonio.read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and Path(record.get("project_dir", "")).resolve() == project:
            return path.name[:-len(".fetch.json")]
    return run.name


class Mutator:
    """Compiles, exports, judges and audits candidates in `OUT/<id>/`."""

    def __init__(self, run: Path, project: Path, out: Path):
        self.run, self.project, self.out = run, project, out
        path = run / "audit.json"
        if not path.is_file():
            raise MutateError(f"missing {path} (run the audit stage first)")
        data = jsonio.read_json(path)
        if not data.get("reference"):
            raise MutateError(f"{path} has no reference")
        self.target = data["target"]
        self.frontier = list(data["frontier"])
        self.ref_text = (run / data["reference"]["source"]).read_text(encoding="utf-8")
        self.solution = run / data["reference"]["export"]
        if not self.solution.is_file():
            raise MutateError(f"missing {self.solution}")
        self.nodes = load_graph(run / "graph.ndjson")
        path = run / "core.json"
        if not path.is_file():
            raise MutateError(f"missing {path} (run the core stage first)")
        self.core = list(jsonio.read_json(path)["core"])
        self.roots, _ = kernels.split_roots(self.target, kernels.read_declared_roots(run))
        self.env = lean_env()
        self.vbin = kernels.verification_bin()
        self.judge = kernels.judge_dir()

    def candidate(self, cid: str, cand: Candidate) -> dict | None:
        """The `mutations` entry of a candidate, or None if it does not compile."""
        d = self.out / cid
        if d.exists():
            shutil.rmtree(d)
        build = d / "build"
        build.mkdir(parents=True)
        with open(d / "Reference.lean", "w", encoding="utf-8", newline="\n") as f:
            f.write(cand.text)
        src = build / f"{MODULE}.lean"
        shutil.copyfile(d / "Reference.lean", src)
        olean = build / f"{MODULE}.olean"
        code = kernels.run_logged(["lake", "env", "lean", f"--root={build}", src, "-o", olean],
                                  self.project, self.env, d / "compile.log")
        if code != 0:
            return None
        export = d / "reference.ndjson"
        exporter = audit.lean_path_exporter(kernels.corpus_exporter(self.project), build)
        kernels.export(exporter, MODULE, self.roots, self.project, self.env, export, d / "export.log")
        cfg = d / "comparator.config.json"
        jsonio.write_json(cfg, audit.comparator_config(self.target))
        kernels.run_logged(
            [self.vbin / "lake", "comparator", "--config", cfg, f"--challenge-from-export={export}",
             f"--solution-from-export={self.solution}", "--json"],
            self.judge, kernels.judge_env(self.vbin), d / "comparator.log",
            stdout_path=d / "comparator.json")
        decls = build / "decls.ndjson"
        run_extractor(self.project, [Olean(MODULE, olean, olean.stat().st_size, False)],
                      decls, d / "extract.log", self.env)
        with open(decls, encoding="utf-8") as f:
            rows = [json.loads(line) for line in f if line.strip()]
        diff = audit.frontier_diff(self.nodes, self.frontier, rows)
        changed = bool(diff["changed"] or diff["missing_in_reference"])
        classification = classify(changed, cand.in_frontier)
        jsonio.write_json(d / "audit.json", {"target": self.target, "frontier_diff": diff,
                                             "statement_changed": changed,
                                             "classification": classification})
        return {"id": cid, "site": cand.site, "operator": cand.operator,
                "in_frontier": cand.in_frontier, "dir": cid, "compile_exit": code,
                "statement_changed": changed, "classification": classification}

    def mutations_json(self) -> dict:
        entries, tried, leaves = [], 0, 0
        front = frontier_candidates(self.ref_text, self.frontier, self.nodes)
        rest = leaf_candidates(self.ref_text, self.nodes, self.core, self.frontier,
                               source_reader(self.project))
        for cid, cand in numbered(chain(front, rest)):
            if not cand.in_frontier and leaves >= OUT_OF_FRONTIER:
                break
            tried += 1
            entry = self.candidate(cid, cand)
            if entry is None:
                continue
            entries.append(entry)
            if not cand.in_frontier:
                leaves += 1
        return {"format": MUTATIONS_FORMAT, "corpus": corpus_name(self.project, self.run),
                "target": self.target, "candidates": tried, "compiled": len(entries),
                "mutations": entries}


def main(args) -> int:
    run = Path(args.run).resolve()
    project = Path(args.project).resolve()
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    try:
        data = Mutator(run, project, out).mutations_json()
    except (MutateError, audit.AuditError, kernels.KernelsError, GraphError, CoreError, ConfigError,
            OSError) as e:
        print(f"lazarillo: mutate: {e}", file=sys.stderr)
        return 1
    jsonio.write_json(out / "mutations.json", data)
    return 0
