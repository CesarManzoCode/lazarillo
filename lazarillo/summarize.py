"""`summarize`: collect `work/results/` into `work/results/summary.json` (CONTRACT §4).

Decisions inside the contract, with the counting of criteria 12–15 (§7, D09, D10):
- The truth of a mutation is `report.compare_statements.judgement` of its raw `comparator.json`.
  `statement_changed_by_comparator` counts the `failure`s and `detected` those among them that
  lazarillo reports with `statement_changed`.
- `out_of_frontier` counts the mutations of sites (b): neither a frontier definition
  (`in_frontier`) nor the target's statement (`site == target`).
- `controls` counts the mutations Comparator accepts (`success`), C0 included, and
  `false_positives` those among them that lazarillo reports with `statement_changed`.
- A missing or unreadable `comparator.json` counts in neither group.
"""

from pathlib import Path

from . import jsonio
from .config import work_dir
from .mutate import compare_statements

RESULTS_FORMAT = "lazarillo-results/1"


def _truth(mut_dir: Path, m: dict):
    path = mut_dir / m["dir"] / "comparator.json"
    return compare_statements(path.read_text(encoding="utf-8")) if path.is_file() else None


def mutation_counts(mut_dir: Path) -> dict:
    data = jsonio.read_json(mut_dir / "mutations.json")
    target = data["target"]
    changed = detected = outside = controls = false_positives = 0
    for m in data["mutations"]:
        truth = _truth(mut_dir, m)
        if truth == "failure":
            changed += 1
            detected += bool(m["statement_changed"])
        elif truth == "success":
            controls += 1
            false_positives += bool(m["statement_changed"])
        if not m["in_frontier"] and m["site"] != target:
            outside += 1
    return {"compiled": data["compiled"], "statement_changed_by_comparator": changed,
            "detected": detected, "detection_rate": detected / changed if changed else 0.0,
            "out_of_frontier": outside, "controls": controls, "false_positives": false_positives}


def results_json(work: Path) -> dict:
    results = work / "results"
    corpora = {p.parent.name: jsonio.read_json(p) for p in sorted(results.glob("*/summary.json"))}
    mutations = {p.parent.parent.name: mutation_counts(p.parent)
                 for p in sorted(results.glob("*/mutations/mutations.json"))}
    calibration = results / "pfr" / "calibration.json"
    return {"format": RESULTS_FORMAT, "corpora": corpora, "mutations": mutations,
            "calibration": jsonio.read_json(calibration) if calibration.is_file() else None}


def main(work=None) -> int:
    work = Path(work) if work is not None else work_dir()
    (work / "results").mkdir(parents=True, exist_ok=True)
    jsonio.write_json(work / "results" / "summary.json", results_json(work))
    return 0
