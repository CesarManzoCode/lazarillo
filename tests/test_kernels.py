import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import audit, config, jsonio, kernels, measure, runner  # noqa: E402
from lazarillo.graph import DECLARED_ROOTS  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "mini"

# Synthetic NDJSON 3.1.0: names (one with a numeric component), an inductive block and theorems.
EXPORT = [
    {"meta": {"format": {"version": "3.1.0"}}},
    {"in": 1, "str": {"pre": 0, "str": "P"}},
    {"in": 2, "str": {"pre": 1, "str": "T"}},
    {"in": 3, "str": {"pre": 2, "str": "mk"}},
    {"in": 4, "str": {"pre": 2, "str": "rec"}},
    {"in": 5, "str": {"pre": 1, "str": "lemma"}},
    {"in": 6, "num": {"pre": 5, "i": 2}},
    {"in": 7, "str": {"pre": 1, "str": "target"}},
    {"inductive": {"types": [{"name": 2}], "ctors": [{"name": 3}], "recs": [{"name": 4}]}},
    {"thm": {"name": 5, "type": 0, "value": 0, "levelParams": []}},
    {"thm": {"name": 6, "type": 0, "value": 0, "levelParams": []}},
    {"thm": {"name": 7, "type": 0, "value": 0, "levelParams": []}},
]


def node(name, kind, type_deps=(), value_deps=(), trusted=False):
    return {"name": name, "kind": kind, "trusted": trusted, "internal": False, "module": "P",
            "type_deps": sorted(type_deps), "value_deps": sorted(value_deps),
            "hash_type": "0" * 16, "hash_value": None}


class RootsTest(unittest.TestCase):
    def test_split_roots(self):
        declared = [r for r in config.ALLOWED_AXIOMS + config.KERNEL_ROOTS if r != "eagerReduce"]
        roots, dropped = kernels.split_roots("P.target", declared)
        self.assertEqual(roots[0], "P.target")
        self.assertEqual(roots[1:4], list(config.ALLOWED_AXIOMS))
        self.assertNotIn("eagerReduce", roots)
        self.assertEqual(dropped, ["eagerReduce"])
        self.assertEqual(len(roots) + len(dropped), 1 + 3 + 19)

    def test_target_is_a_root_only_once(self):
        roots, dropped = kernels.split_roots("Nat.add", ["Nat.add"])
        self.assertEqual(roots, ["Nat.add"])
        self.assertNotIn("Nat.add", dropped)
        self.assertIn("propext", dropped)

    def test_declared_roots_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            with self.assertRaises(kernels.KernelsError):
                kernels.read_declared_roots(out)
            (out / DECLARED_ROOTS).parent.mkdir(parents=True)
            jsonio.write_lines(out / DECLARED_ROOTS, ["propext", "Nat.add"])
            self.assertEqual(kernels.read_declared_roots(out), ["propext", "Nat.add"])


class ExporterTest(unittest.TestCase):
    def test_fetch_record_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "work"
            project = Path(tmp) / "proj"
            project.mkdir()
            (work / "corpora").mkdir(parents=True)
            jsonio.write_json(work / "corpora" / "other.fetch.json",
                              {"project_dir": str(Path(tmp) / "x"), "exporter": ["no"]})
            jsonio.write_json(work / "corpora" / "c.fetch.json",
                              {"project_dir": str(project), "exporter": ["lake", "env", "/bin/x"]})
            self.assertEqual(kernels.fetch_record(project, work)["exporter"], ["lake", "env", "/bin/x"])
            self.assertIsNone(kernels.fetch_record(Path(tmp) / "none", work))

    def test_exporter_rule(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            elan = work / "elan"
            tc = "leanprover/lean4:v4.33.0-rc2"
            with mock.patch.object(kernels, "elan_home", return_value=elan):
                with self.assertRaises(kernels.KernelsError):
                    kernels.exporter_for(tc, work)
                binary = work / "tools" / "lean4export-v4.33.0-rc2" / ".lake" / "build" / "bin" / "lean4export"
                binary.parent.mkdir(parents=True)
                binary.write_text("")
                self.assertEqual(kernels.exporter_for(tc, work), ["lake", "env", str(binary)])
                shipped = elan / "toolchains" / config.toolchain_dir_name(tc) / "bin" / "leanexport"
                shipped.parent.mkdir(parents=True)
                shipped.write_text("")
                self.assertEqual(kernels.exporter_for(tc, work), ["lake", "env", str(shipped)])

    def test_lean_path_exporter(self):
        cmd = audit.lean_path_exporter(["lake", "env", "/t/leanexport"], Path("/o/reference"))
        self.assertEqual(cmd[:4], ["lake", "env", "sh", "-c"])
        self.assertEqual(cmd[5:], ["/o/reference", "/t/leanexport"])
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, LEAN_PATH="/a")
            proc = subprocess.run(cmd[2:5] + [tmp, "sh", "-c", 'printf %s "$LEAN_PATH"'],
                                  env=env, stdout=subprocess.PIPE, text=True)
        self.assertEqual(proc.stdout, f"{tmp}:/a")


class ExportRecordsTest(unittest.TestCase):
    def write(self, path):
        jsonio.write_ndjson(path, EXPORT)

    def strip(self, victim):
        with tempfile.TemporaryDirectory() as tmp:
            src, dst = Path(tmp) / "a.ndjson", Path(tmp) / "b.ndjson"
            self.write(src)
            removed = kernels.strip_record(src, dst, victim)
            lines = [json.loads(x) for x in dst.read_text(encoding="utf-8").splitlines()]
        return removed, lines

    def test_numeric_name(self):
        removed, lines = self.strip("P.lemma.2")
        self.assertTrue(removed)
        self.assertEqual(len(lines), len(EXPORT) - 1)
        self.assertNotIn({"thm": {"name": 6, "type": 0, "value": 0, "levelParams": []}}, lines)
        self.assertIn({"thm": {"name": 5, "type": 0, "value": 0, "levelParams": []}}, lines)

    def test_inductive_block_by_ctor(self):
        removed, lines = self.strip("P.T.mk")
        self.assertTrue(removed)
        self.assertFalse(any("inductive" in x for x in lines))
        self.assertEqual(sum(1 for x in lines if "in" in x), 7)

    def test_absent_name_keeps_everything(self):
        removed, lines = self.strip("P.nothing")
        self.assertFalse(removed)
        self.assertEqual(lines, EXPORT)

    def test_altered_candidates(self):
        nodes = {r["name"]: r for r in [
            node("P.target", "thm", ["P.b", "Nat"], ["P.a", "P.target"]),
            node("P.a", "thm"), node("P.b", "def"), node("Nat", "inductive", trusted=True),
        ]}
        self.assertEqual(kernels.altered_candidates(nodes, "P.target"), ["P.a", "P.b"])


class NanodaTest(unittest.TestCase):
    def test_config(self):
        cfg = kernels.nanoda_config(Path("core.ndjson"), 8)
        self.assertEqual(cfg["export_file_path"], str(Path("core.ndjson").resolve()))
        self.assertEqual(cfg["num_threads"], 8)
        self.assertEqual(cfg["permitted_axioms"], ["propext", "Quot.sound", "Classical.choice"])
        self.assertIs(cfg["unpermitted_axiom_hard_error"], False)
        self.assertIs(cfg["nat_extension"], True)
        self.assertIs(cfg["string_extension"], True)
        self.assertIs(cfg["print_success_message"], True)

    def test_checked(self):
        self.assertEqual(kernels.parse_checked("$ nanoda_bin x\nChecked 1439 declarations with no "
                                               "typechecker errors\n[exit 0]\n"), 1439)
        self.assertIsNone(kernels.parse_checked("declaration target depends on x which was not found"))

    def test_comparator(self):
        cfg = audit.comparator_config("P.target")
        self.assertEqual(cfg["theorem_names"], ["P.target"])
        self.assertEqual(cfg["external_kernels"], {"nanoda": ["nanoda_bin"]})
        self.assertEqual(audit.parse_judgement('info\n{"judgement": "accepted", "report": {}}'), "accepted")
        self.assertIsNone(audit.parse_judgement("no json"))


class SummaryTest(unittest.TestCase):
    CORPUS = {"git": "https://x/y", "commit": "a" * 40, "toolchain": "leanprover/lean4:v4.37.0-rc1",
              "target": "P.target", "subdir": ".", "license": "MIT", "challenge_module": "Challenge",
              "stages": ["graph", "core", "kernels", "audit"], "depth": 2, "explain_depth": 1}

    def test_run_argv(self):
        argv = measure.run_argv(self.CORPUS, Path("/p"), Path("/o"))
        self.assertEqual(argv, ["run", "/p", "P.target", "--out", "/o", "--challenge-module", "Challenge",
                                "--stages", "graph,core,kernels,audit", "--depth", "2",
                                "--explain-depth", "1"])
        c = dict(self.CORPUS, reference="corpora/x/Reference.lean")
        del c["challenge_module"]
        self.assertIn(str(REPO / "corpora/x/Reference.lean"), measure.run_argv(c, Path("/p"), Path("/o")))

    def test_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            jsonio.write_json(run / "core.json", {"project_decls": 10, "core_decls": 4, "ratio": 0.4})
            jsonio.write_json(run / "audit.json", {"axioms": ["propext"],
                                                   "comparator": {"exit": 0, "judgement": "accepted",
                                                                  "report": "reference/comparator.report.json"}})
            jsonio.write_json(run / "kernels.json", {
                "format": "lazarillo-kernels/1", "exporter": ["lake"], "export_roots": [], "dropped_roots": [],
                "lean": {"exit": 0, "log": "logs/a"}, "nanoda": {"exit": 0, "checked": 9, "log": "logs/b"},
                "con_leche": {"exit": 0, "log": "logs/c"},
                "altered": {"removed": "P.a", "lean_exit": 1, "nanoda_exit": 101, "con_leche_exit": 1}})
            jsonio.write_json(run / "timings.json", {"format": "lazarillo-timings/1", "stages": {
                "graph": {"wall_s": 1.5, "peak_rss_bytes": 10, "time_max_rss_kb": 1,
                          "log_time": "logs/graph.time", "log_rss": "logs/graph.rss"}}})
            s = measure.summary_json("c", self.CORPUS, run)
            empty = measure.summary_json("c", self.CORPUS, run / "missing")
        self.assertEqual(set(s), {"format", "corpus", "git", "commit", "toolchain", "target", "project_decls",
                                  "core_decls", "ratio", "axioms", "kernels", "comparator", "stages"})
        self.assertEqual(s["format"], "lazarillo-summary/1")
        self.assertEqual((s["project_decls"], s["core_decls"], s["ratio"]), (10, 4, 0.4))
        self.assertEqual(s["axioms"], ["propext"])
        self.assertEqual(s["comparator"], "accepted")
        self.assertEqual(s["kernels"], {"lean": {"exit": 0}, "nanoda": {"exit": 0, "checked": 9},
                                        "con_leche": {"exit": 0},
                                        "altered": {"removed": "P.a", "lean_exit": 1, "nanoda_exit": 101,
                                                    "con_leche_exit": 1}})
        self.assertEqual(s["stages"], {"graph": {"wall_s": 1.5, "peak_rss_bytes": 10, "time_max_rss_kb": 1}})
        self.assertIsNone(empty["kernels"])
        self.assertIsNone(empty["comparator"])
        self.assertIsNone(empty["axioms"])
        self.assertIsNone(empty["project_decls"])
        self.assertEqual(empty["stages"], {})


def find_elan():
    local = config.work_dir() / "elan" / "bin" / "elan"
    return str(local) if local.is_file() else shutil.which("elan")


def verification_ready():
    try:
        vbin = kernels.verification_bin()
    except (config.ConfigError, kernels.KernelsError, OSError):
        return False
    return (vbin / "nanoda_bin").is_file() and (config.work_dir() / "judge" / "lake-manifest.json").is_file()


@unittest.skipUnless(find_elan(), "elan not available")
@unittest.skipUnless(verification_ready(), "verification toolchain or judge not available")
@unittest.skipUnless(os.path.exists(runner.TIME_BIN), "/usr/bin/time not available")
class MiniKernelsIntegrationTest(unittest.TestCase):
    def test_mini_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, out = Path(tmp) / "mini", Path(tmp) / "out"
            shutil.copytree(FIXTURE, project, ignore=shutil.ignore_patterns(".lake", "lake-manifest.json"))
            build = subprocess.run(["lake", "build"], cwd=project, env=config.lean_env(),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(build.returncode, 0, build.stdout)
            proc = subprocess.run(
                [sys.executable, "-m", "lazarillo", "run", str(project), "Mini.target", "--out", str(out),
                 "--stages", "graph,core,kernels,audit"],
                cwd=REPO, env=runner.stage_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout)

            k = jsonio.read_json(out / "kernels.json")
            self.assertEqual(k["format"], "lazarillo-kernels/1")
            self.assertEqual(k["export_roots"][0], "Mini.target")
            self.assertEqual(k["lean"]["exit"], 0, (out / k["lean"]["log"]).read_text())
            self.assertEqual(k["nanoda"]["exit"], 0, (out / k["nanoda"]["log"]).read_text())
            self.assertEqual(k["altered"]["removed"], "Mini.helper")
            self.assertNotEqual(k["altered"]["lean_exit"], 0)
            self.assertNotEqual(k["altered"]["nanoda_exit"], 0)
            self.assertIsNone(jsonio.read_json(out / "audit.json")["comparator"])

            # Criterion 10: nanoda over an export of the target alone counts the graph's nodes.
            graph_nodes = len((out / "graph.ndjson").read_text(encoding="utf-8").splitlines())
            own = Path(tmp) / "target_only.ndjson"
            code = kernels.run_logged([*k["exporter"], "Mini", "--", "Mini.target"], project,
                                      config.lean_env(), Path(tmp) / "own-export.log", stdout_path=own)
            self.assertEqual(code, 0)
            cfg = Path(tmp) / "nanoda-own.json"
            jsonio.write_json(cfg, kernels.nanoda_config(own, kernels.cores()))
            log = Path(tmp) / "nanoda-own.log"
            vbin = kernels.verification_bin()
            self.assertEqual(kernels.run_logged([vbin / "nanoda_bin", cfg], Path(tmp),
                                                kernels.judge_env(vbin), log), 0)
            self.assertEqual(kernels.parse_checked(log.read_text()), graph_nodes)
            self.assertGreaterEqual(k["nanoda"]["checked"], graph_nodes)


if __name__ == "__main__":
    unittest.main()
