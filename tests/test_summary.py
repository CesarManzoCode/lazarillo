import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import jsonio, measure, summarize  # noqa: E402

CORPUS = {"git": "https://x/y", "commit": "a" * 40, "toolchain": "leanprover/lean4:v4.37.0-rc1",
          "target": "P.target", "subdir": ".", "license": "MIT", "challenge_module": "Challenge",
          "stages": ["graph", "core", "kernels", "audit", "tree"], "depth": 2, "explain_depth": 1}
FIELDS = {"format", "corpus", "git", "commit", "toolchain", "target", "project_decls", "core_decls",
          "ratio", "axioms", "kernels", "comparator", "stages"}


def write_out(out: Path, kernels: bool) -> None:
    """A synthetic `run` OUT directory; with or without `kernels.json`."""
    jsonio.write_json(out / "core.json", {"format": "lazarillo-core/1", "project_decls": 20,
                                          "core_decls": 5, "ratio": 0.25, "core": ["P.a", "P.target"]})
    jsonio.write_json(out / "audit.json", {
        "axioms": ["Classical.choice", "P.ax", "propext"],
        "frontier": ["P.def"], "statement_decls": ["P.def"],
        "comparator": {"exit": 0, "judgement": "accepted", "report": "reference/comparator.report.json"}
        if kernels else None})
    if kernels:
        jsonio.write_json(out / "kernels.json", {
            "format": "lazarillo-kernels/1", "exporter": ["lake"], "export_roots": ["P.target"],
            "dropped_roots": [], "lean": {"exit": 0, "log": "logs/lean.log"},
            "nanoda": {"exit": 0, "checked": 99, "log": "logs/nanoda.log"},
            "con_leche": {"exit": 0, "log": "logs/con-leche.log"},
            "altered": {"removed": "P.a", "lean_exit": 1, "nanoda_exit": 101, "con_leche_exit": 1}})
    jsonio.write_json(out / "tree.json", {"nodes": [{"name": "P.target", "statement": "1 = 1",
                                                     "explanation": "The theorem says one is one."}]})
    jsonio.write_json(out / "timings.json", {"format": "lazarillo-timings/1", "stages": {
        "tree": {"wall_s": 3.0, "peak_rss_bytes": 30, "time_max_rss_kb": 1,
                 "log_time": "logs/tree.time", "log_rss": "logs/tree.rss"},
        "graph": {"wall_s": 1.0, "peak_rss_bytes": 10, "time_max_rss_kb": 1,
                  "log_time": "logs/graph.time", "log_rss": "logs/graph.rss"}}})


def strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from strings(v)


class SummaryJsonTest(unittest.TestCase):
    def test_with_kernels(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_out(out, kernels=True)
            s = measure.summary_json("c", CORPUS, out)
        self.assertEqual(set(s), FIELDS)
        self.assertEqual((s["format"], s["corpus"], s["git"], s["commit"], s["toolchain"], s["target"]),
                         ("lazarillo-summary/1", "c", "https://x/y", "a" * 40,
                          "leanprover/lean4:v4.37.0-rc1", "P.target"))
        self.assertEqual((s["project_decls"], s["core_decls"], s["ratio"]), (20, 5, 0.25))
        self.assertEqual(s["axioms"], ["Classical.choice", "P.ax", "propext"])
        self.assertEqual(s["kernels"], {
            "lean": {"exit": 0}, "nanoda": {"exit": 0, "checked": 99}, "con_leche": {"exit": 0},
            "altered": {"removed": "P.a", "lean_exit": 1, "nanoda_exit": 101, "con_leche_exit": 1}})
        self.assertEqual(s["comparator"], "accepted")
        self.assertEqual(list(s["stages"]), ["graph", "tree"])
        self.assertEqual(s["stages"]["tree"], {"wall_s": 3.0, "peak_rss_bytes": 30, "time_max_rss_kb": 1})

    def test_without_kernels(self):
        c = dict(CORPUS, stages=["graph", "core", "audit", "tree"])
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            write_out(out, kernels=False)
            s = measure.summary_json("c", c, out)
        self.assertEqual(set(s), FIELDS)
        self.assertIsNone(s["kernels"])
        self.assertIsNone(s["comparator"])
        self.assertEqual(s["core_decls"], 5)

    def test_unlicensed_has_figures_only(self):
        c = dict(CORPUS, license="none", target="riemannHypothesis")
        with tempfile.TemporaryDirectory() as tmp:
            out, bare_out = Path(tmp) / "a", Path(tmp) / "b"
            out.mkdir()
            bare_out.mkdir()
            write_out(out, kernels=True)
            s = measure.summary_json("rh", c, out)
            write_out(bare_out, kernels=False)
            bare = measure.summary_json("rh", c, bare_out)
        self.assertEqual(set(s), FIELDS)
        self.assertEqual(s["axioms"], 3)
        self.assertEqual(s["kernels"]["altered"], {"lean_exit": 1, "nanoda_exit": 101, "con_leche_exit": 1})
        text = json.dumps(s, ensure_ascii=False)
        for derived in ("P.ax", "P.a\"", "P.def", "1 = 1", "one is one", "logs/"):
            self.assertNotIn(derived, text)
        allowed = {"lazarillo-summary/1", "rh", "https://x/y", "a" * 40, "leanprover/lean4:v4.37.0-rc1",
                   "riemannHypothesis", "accepted"}
        self.assertLessEqual(set(strings(s)), allowed)
        self.assertEqual(bare["axioms"], 3)
        self.assertIsNone(bare["kernels"])


def write_mutations(d: Path, target: str, rows: list[tuple]) -> None:
    """rows: (id, site, in_frontier, statement_changed, comparator judgement or None)."""
    d.mkdir(parents=True)
    ms = []
    for mid, site, in_frontier, changed, judgement in rows:
        (d / mid).mkdir()
        if judgement is not None:
            report = {"judgement": "rejected" if judgement == "failure" else "accepted",
                      "report": {"compare_statements": {"judgement": judgement},
                                 "check_axioms": {"judgement": "success"}}}
            (d / mid / "comparator.json").write_text("info: comparing\n" + json.dumps(report) + "\n")
        ms.append({"id": mid, "site": site, "operator": "M1", "in_frontier": in_frontier, "dir": mid,
                   "compile_exit": 0, "statement_changed": changed,
                   "classification": "statement_change" if changed else
                   ("no_change" if in_frontier or site == target else "out_of_frontier")})
    jsonio.write_json(d / "mutations.json", {"format": "lazarillo-mutations/1", "corpus": d.parent.name,
                                             "target": target, "candidates": len(ms) + 2,
                                             "compiled": len(ms), "mutations": ms})


class SummarizeTest(unittest.TestCase):
    def test_two_corpora(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            results = work / "results"
            # zeta23: 4 changed per Comparator (3 detected), 2 controls (1 flagged), 2 outside.
            write_mutations(results / "zeta23" / "mutations", "Goal", [
                ("m001", "IsZero", True, True, "failure"),
                ("m002", "IsZero", True, True, "failure"),
                ("m003", "IsZero", True, False, "failure"),
                ("m004", "Goal", False, True, "failure"),
                ("m005", "IsZero", True, False, "success"),
                ("m006", "Goal", False, True, "success"),
                ("m007", "Leaf.f", False, False, "success"),
                ("m008", "Leaf.g", False, False, None),
            ])
            # pfr: nothing changes the statement, so the rate is 0.0 with the count beside it.
            write_mutations(results / "pfr" / "mutations", "Marton.pfr_conjecture", [
                ("m001", "Marton.pfr_conjecture", False, False, "success"),
                ("m002", "leafDef", False, False, "success"),
            ])
            jsonio.write_json(results / "zeta23" / "summary.json", {"format": "lazarillo-summary/1",
                                                                    "corpus": "zeta23", "core_decls": 7})
            jsonio.write_json(results / "pfr" / "summary.json", {"format": "lazarillo-summary/1",
                                                                 "corpus": "pfr", "core_decls": 9})
            calibration = {"format": "lazarillo-calibration/1", "root_label": "pfr",
                           "nodes": {"precision": 0.9, "recall": 1.0}}
            jsonio.write_json(results / "pfr" / "calibration.json", calibration)

            self.assertEqual(summarize.main(work), 0)
            path = results / "summary.json"
            first = path.read_bytes()
            self.assertEqual(summarize.main(work), 0)
            self.assertEqual(path.read_bytes(), first)
            data = jsonio.read_json(path)

        self.assertEqual(data["format"], "lazarillo-results/1")
        self.assertEqual(sorted(data["corpora"]), ["pfr", "zeta23"])
        self.assertEqual(data["corpora"]["zeta23"]["core_decls"], 7)
        self.assertEqual(data["calibration"], calibration)
        self.assertEqual(data["mutations"]["zeta23"], {
            "compiled": 8, "statement_changed_by_comparator": 4, "detected": 3, "detection_rate": 3 / 4,
            "out_of_frontier": 2, "controls": 3, "false_positives": 1})
        self.assertEqual(data["mutations"]["pfr"], {
            "compiled": 2, "statement_changed_by_comparator": 0, "detected": 0, "detection_rate": 0.0,
            "out_of_frontier": 1, "controls": 2, "false_positives": 0})

    def test_empty_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            self.assertEqual(summarize.main(work), 0)
            data = jsonio.read_json(work / "results" / "summary.json")
        self.assertEqual(data, {"format": "lazarillo-results/1", "corpora": {}, "mutations": {},
                                "calibration": None})


if __name__ == "__main__":
    unittest.main()
