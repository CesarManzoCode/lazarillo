"""`measure CORPUS`: `run` with the parameters of `corpora.toml` and `summary.json` (CONTRACT §4).

Decisions inside the contract:
- `work/runs/<name>/` is emptied before the run, so `timings.json` and the summary only
  describe this run.
- The summary is written even if `run` fails (D07: a negative result is a result); fields of
  outputs that were not produced are `null`.
- `kernels` keeps the verdicts of `kernels.json` without the log paths, like `stages`.
- A corpus with `license = "none"` (RH, D13) gets a summary with figures only: `axioms` is the
  number of axioms and `kernels` loses its strings (e.g. `altered.removed`), so no name or text
  taken from the corpus is published. The identifiers from `corpora.toml` and the Comparator
  verdict stay.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from . import jsonio
from .config import REPO, ConfigError, load_corpora, work_dir
from .runner import stage_env

SUMMARY_FORMAT = "lazarillo-summary/1"
PATH_KEYS = ("log", "log_time", "log_rss")


def run_argv(c: dict, project: Path, out: Path) -> list[str]:
    argv = ["run", str(project), c["target"], "--out", str(out)]
    if "challenge_module" in c:
        argv += ["--challenge-module", c["challenge_module"]]
    else:
        argv += ["--reference", str(REPO / c["reference"])]
    argv += ["--stages", ",".join(c["stages"]), "--depth", str(c["depth"]),
             "--explain-depth", str(c["explain_depth"])]
    return argv


def _read(path: Path):
    return jsonio.read_json(path) if path.is_file() else None


def _without_paths(obj: dict) -> dict:
    return {k: v for k, v in obj.items() if k not in PATH_KEYS}


def figures_only(summary: dict) -> dict:
    axioms = summary["axioms"]
    kernels = summary["kernels"]
    return dict(summary,
                axioms=len(axioms) if axioms is not None else None,
                kernels={k: {f: v for f, v in r.items() if not isinstance(v, str)} for k, r in kernels.items()}
                        if kernels is not None else None)


def summary_json(name: str, c: dict, run_dir: Path) -> dict:
    core = _read(run_dir / "core.json") or {}
    audit = _read(run_dir / "audit.json")
    kernels = _read(run_dir / "kernels.json")
    timings = _read(run_dir / "timings.json") or {}
    comparator = audit.get("comparator") if audit else None
    summary = {
        "format": SUMMARY_FORMAT,
        "corpus": name,
        "git": c["git"],
        "commit": c["commit"],
        "toolchain": c["toolchain"],
        "target": c["target"],
        "project_decls": core.get("project_decls"),
        "core_decls": core.get("core_decls"),
        "ratio": core.get("ratio"),
        "axioms": audit["axioms"] if audit else None,
        "kernels": {k: _without_paths(kernels[k]) for k in ("lean", "nanoda", "con_leche", "altered")}
                   if kernels else None,
        "comparator": comparator["judgement"] if comparator else None,
        "stages": {s: _without_paths(t) for s, t in sorted(timings.get("stages", {}).items())},
    }
    return figures_only(summary) if c["license"] == "none" else summary


def main(name: str, cfg=None, work=None) -> int:
    cfg = cfg if cfg is not None else load_corpora()
    if name not in cfg["corpus"]:
        raise ConfigError(f"unknown corpus: {name}")
    c = cfg["corpus"][name]
    work = Path(work) if work is not None else work_dir()
    project = work / "corpora" / name / c["subdir"]
    if not project.is_dir():
        print(f"lazarillo: measure {name}: {project} is missing (run fetch first)", file=sys.stderr)
        return 1
    run_dir = work / "runs" / name
    if run_dir.exists():
        shutil.rmtree(run_dir)
    run_dir.mkdir(parents=True)
    env = stage_env()
    env["LAZARILLO_WORK"] = str(work)
    code = subprocess.run([sys.executable, "-m", "lazarillo", *run_argv(c, project, run_dir)],
                          env=env).returncode
    results = work / "results" / name
    results.mkdir(parents=True, exist_ok=True)
    jsonio.write_json(results / "summary.json", summary_json(name, c, run_dir))
    if code != 0:
        print(f"lazarillo: measure {name}: run exited with code {code}", file=sys.stderr)
    return code
