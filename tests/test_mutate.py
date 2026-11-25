import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import mutate  # noqa: E402

# Two frontier definitions inside `namespace Demo`. Docstrings, comments and the signature of
# `big` (`Fin 7`) hold literals and operators that must not be mutated.
REFERENCE = """import Mathlib

-- lazarillo: flattened from Challenge
namespace Demo

/-- Small numbers: 7 < 8 ∧ 9 ≤ 10 (docstring, not mutated). -/
def small (n : ℕ) : Prop := n < 3 ∧ 0 ≤ n

def big (n : Fin 7) : Prop :=
  -- a comment with 5 < 6
  10 ≤ n.val

end Demo

theorem Demo.goal (n : Fin 7) (h : Demo.small n.val) : Demo.big n := by
  sorry
"""

SMALL = "def small (n : ℕ) : Prop := n < 3 ∧ 0 ≤ n"
BIG_BODY = "  10 ≤ n.val"
BIG_HEAD = "def big (n : Fin 7) : Prop :=\n  -- a comment"
C0 = "-- lazarillo: C0 control"

# A module of the project: the same short name in another namespace, then the leaf inside
# `namespace Zeta` / `section Helpers`, followed by a theorem.
SOURCE = """import Mathlib

namespace Other

def leaf (n : ℕ) : ℕ := n + 100

end Other

namespace Zeta

section Helpers

variable (k : ℕ)

/-- A leaf definition. -/
noncomputable def leaf (n : ℕ) : ℕ :=
  n + 2
    * 3

theorem leaf_pos (n : ℕ) : 0 < leaf n + 1 := by
  omega

end Helpers

end Zeta
"""

LEAF_BLOCK = "noncomputable def leaf (n : ℕ) : ℕ :=\n  n + 2\n    * 3\n"

PLAIN = "import Mathlib\n\ndef plain (n : ℕ) : ℕ := n\n"


def node(name, kind="def", deps=(), trusted=False, internal=False, module="Demo"):
    return {"name": name, "kind": kind, "module": module, "trusted": trusted, "internal": internal,
            "type_deps": [], "value_deps": sorted(deps), "hash_type": "0" * 16, "hash_value": None}


NODES = {n["name"]: n for n in [
    node("Nat", "inductive", trusted=True, module="Init.Prelude"),
    node("HAdd.hAdd", trusted=True, module="Init.Prelude"),
    node("Demo.small", deps=["Nat"]),
    node("Demo.small._proof_1", "thm", deps=["Nat"], internal=True),
    node("Demo.big", deps=["Nat"]),
    node("Demo.missing", deps=["Nat"]),
    node("Zeta.leaf", deps=["Nat", "HAdd.hAdd"], module="Zeta.Defs"),
    node("Zeta.leaf_pos", "thm", deps=["Zeta.leaf"], module="Zeta.Defs"),
    node("Zeta.uses", deps=["Zeta.leaf"], module="Zeta.Defs"),
    node("Zeta.aux._proof_1", deps=["Nat"], internal=True, module="Zeta.Defs"),
    node("plain", deps=["Nat"], module="Plain"),
]}
CORE = sorted(n for n, r in NODES.items() if not r["trusted"])
FRONTIER = ["Demo.big", "Demo.missing", "Demo.small", "Demo.small._proof_1"]


def expected(old, new):
    assert REFERENCE.count(old) == 1, old
    return REFERENCE.replace(old, new)


class TestFrontierCandidates(unittest.TestCase):
    def test_candidates_and_controls(self):
        got = mutate.frontier_candidates(REFERENCE, FRONTIER, NODES)
        want = [
            mutate.Candidate("Demo.big", "M1", True, expected(BIG_BODY, "  11 ≤ n.val")),
            mutate.Candidate("Demo.big", "M2", True, expected(BIG_BODY, "  10 < n.val")),
            mutate.Candidate("Demo.big", "C0", True,
                             expected(BIG_HEAD, "def big (n : Fin 7) : Prop :=\n  " + C0 + "\n  -- a comment")),
            mutate.Candidate("Demo.small", "M1", True, expected(SMALL, SMALL.replace("< 3", "< 4"))),
            mutate.Candidate("Demo.small", "M1", True, expected(SMALL, SMALL.replace("0 ≤", "1 ≤"))),
            mutate.Candidate("Demo.small", "M2", True, expected(SMALL, SMALL.replace("n < 3", "n ≤ 3"))),
            mutate.Candidate("Demo.small", "M2", True, expected(SMALL, SMALL.replace("0 ≤ n", "0 < n"))),
            mutate.Candidate("Demo.small", "M3", True, expected(SMALL, SMALL.replace("∧", "∨"))),
            mutate.Candidate("Demo.small", "C0", True,
                             expected(SMALL, "def small (n : ℕ) : Prop :=\n  " + C0 + "\n  n < 3 ∧ 0 ≤ n")),
        ]
        self.assertEqual([(c.site, c.operator) for c in got], [(c.site, c.operator) for c in want])
        for g, w in zip(got, want):
            self.assertEqual(g, w)

    def test_ids_are_stable(self):
        first = list(mutate.numbered(mutate.frontier_candidates(REFERENCE, FRONTIER, NODES)))
        second = list(mutate.numbered(mutate.frontier_candidates(REFERENCE, FRONTIER, NODES)))
        self.assertEqual(first, second)
        self.assertEqual([cid for cid, _ in first], [f"m00{i}" for i in range(1, 10)])
        self.assertEqual(mutate.candidate_id(12), "m012")

    def test_operators_skip_longer_tokens(self):
        s = "a <;> b => c <| d >>= e ≤ f + ℝ≥0 + p.1 + x2 + 1.5 + 7"
        got = [(op, s[a:b], r) for op, a, b, r in mutate.occurrences(s, 0, len(s))]
        self.assertEqual(got, [("M1", "7", "8"), ("M2", "≤", "<")])

    def test_mask_keeps_offsets(self):
        text = 'a /- x /- y -/ 1 -/ b -- 2\n"3 \\" 4" 5'
        masked = mutate.mask(text)
        self.assertEqual(len(masked), len(text))
        self.assertEqual(masked.split(), ["a", "b", "5"])


class TestLeaves(unittest.TestCase):
    def test_block_inside_namespace_and_section(self):
        block = mutate.locate(SOURCE, "Zeta.leaf")
        self.assertIsNotNone(block)
        self.assertEqual(SOURCE[block.start:block.end], LEAF_BLOCK)
        self.assertEqual(SOURCE[block.body:block.end], "\n  n + 2\n    * 3\n")
        other = mutate.locate(SOURCE, "Other.leaf")
        self.assertEqual(SOURCE[other.start:other.end], "def leaf (n : ℕ) : ℕ := n + 100\n")
        self.assertIsNone(mutate.locate(SOURCE, "leaf"))
        self.assertIsNone(mutate.locate(SOURCE, "Zeta.Helpers.leaf"))

    def test_leaf_defs(self):
        self.assertEqual(mutate.leaf_defs(NODES, CORE, ["Demo.small"]), ["Demo.big", "Demo.missing",
                                                                         "Zeta.leaf", "plain"])

    def test_leaf_candidates(self):
        sources = {"Zeta.Defs": SOURCE, "Plain": PLAIN}
        got = list(mutate.leaf_candidates(REFERENCE, NODES, CORE, ["Demo.small"], sources.get))
        copy = (REFERENCE + "\n-- lazarillo: copy of Zeta.leaf\nnamespace Zeta\nnoncomputable section\n\n"
                + LEAF_BLOCK + "\nend\nend Zeta\n")
        plain = (REFERENCE + "\n-- lazarillo: copy of plain\nnoncomputable section\n\n"
                 + "def plain (n : ℕ) : ℕ :=\n  " + C0 + "\n  n\n\nend\n")
        # Demo.big is already in the reference and Demo.missing has no source: both skipped.
        self.assertEqual(got, [
            mutate.Candidate("Zeta.leaf", "M1", False, copy.replace("  n + 2\n", "  n + 3\n")),
            mutate.Candidate("plain", "C0", False, plain),
        ])


RAW = """{"version": "0.1.0",
 "sandboxed": true,
 "report":
 {"kernel_reports":
  {"Lean default": {"output": {"proc": {"stdout": "", "stderr": ""}}, "judgement": "%s"}},
  "compare_statements":
  {"output": {"str": {"string": "%s"}}, "judgement": "%s"},
  "check_axioms":
  {"output": {"str": {"string": "Illegal axiom detected: 'sorryAx'"}}, "judgement": "failure"}},
 "judgement": "rejected"}
"""


class TestVerdicts(unittest.TestCase):
    def test_compare_statements(self):
        failure = RAW % ("skipped", "Challenge and solution theorem statement do not match", "failure")
        success = RAW % ("success", "", "success")
        self.assertEqual(mutate.compare_statements(failure), "failure")
        self.assertEqual(mutate.compare_statements("comparator: starting\n" + success), "success")
        self.assertIsNone(mutate.compare_statements(""))
        self.assertIsNone(mutate.compare_statements('{"judgement": "rejected"}'))

    def test_classification(self):
        self.assertEqual(mutate.classify(True, True), "statement_change")
        self.assertEqual(mutate.classify(True, False), "statement_change")
        self.assertEqual(mutate.classify(False, False), "out_of_frontier")
        self.assertEqual(mutate.classify(False, True), "no_change")


if __name__ == "__main__":
    unittest.main()
