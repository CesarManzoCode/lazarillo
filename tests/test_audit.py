import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import audit, core, jsonio  # noqa: E402


def node(name, kind, type_deps=(), value_deps=(), trusted=False, internal=False,
         module="P", ht="1", hv="2"):
    return {"name": name, "kind": kind, "module": module, "trusted": trusted, "internal": internal,
            "type_deps": sorted(type_deps), "value_deps": sorted(value_deps),
            "hash_type": ht.rjust(16, "0"), "hash_value": hv.rjust(16, "0") if hv else None}


ROWS = [
    node("Nat", "inductive", trusted=True, module="Init.Prelude", hv=None),
    node("propext", "axiom", trusted=True, module="Init.Core", hv=None),
    node("sorryAx", "axiom", trusted=True, module="Init.Prelude", hv=None),
    node("Lean.ofReduceBool", "axiom", trusted=True, module="Init.Core", hv=None),
    # A trusted node that (artificially) mentions a project node: traversal must stop here.
    node("Mathlib.Foo", "def", ["Nat"], ["P.leak"], trusted=True, module="Mathlib.Foo"),
    node("P.target", "thm", ["P.good", "Nat", "Mathlib.Foo"], ["P.main", "P.target._proof_1"]),
    node("P.target._proof_1", "thm", ["P.good"], ["propext"], internal=True),
    node("P.good", "def", ["P.Carrier"], ["P.helper", "P.bound"]),
    node("P.Carrier", "def", ["Nat"], ["Nat"]),
    node("P.helper", "def", ["Nat"], ["Nat"]),
    node("P.bound", "def", ["Nat"], ["P.bound_lemma"]),
    node("P.bound_lemma", "thm", ["P.tyDep"], ["P.secret"]),
    node("P.tyDep", "def", ["Nat"], []),
    node("P.secret", "def", ["Nat"], ["Nat"]),
    node("P.leak", "def", ["Nat"], []),
    node("P.main", "thm", ["P.good"], ["P.secret", "sorryAx"]),
    node("P.ax", "axiom", ["Nat"], hv=None),
]
NODES = {r["name"]: r for r in ROWS}
PROJECT = sorted(r["name"] for r in ROWS if not r["trusted"])


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


class CoreTest(unittest.TestCase):
    def test_core_and_ratio(self):
        data = core.core_json(NODES, 40, "P.target", "leanprover/lean4:v4.37.0-rc1")
        self.assertEqual(data["format"], "lazarillo-core/1")
        self.assertEqual(data["core"], PROJECT)
        self.assertEqual(data["core_decls"], len(PROJECT))
        self.assertEqual(data["closure_decls"], len(ROWS))
        self.assertEqual(data["project_decls"], 40)
        self.assertEqual(data["ratio"], round(len(PROJECT) / 40, 6))

    def test_run_core(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, proj = Path(tmp) / "out", Path(tmp) / "proj"
            out.mkdir()
            write(proj / "lean-toolchain", "leanprover/lean4:v4.37.0-rc1\n")
            jsonio.write_ndjson(out / "graph.ndjson", sorted(ROWS, key=lambda r: r["name"]))
            jsonio.write_lines(out / "project_decls.txt", PROJECT + ["P.unused"])
            args = SimpleNamespace(out=str(out), project_dir=str(proj), theorem="P.target")
            self.assertEqual(core.run_core(args), 0)
            first = (out / "core.json").read_bytes()
            data = json.loads(first)
            self.assertEqual(data["toolchain"], "leanprover/lean4:v4.37.0-rc1")
            self.assertEqual(data["project_decls"], len(PROJECT) + 1)
            self.assertEqual(core.run_core(args), 0)
            self.assertEqual((out / "core.json").read_bytes(), first)


class GraphFactsTest(unittest.TestCase):
    def test_axioms_and_uses(self):
        self.assertEqual(audit.axioms(NODES), ["Lean.ofReduceBool", "P.ax", "propext", "sorryAx"])
        u = audit.uses(NODES)
        self.assertTrue(u["sorry"])
        self.assertEqual(u["native_decide"], ["Lean.ofReduceBool"])
        self.assertEqual(u["project_axioms"], ["P.ax"])

    def test_statement_only_by_types(self):
        self.assertEqual(audit.statement_decls(NODES, "P.target"), ["P.Carrier", "P.good"])

    def test_frontier(self):
        front = audit.frontier(NODES, "P.target")
        # Values of defs are followed (helper, bound) and so are types of the theorem
        # reached that way (tyDep), but not its value (secret).
        self.assertEqual(front, ["P.Carrier", "P.bound", "P.bound_lemma", "P.good", "P.helper", "P.tyDep"])
        self.assertNotIn("P.secret", front)
        # Stops at the trusted base.
        self.assertNotIn("P.leak", front)
        self.assertNotIn("Mathlib.Foo", front)
        self.assertNotIn("Nat", front)
        # The target's value (main, _proof_1) is not part of the frontier.
        self.assertNotIn("P.main", front)

    def test_core_lemmas(self):
        self.assertEqual([d["name"] for d in audit.core_lemmas(NODES)],
                         ["P.bound_lemma", "P.main", "P.target"])
        self.assertEqual(audit.core_lemmas(NODES)[0], {"name": "P.bound_lemma", "module": "P", "kind": "thm"})


class SourceTest(unittest.TestCase):
    def test_strip_comments(self):
        text = "a /- x /- y -/ sorry -/ b\nc -- sorry\n/- one\ntwo -/d\n/-- doc -/ e"
        stripped = audit.strip_comments(text)
        self.assertNotIn("sorry", stripped)
        self.assertNotIn("doc", stripped)
        self.assertEqual(stripped.count("\n"), text.count("\n"))
        self.assertEqual(stripped.split("\n")[0].split(), ["a", "b"])
        self.assertEqual(stripped.split("\n")[3].strip(), "d")

    def test_scan_text(self):
        text = ("theorem t : True := by sorry\n"
                "def sorry_free := 1\n#check Foo.sorry\n#check sorry'\n"
                "private noncomputable axiom a1 : Nat\naxiom a2 : Nat\n"
                "  protected unsafe axiom a3 : Nat\ntheorem axiom_like : True := trivial\n"
                "example : 2 = 2 := by native_decide\nexample : True := by admit\n")
        self.assertEqual(audit.scan_text(text), {"sorry": 1, "admit": 1, "axiom": 3, "native_decide": 1})

    def test_imports(self):
        text = "module\npublic import A.B\nmeta import C\nimport D E\nimport all F\ndef x := 1\n"
        self.assertEqual(audit.imports_of(text), ["A.B", "C", "D", "E", "F"])

    def test_source_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            write(proj / "lakefile.toml",
                  'name = "proj"\n\n[[lean_lib]]\nname = "Proj"\nsrcDir = "src"\n\n'
                  '[[lean_lib]]\nname = "Hidden"\nsrcDir = ".lake/hidden"\n')
            write(proj / "Main.lean",
                  "public import Proj.A\nmeta import Mathlib.Tactic\nimport Proj.Missing\n"
                  "/- outer /- inner sorry -/ still sorry -/\n-- sorry admit\n"
                  "theorem t : True := by sorry\n")
            write(proj / "src" / "Proj" / "A.lean",
                  "import Proj.B\nprivate noncomputable axiom ax1 : Nat\naxiom ax2 : Nat\n"
                  "  protected unsafe axiom ax3 : Nat\ntheorem axiom_like : True := trivial\n"
                  "def sorry_free := 1\ntheorem u : 2 = 2 := by native_decide\n"
                  "example : True := by admit\n#check Foo.sorry\n/-- doc with sorry -/\ndef x := 1\n")
            write(proj / "Proj" / "B.lean", "import Main\ntheorem b : True := by sorry -- sorry\n")
            # Only reachable through a srcDir inside `.lake/`: never counted.
            write(proj / ".lake" / "hidden" / "Proj" / "Missing.lean", "theorem m : True := by sorry\n")
            self.assertEqual(audit.source_scan(proj, "Main"),
                             {"files": 3, "sorry": 2, "admit": 1, "axiom": 3, "native_decide": 1})


class FlattenTest(unittest.TestCase):
    def test_flatten_order_and_single_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp)
            write(proj / "Challenge.lean",
                  "import Mathlib.Data\nimport Proj.Defs\npublic import Proj.Base\n\n"
                  "theorem Proj.target : Proj.good 1 := by sorry\n")
            write(proj / "Proj" / "Defs.lean",
                  "/- Copyright -/\nimport Proj.Base\nimport Mathlib.Order\n\n"
                  "def Proj.good (n : Nat) : Prop := Proj.base n < 2\n")
            write(proj / "Proj" / "Base.lean", "import Mathlib.Data\n\ndef Proj.base (n : Nat) : Nat := n\n")
            text, imports = audit.flatten(proj, "Challenge")
            self.assertEqual(imports, ["Mathlib.Data", "Mathlib.Order"])
            self.assertTrue(text.startswith("import Mathlib.Data\nimport Mathlib.Order\n"))
            self.assertEqual(text.count("import "), 2)
            self.assertEqual(text.count("def Proj.base"), 1)
            self.assertEqual(text.count("def Proj.good"), 1)
            base, good = text.index("def Proj.base"), text.index("def Proj.good")
            self.assertLess(base, good)
            self.assertLess(good, text.index("theorem Proj.target"))

    def test_missing_challenge(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(audit.AuditError):
                audit.flatten(Path(tmp), "Nope")


class FrontierDiffTest(unittest.TestCase):
    def test_diff(self):
        front = audit.frontier(NODES, "P.target")
        ref = [
            node("P.good", "def"),                    # same fingerprint
            node("P.Carrier", "def", hv="9"),         # value differs
            node("P.bound", "def"),
            node("P.bound_lemma", "thm", hv="9"),     # theorem: only the type counts
            node("P.tyDep", "def", ht="9"),           # type differs
            node("P.secret", "def", hv="9"),          # out of frontier, different
            node("P.main", "thm"),                    # out of frontier, same
            node("P.target", "thm", hv="9"),          # `sorry` proof: not a change
            node("Ref.only", "def", hv="9"),          # not in the core
            node("Nat", "inductive", ht="9", hv=None),  # trusted
        ]                                             # P.helper is missing
        diff = audit.frontier_diff(NODES, front, ref)
        self.assertEqual(diff, {"changed": ["P.Carrier", "P.tyDep"],
                                "missing_in_reference": ["P.helper"],
                                "out_of_frontier_changed": ["P.secret"]})

    def test_identical_reference(self):
        front = audit.frontier(NODES, "P.target")
        diff = audit.frontier_diff(NODES, front, [NODES[n] for n in front])
        self.assertEqual(diff, audit.empty_diff())


class RunAuditTest(unittest.TestCase):
    def test_without_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            out, proj = Path(tmp) / "out", Path(tmp) / "proj"
            out.mkdir()
            write(proj / "P.lean", "theorem P.target : True := by sorry\n")
            jsonio.write_ndjson(out / "graph.ndjson", sorted(ROWS, key=lambda r: r["name"]))
            args = SimpleNamespace(out=str(out), project_dir=str(proj), theorem="P.target",
                                   challenge_module=None, reference=None)
            self.assertEqual(audit.run_audit(args), 0)
            data = json.loads((out / "audit.json").read_text(encoding="utf-8"))
            self.assertEqual(set(data), {"format", "target", "axioms", "nonstandard_axioms", "uses",
                                         "source_scan", "statement_decls", "frontier", "core_lemmas",
                                         "reference", "frontier_diff", "statement_changed", "comparator"})
            self.assertEqual(data["format"], "lazarillo-audit/1")
            self.assertEqual(data["nonstandard_axioms"], ["Lean.ofReduceBool", "P.ax", "sorryAx"])
            self.assertIsNone(data["reference"])
            self.assertIsNone(data["comparator"])
            self.assertEqual(data["frontier_diff"], audit.empty_diff())
            self.assertFalse(data["statement_changed"])
            self.assertEqual(data["source_scan"]["files"], 1)
            self.assertEqual(data["source_scan"]["sorry"], 1)


if __name__ == "__main__":
    unittest.main()
