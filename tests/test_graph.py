import hashlib
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import config, graph, runner  # noqa: E402

FIXTURE = REPO / "tests" / "fixtures" / "mini"


def decl(name, module, kind, type_deps=(), value_deps=(), internal=False, value=True):
    h = hashlib.sha256(("t" + name).encode()).hexdigest()[:16]
    hv = hashlib.sha256(("v" + name).encode()).hexdigest()[:16] if value else None
    return {"name": name, "module": module, "kind": kind, "internal": internal,
            "type_deps": list(type_deps), "value_deps": list(value_deps),
            "hash_type": h, "hash_value": hv}


# A miniature of the `mini` fixture as Extract.lean would print it, inductive rule included.
SYNTH = [
    decl("Nat", "Init.Prelude", "inductive", [], ["Nat.zero", "Nat.succ", "Nat", "Nat.rec"], value=False),
    decl("Nat.zero", "Init.Prelude", "ctor", ["Nat"], ["Nat"], value=False),
    decl("Nat.succ", "Init.Prelude", "ctor", ["Nat"], ["Nat"], value=False),
    decl("Nat.rec", "Init.Prelude", "rec", ["Nat", "Nat.zero", "Nat.succ"], ["Nat"], value=False),
    decl("Nat.add", "Init.Prelude", "def", ["Nat"], ["Nat.rec", "Nat.succ", "Nat.rec"]),
    decl("Eq", "Init.Prelude", "inductive", [], ["Eq.refl", "Eq", "Eq.rec"], value=False),
    decl("Eq.refl", "Init.Prelude", "ctor", ["Eq"], ["Eq"], value=False),
    decl("Eq.rec", "Init.Prelude", "rec", ["Eq", "Eq.refl"], ["Eq"], value=False),
    decl("propext", "Init.Core", "axiom", ["Eq"], value=False),
    decl("Mini.Pair", "Mini", "inductive", ["Nat"], ["Mini.Pair.mk", "Mini.Pair", "Mini.Pair.rec"], value=False),
    decl("Mini.Pair.mk", "Mini", "ctor", ["Nat", "Mini.Pair"], ["Mini.Pair"], value=False),
    decl("Mini.Pair.rec", "Mini", "rec", ["Mini.Pair", "Mini.Pair.mk"], ["Mini.Pair"], value=False),
    decl("Mini.helper", "Mini", "def", ["Nat"], ["Mini.Pair.mk", "Nat.add"]),
    decl("Mini.helper_eq", "Mini", "thm", ["Eq", "Mini.helper", "Nat"], ["Mini.helper_eq._proof_1"]),
    decl("Mini.helper_eq._proof_1", "Mini", "thm", ["Eq", "Mini.helper"], ["Eq.refl", "propext"], internal=True),
    decl("Mini.target", "Mini", "thm", ["Eq", "Mini.helper", "Nat.add"], ["Mini.helper_eq", "Mini.helper_eq"]),
    decl("Mini.unused", "Mini", "def", ["Nat"], ["Nat.add"]),
]
TRUSTED_OF = {"Init.Prelude": True, "Init.Core": True, "Mini": False}


def synth_lines(rows=SYNTH):
    return [json.dumps(r) + "\n" for r in rows]


def load(rows=SYNTH):
    g = graph.Graph()
    g.load(synth_lines(rows), TRUSTED_OF)
    return g


def closure_names(g, target):
    return {g.name_of(r) for r in g.closure(target)}


class ClosureTest(unittest.TestCase):
    def test_closure_of_target(self):
        names = closure_names(load(), "Mini.target")
        self.assertIn("Mini.helper_eq", names)
        self.assertIn("Mini.helper_eq._proof_1", names)
        self.assertIn("propext", names)
        self.assertNotIn("Mini.unused", names)
        self.assertEqual(names, {r["name"] for r in SYNTH} - {"Mini.unused"})

    def test_inductive_rule(self):
        # `helper` mentions only the constructor; the constructor reaches its inductive,
        # and the inductive reaches its recursor.
        names = closure_names(load(), "Mini.helper")
        self.assertTrue({"Mini.Pair", "Mini.Pair.mk", "Mini.Pair.rec", "Nat", "Nat.rec"} <= names)
        self.assertNotIn("Mini.helper_eq", names)
        self.assertNotIn("Eq", names)

    def test_missing_constant_is_an_error(self):
        rows = [r for r in SYNTH if r["name"] != "Mini.helper_eq"]
        with self.assertRaisesRegex(graph.GraphError, "Mini.helper_eq"):
            load(rows).closure("Mini.target")

    def test_unknown_target(self):
        with self.assertRaises(graph.GraphError):
            load().closure("Mini.nope")

    def test_unknown_module(self):
        g = graph.Graph()
        with self.assertRaises(graph.GraphError):
            g.load(synth_lines([decl("X.y", "X", "def")]), TRUSTED_OF)

    def test_duplicate_keeps_first(self):
        g = load(SYNTH + [decl("Mini.unused", "Mini", "thm")])
        self.assertEqual(g.duplicates, ["Mini.unused"])
        rows = {r["name"]: r for r in g.rows(range(len(g)))}
        self.assertEqual(rows["Mini.unused"]["kind"], "def")


class OutputTest(unittest.TestCase):
    def write(self, out, rows):
        out.mkdir()
        g = load(rows)
        graph.write_outputs(g, "Mini.target", out)
        return (out / "graph.ndjson").read_bytes(), (out / "project_decls.txt").read_bytes()

    def test_order_and_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, decls = self.write(Path(tmp) / "a", SYNTH)
        lines = text.decode("utf-8").splitlines()
        rows = [json.loads(line) for line in lines]
        names = [r["name"] for r in rows]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), len(SYNTH) - 1)
        for r in rows:
            self.assertEqual(list(r), sorted(r))
            self.assertEqual(set(r), {"hash_type", "hash_value", "internal", "kind", "module", "name",
                                      "trusted", "type_deps", "value_deps"})
            self.assertEqual(r["type_deps"], sorted(set(r["type_deps"])))
            self.assertEqual(r["value_deps"], sorted(set(r["value_deps"])))
            self.assertIn(r["kind"], graph.KINDS)
        by_name = {r["name"]: r for r in rows}
        self.assertEqual(by_name["Mini.target"]["value_deps"], ["Mini.helper_eq"])
        self.assertFalse(by_name["Mini.target"]["trusted"])
        self.assertTrue(by_name["Nat"]["trusted"])
        self.assertIsNone(by_name["Nat"]["hash_value"])
        self.assertTrue(by_name["Mini.helper_eq._proof_1"]["internal"])

        src = next(r for r in SYNTH if r["name"] == "Mini.target")
        expected = ('{"hash_type":"%s","hash_value":"%s","internal":false,"kind":"thm","module":"Mini",'
                    '"name":"Mini.target","trusted":false,"type_deps":["Eq","Mini.helper","Nat.add"],'
                    '"value_deps":["Mini.helper_eq"]}') % (src["hash_type"], src["hash_value"])
        self.assertIn(expected, lines)

        self.assertEqual(decls.decode("utf-8"), "\n".join(sorted(
            r["name"] for r in SYNTH if r["module"] == "Mini")) + "\n")

    def test_byte_identical_for_any_input_order(self):
        shuffled = list(SYNTH)
        random.Random(7).shuffle(shuffled)
        with tempfile.TemporaryDirectory() as tmp:
            a = self.write(Path(tmp) / "a", SYNTH)
            b = self.write(Path(tmp) / "b", SYNTH)
            c = self.write(Path(tmp) / "c", shuffled)
        self.assertEqual(a, b)
        self.assertEqual(a, c)


MATHLIB_MANIFEST = {
    "version": "1.1.0",
    "packagesDir": ".lake/packages",
    "packages": [
        {"url": "https://github.com/leanprover-community/batteries", "type": "git", "subDir": None,
         "scope": "leanprover-community", "rev": "0" * 40, "name": "batteries", "manifestFile":
         "lake-manifest.json", "inputRev": "main", "inherited": False, "configFile": "lakefile.toml"},
        {"url": "https://github.com/leanprover-community/aesop", "type": "git", "subDir": None,
         "scope": "leanprover-community", "rev": "1" * 40, "name": "aesop", "manifestFile":
         "lake-manifest.json", "inputRev": "master", "inherited": False, "configFile": "lakefile.toml"},
    ],
    "name": "mathlib",
    "lakeDir": ".lake",
}


def touch(path: Path, size: int = 8) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def fake_project(root: Path) -> tuple[Path, Path]:
    project = root / "proj"
    touch(project / ".lake" / "build" / "lib" / "lean" / "Mini.olean")
    pkgs = project / ".lake" / "packages"
    touch(pkgs / "mathlib" / ".lake" / "build" / "lib" / "lean" / "Mathlib" / "Logic" / "Basic.olean")
    (pkgs / "mathlib" / "lake-manifest.json").write_text(json.dumps(MATHLIB_MANIFEST), encoding="utf-8")
    touch(pkgs / "batteries" / ".lake" / "build" / "lib" / "lean" / "Batteries" / "Data.olean")
    touch(pkgs / "extra" / ".lake" / "build" / "lib" / "lean" / "Extra.olean")
    touch(pkgs / "extra" / ".lake" / "build" / "lib" / "lean" / "Extra.ilean")
    tc_lib = root / "toolchain" / "lib" / "lean"
    touch(tc_lib / "Init" / "Prelude.olean", 100)
    touch(tc_lib / "Init" / "Prelude.olean.server", 10)
    touch(tc_lib / "Init" / "Prelude.olean.private", 1)
    touch(tc_lib / "Init" / "Core.olean")
    return project, tc_lib


class TrustTest(unittest.TestCase):
    def test_trusted_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, _ = fake_project(Path(tmp))
            self.assertEqual(graph.trusted_packages(project), {"mathlib", "batteries", "aesop"})
            self.assertEqual(graph.trusted_packages(Path(tmp) / "none"), {"mathlib"})

    def test_discover(self):
        with tempfile.TemporaryDirectory() as tmp:
            project, tc_lib = fake_project(Path(tmp))
            oleans = graph.discover(project, tc_lib, graph.trusted_packages(project))
        self.assertEqual([(o.module, o.trusted) for o in oleans], [
            ("Mini", False),
            ("Extra", False),
            ("Batteries.Data", True),
            ("Mathlib.Logic.Basic", True),
            ("Init.Core", True),
            ("Init.Prelude", True),
        ])
        self.assertEqual(next(o for o in oleans if o.module == "Init.Prelude").size, 111)

    def test_batches(self):
        olean = lambda m, s: graph.Olean(m, Path(m), s, True)  # noqa: E731
        items = [olean(f"M{i}", 10) for i in range(5)]
        self.assertEqual([len(b) for b in graph.make_batches(items, max_modules=2)], [2, 2, 1])
        self.assertEqual([len(b) for b in graph.make_batches(items, max_bytes=25)], [2, 2, 1])
        self.assertEqual([len(b) for b in graph.make_batches([olean("Big", 100)] + items, max_bytes=50)],
                         [1, 5])
        self.assertEqual(sum(len(b) for b in graph.make_batches(items)), 5)

    def test_build_graph_with_fake_extractor(self):
        rows = SYNTH + [
            decl("Mathlib.foo", "Mathlib.Logic.Basic", "def", ["Nat"], ["Nat.add"]),
            decl("Batteries.bar", "Batteries.Data", "def", ["Nat"], []),
            decl("Extra.baz", "Extra", "def", ["Nat"], []),
        ]
        calls = []

        def extract(project, batch, out_path, log_path, env):
            calls.append([o.module for o in batch])
            modules = {o.module for o in batch}
            out_path.write_text("".join(synth_lines([r for r in rows if r["module"] in modules])),
                                encoding="utf-8")

        with tempfile.TemporaryDirectory() as tmp:
            project, tc_lib = fake_project(Path(tmp))
            out = Path(tmp) / "out"
            g = graph.build_graph(project, "Mini.target", out, tc_lib=tc_lib, extract=extract, env={})
            decls = (out / "project_decls.txt").read_text(encoding="utf-8").splitlines()
            graph_rows = [json.loads(x) for x in (out / "graph.ndjson").read_text(encoding="utf-8").splitlines()]
            leftovers = list((out / "work").rglob("*.ndjson"))
        self.assertEqual(calls, [["Mini", "Extra", "Batteries.Data", "Mathlib.Logic.Basic",
                                  "Init.Core", "Init.Prelude"]])
        self.assertEqual(leftovers, [])
        self.assertIn("Extra.baz", decls)
        self.assertNotIn("Mathlib.foo", decls)
        self.assertNotIn("Batteries.bar", decls)
        self.assertNotIn("Nat", decls)
        flags = {r["name"]: r["trusted"] for r in g.rows(range(len(g)))}
        self.assertTrue(flags["Mathlib.foo"])
        self.assertTrue(flags["Batteries.bar"])
        self.assertFalse(flags["Extra.baz"])
        self.assertNotIn("Mini.unused", {r["name"] for r in graph_rows})


def find_elan():
    local = config.work_dir() / "elan" / "bin" / "elan"
    return str(local) if local.is_file() else shutil.which("elan")


@unittest.skipUnless(find_elan(), "elan not available")
@unittest.skipUnless(os.path.exists(runner.TIME_BIN), "/usr/bin/time not available")
class MiniIntegrationTest(unittest.TestCase):
    def run_graph(self, project: Path, out: Path) -> dict:
        proc = subprocess.run(
            [sys.executable, "-m", "lazarillo", "run", str(project), "Mini.target",
             "--out", str(out), "--stages", "graph"],
            cwd=REPO, env=runner.stage_env(), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(proc.returncode, 0, proc.stdout)
        lines = (out / "graph.ndjson").read_text(encoding="utf-8").splitlines()
        return {r["name"]: r for r in map(json.loads, lines)}

    def test_mini_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "mini"
            shutil.copytree(FIXTURE, project, ignore=shutil.ignore_patterns(".lake", "lake-manifest.json"))
            build = subprocess.run(["lake", "build"], cwd=project, env=config.lean_env(),
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(build.returncode, 0, build.stdout)

            nodes = self.run_graph(project, Path(tmp) / "out")
            self.assertIn("Mini.target", nodes)
            self.assertIn("Mini.helper_eq", nodes)
            self.assertIn("Mini.helper", nodes)
            self.assertNotIn("Mini.unused", nodes)
            self.assertEqual(nodes["Mini.target"]["kind"], "thm")
            self.assertFalse(nodes["Mini.target"]["trusted"])
            self.assertEqual(nodes["Mini.target"]["module"], "Mini")
            self.assertIn("Mini.helper", nodes["Mini.helper_eq"]["type_deps"])
            self.assertEqual(nodes["Mini.Pair"]["kind"], "inductive")
            self.assertIn("Mini.Pair.rec", nodes)
            self.assertEqual(nodes["Mini.Pair.rec"]["kind"], "rec")
            self.assertIn("Mini.Pair.rec", nodes["Mini.Pair"]["value_deps"])
            self.assertIn("Mini.Pair.mk", nodes["Mini.Pair"]["value_deps"])
            self.assertTrue(nodes["Nat"]["trusted"])
            self.assertRegex(nodes["Mini.target"]["hash_type"], r"^[0-9a-f]{16}$")

            decls = (Path(tmp) / "out" / "project_decls.txt").read_text(encoding="utf-8").splitlines()
            self.assertIn("Mini.unused", decls)
            self.assertIn("Mini.target", decls)
            self.assertNotIn("Nat", decls)

            self.run_graph(project, Path(tmp) / "out2")
            for name in ("graph.ndjson", "project_decls.txt"):
                self.assertEqual((Path(tmp) / "out" / name).read_bytes(),
                                 (Path(tmp) / "out2" / name).read_bytes(), name)


if __name__ == "__main__":
    unittest.main()
