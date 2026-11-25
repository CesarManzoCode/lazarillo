import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import config, jsonio, runner, tree  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "mini"


def node(name, kind="thm", deps=(), value_deps=(), trusted=False, internal=False, module="P.A"):
    return {"name": name, "kind": kind, "module": module, "trusted": trusted, "internal": internal,
            "type_deps": sorted(deps), "value_deps": sorted(value_deps),
            "hash_type": "0" * 16, "hash_value": None}


# T uses b and a (a only through the internal T._proof_1, which also reaches c through
# another internal); a and b both use d (parent must be a); d uses e; Nat is trusted.
ROWS = [
    node("Nat", "inductive", trusted=True, module="Init.Prelude"),
    node("Lean.aux._proof_1", trusted=True, internal=True, module="Init.Core", value_deps=["P.z"]),
    node("P.T", deps=["P.b", "Nat"], value_deps=["P.T._proof_1", "Lean.aux._proof_1"]),
    node("P.T._proof_1", internal=True, value_deps=["P.a", "P.T.match_1"]),
    node("P.T.match_1", "def", internal=True, value_deps=["P.c", "Nat"]),
    node("P.a", value_deps=["P.d", "P.a"]),
    node("P.b", "def", value_deps=["P.d"], module="P.B"),
    node("P.c", "def", deps=["Nat"]),
    node("P.d", "def", value_deps=["P.e", "P.d._proof_2"]),
    node("P.d._proof_2", internal=True, value_deps=["P.a"]),
    node("P.e", "def"),
    node("P.z", "def"),
]
NODES = {r["name"]: r for r in ROWS}


class StructureTest(unittest.TestCase):
    def test_collapse_internals(self):
        self.assertEqual(tree.collapsed_uses(NODES, "P.T"), ["P.a", "P.b", "P.c"])
        self.assertEqual(tree.collapsed_uses(NODES, "P.a"), ["P.d"])  # no self edge
        self.assertEqual(tree.collapsed_uses(NODES, "P.d"), ["P.a", "P.e"])
        self.assertEqual(tree.collapsed_uses(NODES, "P.c"), [])

    def test_bfs_alphabetical_parent(self):
        t = tree.bfs(NODES, "P.T", "all")
        self.assertEqual(t["P.T"], {"depth": 0, "parent": None, "uses": ["P.a", "P.b", "P.c"]})
        self.assertEqual(t["P.d"]["parent"], "P.a")
        self.assertEqual(t["P.d"]["depth"], 2)
        self.assertEqual(t["P.e"]["depth"], 3)
        for name in t:
            self.assertFalse(NODES[name]["internal"])
            self.assertFalse(NODES[name]["trusted"])
        self.assertNotIn("P.z", t)  # reachable only through the trusted base

    def test_depth_limit(self):
        self.assertEqual(sorted(tree.bfs(NODES, "P.T", 0)), ["P.T"])
        self.assertEqual(sorted(tree.bfs(NODES, "P.T", 1)), ["P.T", "P.a", "P.b", "P.c"])
        self.assertEqual(sorted(tree.bfs(NODES, "P.T", 2)), ["P.T", "P.a", "P.b", "P.c", "P.d"])
        self.assertEqual(sorted(tree.bfs(NODES, "P.T", "all")),
                         ["P.T", "P.a", "P.b", "P.c", "P.d", "P.e"])
        self.assertEqual(tree.bfs(NODES, "P.T", 3), tree.bfs(NODES, "P.T", "all"))

    def test_uses_restricted_to_tree(self):
        nodes = tree.structure(NODES, "P.T", 2)
        names = {n["name"] for n in nodes}
        by = {n["name"]: n for n in nodes}
        for n in nodes:
            self.assertTrue(set(n["uses"]) <= names, n)
            self.assertEqual(n["uses"], sorted(n["uses"]))
        self.assertEqual(by["P.d"]["uses"], ["P.a"])  # P.e is beyond depth 2
        self.assertEqual(by["P.a"]["children"], ["P.d"])
        self.assertEqual(by["P.b"]["children"], [])
        self.assertEqual(by["P.T"]["children"], ["P.a", "P.b", "P.c"])
        self.assertEqual([n["name"] for n in nodes], ["P.T", "P.a", "P.b", "P.c", "P.d"])
        for n in nodes:
            if n["parent"] is not None:
                self.assertIn(n["name"], by[n["parent"]]["children"])
                self.assertEqual(n["depth"], by[n["parent"]]["depth"] + 1)
            self.assertIsNone(n["explanation"])

    def test_target_errors(self):
        with self.assertRaises(tree.TreeError):
            tree.bfs(NODES, "Nat", "all")
        with self.assertRaises(tree.TreeError):
            tree.bfs(NODES, "P.T._proof_1", "all")
        with self.assertRaises(tree.TreeError):
            tree.bfs(NODES, "P.missing", "all")


GOALS_A = [
    {"name": "P.T", "range": [3, 6], "statement": "∀ (n : Nat), P.b n = n",
     "tactics": [{"tactic": "Lean.Parser.Tactic.omega", "range": [5, 5], "before": ["n : Nat\n⊢ P.b n = n"]}]},
    {"name": "P.a", "range": [8, 9], "statement": "True", "tactics": []},
    {"name": "P.T._proof_1", "range": None, "statement": "True", "tactics": []},
]
GOALS_B = [{"name": "P.b", "range": [1, 2], "statement": "Nat → Nat", "tactics": []}]


class GoalsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.project = self.root / "proj"
        (self.project / "P").mkdir(parents=True)
        (self.project / "P" / "A.lean").write_text("-- a\n", encoding="utf-8")
        (self.project / "P" / "B.lean").write_text("-- b\n", encoding="utf-8")
        self.out = self.root / "out"
        self.out.mkdir()
        jsonio.write_ndjson(self.out / "graph.ndjson", sorted(ROWS, key=lambda r: r["name"]))
        self.calls = []

    def tearDown(self):
        self.tmp.cleanup()

    def fake_run(self, project, path, module, dest, log, env):
        self.calls.append((Path(path).relative_to(self.project.resolve()).as_posix(), module))
        rows = {"P.A": GOALS_A, "P.B": GOALS_B}[module]
        jsonio.write_ndjson(dest, rows)
        log.write_text("fake\n", encoding="utf-8")
        return 0

    def args(self, depth):
        return SimpleNamespace(out=str(self.out), project_dir=str(self.project), theorem="P.T",
                               depth=depth, explain_depth=1)

    def test_run_tree_merges_goals(self):
        self.assertEqual(tree.run_tree(self.args("all"), run=self.fake_run), 0)
        # One run per distinct file, in file order.
        self.assertEqual(self.calls, [("P/A.lean", "P.A"), ("P/B.lean", "P.B")])
        data = jsonio.read_json(self.out / "tree.json")
        self.assertEqual(data["format"], "lazarillo-tree/1")
        self.assertEqual(data["target"], "P.T")
        self.assertEqual(data["depth_limit"], "all")
        self.assertEqual(data["explain_depth"], 1)
        self.assertEqual(data["llm"], {})
        by = {n["name"]: n for n in data["nodes"]}
        t = by["P.T"]
        self.assertEqual(t["file"], "P/A.lean")
        self.assertEqual(t["range"], [3, 6])
        self.assertTrue(t["tactic_proof"])
        self.assertEqual(t["goals"], GOALS_A[0]["tactics"])
        self.assertEqual(t["statement"], "∀ (n : Nat), P.b n = n")
        self.assertFalse(by["P.a"]["tactic_proof"])
        self.assertEqual(by["P.a"]["goals"], [])
        self.assertEqual(by["P.b"]["file"], "P/B.lean")
        self.assertEqual(by["P.b"]["statement"], "Nat → Nat")
        # Not reported by Goals.lean: source fields stay empty.
        self.assertEqual(by["P.e"]["file"], "P/A.lean")
        self.assertIsNone(by["P.e"]["range"])
        self.assertIsNone(by["P.e"]["statement"])
        self.assertFalse(by["P.e"]["tactic_proof"])
        self.assertNotIn("P.T._proof_1", by)

    def test_missing_source_file(self):
        (self.project / "P" / "B.lean").unlink()
        self.assertEqual(tree.run_tree(self.args(1), run=self.fake_run), 0)
        self.assertEqual(self.calls, [("P/A.lean", "P.A")])
        by = {n["name"]: n for n in jsonio.read_json(self.out / "tree.json")["nodes"]}
        self.assertIsNone(by["P.b"]["file"])
        self.assertIsNone(by["P.b"]["statement"])

    def test_deterministic(self):
        tree.run_tree(self.args(2), run=self.fake_run)
        first = (self.out / "tree.json").read_bytes()
        tree.run_tree(self.args(2), run=self.fake_run)
        self.assertEqual((self.out / "tree.json").read_bytes(), first)

    def test_failed_goals_run(self):
        def failing(project, path, module, dest, log, env):
            log.write_text("boom\n", encoding="utf-8")
            return 1
        self.assertEqual(tree.run_tree(self.args(1), run=failing), 0)
        by = {n["name"]: n for n in jsonio.read_json(self.out / "tree.json")["nodes"]}
        self.assertIsNone(by["P.T"]["statement"])

    def test_missing_graph(self):
        (self.out / "graph.ndjson").unlink()
        self.assertEqual(tree.run_tree(self.args(1), run=self.fake_run), 1)


def find_elan():
    local = config.work_dir() / "elan" / "bin" / "elan"
    return str(local) if local.is_file() else shutil.which("elan")


@unittest.skipUnless(find_elan(), "elan not available")
@unittest.skipUnless(os.path.exists(runner.TIME_BIN), "/usr/bin/time not available")
class MiniTreeIntegrationTest(unittest.TestCase):
    def test_mini_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, out = Path(tmp) / "mini", Path(tmp) / "out"
            shutil.copytree(FIXTURE, project, ignore=shutil.ignore_patterns(".lake", "lake-manifest.json"))
            build = subprocess.run(["lake", "build"], cwd=project, env=config.lean_env(),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(build.returncode, 0, build.stdout)
            proc = subprocess.run(
                [sys.executable, "-m", "lazarillo", "run", str(project), "Mini.target", "--out", str(out),
                 "--stages", "graph,core,tree", "--depth", "all"],
                cwd=REPO, env=runner.stage_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(proc.returncode, 0, proc.stdout)
            data = jsonio.read_json(out / "tree.json")
            self.assertEqual(data["depth_limit"], "all")
            by = {n["name"]: n for n in data["nodes"]}
            self.assertEqual(data["nodes"][0]["name"], "Mini.target")
            self.assertNotIn("Mini.unused", by)
            h = by["Mini.helper_eq"]
            self.assertEqual(h["file"], "Mini.lean")
            self.assertEqual(h["parent"], "Mini.target")
            self.assertTrue(h["tactic_proof"], json.dumps(h, ensure_ascii=False))
            self.assertTrue(any(g["before"] for g in h["goals"]), h["goals"])
            self.assertIsNotNone(h["range"])
            self.assertIn("helper", h["statement"])
            self.assertIn("Mini.helper", by)
            for n in data["nodes"]:
                self.assertIsNone(n["explanation"])
                self.assertTrue(set(n["uses"]) <= set(by))


if __name__ == "__main__":
    unittest.main()
