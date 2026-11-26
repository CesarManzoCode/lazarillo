"""Stage `kernels`: export of the core file and re-check by `lake check`, nanoda and con-leche,
then the altered core (CONTRACT §2, §3, §5; D04, D11; RESEARCH §2, §3.1–§3.4).

Decisions inside the contract:
- A root of `R` is present in the environment when some module read by the graph stage
  declares it (`graph.DECLARED_ROOTS`). Every root lives in `Init`, which every non-`prelude`
  module imports, so that set equals what the exporter sees from the target's module.
- The verdicts are results: the stage exits 0 whenever it wrote `core.ndjson` and
  `kernels.json`, whatever the kernels answer.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import jsonio
from .config import (ALLOWED_AXIOMS, KERNEL_ROOTS, ConfigError, elan_home, lean_env, load_corpora,
                     toolchain_dir_name, work_dir)
from .core import CoreError, load_graph, project_or, read_toolchain
from .graph import DECLARED_ROOTS

KERNELS_FORMAT = "lazarillo-kernels/1"
CORE_EXPORT = "core.ndjson"
ALTERED_EXPORT = "work/kernels/altered.ndjson"
CHECKED_RE = re.compile(r"Checked (\d+) declarations")
DECL_KINDS = ("axiom", "def", "thm", "opaque", "quot")
INDUCTIVE_PARTS = ("types", "ctors", "recs")


class KernelsError(Exception):
    pass


# --- roots and exporter ----------------------------------------------------------

def split_roots(target: str, declared) -> tuple[list[str], list[str]]:
    """`R = [target] + ALLOWED_AXIOMS + KERNEL_ROOTS` split into present and dropped roots."""
    declared = set(declared)
    roots, dropped = [target], []
    for r in ALLOWED_AXIOMS + KERNEL_ROOTS:
        if r in roots or r in dropped:
            continue
        (roots if r in declared else dropped).append(r)
    return roots, dropped


def read_declared_roots(out: Path) -> list[str]:
    path = Path(out) / DECLARED_ROOTS
    if not path.is_file():
        raise KernelsError(f"missing {path} (run the graph stage first)")
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def toolchain_bin(toolchain: str) -> Path:
    try:
        return elan_home() / "toolchains" / toolchain_dir_name(toolchain) / "bin"
    except ConfigError as e:
        raise KernelsError(str(e)) from None


def fetch_record(project: Path, work: Path | None = None) -> dict | None:
    """The `work/corpora/<name>.fetch.json` whose `project_dir` is PROJECT_DIR, if any."""
    corpora = (work or work_dir()) / "corpora"
    if not corpora.is_dir():
        return None
    project = Path(project).resolve()
    for path in sorted(corpora.glob("*.fetch.json")):
        try:
            record = jsonio.read_json(path)
        except (OSError, ValueError):
            continue
        if isinstance(record, dict) and Path(record.get("project_dir", "")).resolve() == project:
            return record
    return None


def exporter_for(toolchain: str, work: Path | None = None) -> list[str]:
    """The rule of `fetch`: `bin/leanexport` of the toolchain, else lean4export built at the tag
    equal to the toolchain version (CONTRACT §3)."""
    leanexport = toolchain_bin(toolchain) / "leanexport"
    if leanexport.is_file():
        return ["lake", "env", str(leanexport)]
    version = toolchain.split(":", 1)[1]
    binary = (work or work_dir()) / "tools" / f"lean4export-{version}" / ".lake" / "build" / "bin" / "lean4export"
    if not binary.is_file():
        raise KernelsError(f"{toolchain} has no bin/leanexport and {binary} is missing (run fetch)")
    return ["lake", "env", str(binary)]


def corpus_exporter(project: Path) -> list[str]:
    record = fetch_record(project)
    if record and record.get("exporter"):
        return [str(a) for a in record["exporter"]]
    try:
        toolchain = read_toolchain(project)
    except CoreError as e:
        raise KernelsError(str(e)) from None
    return exporter_for(toolchain)


def verification_bin() -> Path:
    return toolchain_bin(load_corpora()["verification"]["toolchain"])


def judge_env(vbin: Path) -> dict:
    """Lean environment with the verification toolchain's `bin/` first in `PATH` (CONTRACT §3)."""
    env = lean_env()
    env["PATH"] = str(vbin) + os.pathsep + env.get("PATH", "")
    return env


def judge_dir() -> Path:
    judge = work_dir() / "judge"
    if not (judge / "lake-manifest.json").is_file():
        raise KernelsError(f"judge workspace {judge} is not built (run fetch)")
    return judge


def cores() -> int:
    return os.cpu_count() or 1


# --- processes -------------------------------------------------------------------

def run_logged(cmd: list[str], cwd: Path, env: dict, log_path: Path, stdout_path: Path | None = None) -> int:
    """Run `cmd`; stderr (and stdout unless `stdout_path`) go to `log_path`. Returns the exit code."""
    cmd = [str(c) for c in cmd]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"$ {' '.join(cmd)}  (cwd {cwd})\n")
        log.flush()
        try:
            if stdout_path is None:
                proc = subprocess.run(cmd, cwd=cwd, env=env, stdout=log, stderr=subprocess.STDOUT)
            else:
                with open(stdout_path, "wb") as f:
                    proc = subprocess.run(cmd, cwd=cwd, env=env, stdout=f, stderr=log)
        except OSError as e:
            raise KernelsError(f"cannot run {cmd[0]}: {e}") from None
        log.write(f"[exit {proc.returncode}]\n")
    return proc.returncode


def export(exporter: list[str], module: str, roots: list[str], project: Path, env: dict,
           dest: Path, log: Path) -> None:
    code = run_logged([*exporter, module, "--", *roots], project, env, log, stdout_path=dest)
    if code != 0:
        raise KernelsError(f"export failed with exit code {code} (see {log})")


# --- export records --------------------------------------------------------------

def record_names(obj: dict, names: dict[int, str]) -> list[str]:
    """Constants declared by one export record (an inductive record declares its whole block)."""
    for kind in DECL_KINDS:
        if kind in obj:
            return [names[obj[kind]["name"]]]
    if "inductive" in obj:
        return [names[t["name"]] for part in INDUCTIVE_PARTS for t in obj["inductive"].get(part, [])]
    return []


def intern_name(obj: dict, names: dict[int, str]) -> None:
    """Record an `in` line: `{"in": i, "str": {"pre", "str"}}` or `{"in": i, "num": {"pre", "i"}}`."""
    if "str" in obj:
        pre, comp = obj["str"]["pre"], obj["str"]["str"]
    else:
        pre, comp = obj["num"]["pre"], str(obj["num"]["i"])
    prefix = names[pre]
    names[obj["in"]] = f"{prefix}.{comp}" if prefix else comp


def strip_record(src: Path, dst: Path, victim: str) -> bool:
    """Copy the export `src` to `dst` without the record that declares `victim`.
    Returns True if a record was removed."""
    names = {0: ""}
    removed = False
    with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8", newline="\n") as out:
        for line in f:
            if not line.strip():
                out.write(line)
                continue
            obj = json.loads(line)
            if "in" in obj:
                intern_name(obj, names)
            elif not removed and victim in record_names(obj, names):
                removed = True
                continue
            out.write(line)
    return removed


def altered_candidates(nodes: dict[str, dict], target: str) -> list[str]:
    """Core declarations other than the target that the target uses directly, alphabetically."""
    row = nodes[target]
    direct = set(row["type_deps"]) | set(row["value_deps"])
    return sorted(d for d in direct if d != target and d in nodes and not nodes[d]["trusted"])


# --- kernels ---------------------------------------------------------------------

def nanoda_config(export_path: Path, threads: int) -> dict:
    return {
        "export_file_path": str(Path(export_path).resolve()),
        "num_threads": threads,
        "permitted_axioms": list(ALLOWED_AXIOMS),
        "unpermitted_axiom_hard_error": False,
        "nat_extension": True,
        "string_extension": True,
        "print_success_message": True,
    }


def parse_checked(text: str) -> int | None:
    m = CHECKED_RE.search(text)
    return int(m.group(1)) if m else None


def run_three(export_path: Path, out: Path, tag: str, vbin: Path, judge: Path, env: dict) -> dict:
    """`lake check`, nanoda and con-leche over one export; logs `OUT/logs/kernels-<tag>-*.log`."""
    logs, work = out / "logs", out / "work" / "kernels"
    work.mkdir(parents=True, exist_ok=True)
    export_path = Path(export_path).resolve()
    result = {}

    log = logs / f"kernels-{tag}-lean.log"
    code = run_logged([vbin / "lake", "check", f"--from-export={export_path}"], judge, env, log)
    result["lean"] = {"exit": code, "log": log.relative_to(out).as_posix()}

    cfg = work / f"nanoda-{tag}.json"
    jsonio.write_json(cfg, nanoda_config(export_path, cores()))
    log = logs / f"kernels-{tag}-nanoda.log"
    code = run_logged([vbin / "nanoda_bin", cfg], out, env, log)
    checked = parse_checked(log.read_text(encoding="utf-8", errors="replace"))
    result["nanoda"] = {"exit": code, "checked": checked, "log": log.relative_to(out).as_posix()}

    log = logs / f"kernels-{tag}-con-leche.log"
    code = run_logged([vbin / "con-leche", f"--jobs={cores()}", export_path], out, env, log)
    result["con_leche"] = {"exit": code, "log": log.relative_to(out).as_posix()}
    return result


def altered(nodes: dict[str, dict], target: str, out: Path, vbin: Path, judge: Path, env: dict) -> dict:
    dst = out / ALTERED_EXPORT
    dst.parent.mkdir(parents=True, exist_ok=True)
    victim = next((c for c in altered_candidates(nodes, target)
                   if strip_record(out / CORE_EXPORT, dst, c)), None)
    if victim is None:
        dst.unlink(missing_ok=True)
        print(f"lazarillo: kernels: no core declaration used by {target} to remove", file=sys.stderr)
        return {"removed": None, "lean_exit": None, "nanoda_exit": None, "con_leche_exit": None}
    r = run_three(dst, out, "altered", vbin, judge, env)
    return {"removed": victim, "lean_exit": r["lean"]["exit"], "nanoda_exit": r["nanoda"]["exit"],
            "con_leche_exit": r["con_leche"]["exit"]}


def kernels_json(args, out: Path, project: Path) -> dict:
    target = args.theorem
    nodes = load_graph(out / "graph.ndjson", keep=project_or(target))  # project rows only
    if target not in nodes:
        raise KernelsError(f"target {target} is not in graph.ndjson")
    roots, dropped = split_roots(target, read_declared_roots(out))
    exporter = corpus_exporter(project)
    export(exporter, nodes[target]["module"], roots, project, lean_env(), out / CORE_EXPORT,
           out / "logs" / "kernels-export.log")
    vbin = verification_bin()
    judge = judge_dir()
    env = judge_env(vbin)
    checks = run_three(out / CORE_EXPORT, out, "core", vbin, judge, env)
    return {
        "format": KERNELS_FORMAT,
        "exporter": exporter,
        "export_roots": roots,
        "dropped_roots": dropped,
        **checks,
        "altered": altered(nodes, target, out, vbin, judge, env),
    }


def run_kernels(args) -> int:
    out = Path(args.out).resolve()
    project = Path(args.project_dir).resolve()
    (out / "logs").mkdir(parents=True, exist_ok=True)
    try:
        data = kernels_json(args, out, project)
    except (KernelsError, CoreError, ConfigError) as e:
        print(f"lazarillo: kernels: {e}", file=sys.stderr)
        return 1
    jsonio.write_json(out / "kernels.json", data)
    return 0
