import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import __main__ as cli  # noqa: E402
from lazarillo import blueprint, jsonio  # noqa: E402

# Two chapters. `ghost` is commented out; `root` takes its `\uses` from the following proof
# (an unlabelled remark in between does not break the link); `l1` has two Lean names and an
# escaped `\%`; the `\label` of an equation inside a proof is not a node; `m` is a Mathlib
# name; `off` is outside `B`; `l4` is in `B` but not in the tree.
CHAPTER_A = r"""\chapter{A}
% \begin{lemma}\label{ghost}\lean{P.ghost}\uses{l4}\end{lemma}
\begin{theorem}[Main]\label{root}
\lean{P.Root}\leanok
\end{theorem}
\begin{remark} No label here. \end{remark}
\begin{proof}
\uses{ l1 , l2 }\leanok % \uses{off}
\end{proof}

\begin{lemma}\label{l1} \lean{P.x, P.y} 50\% sure \uses{l3} \end{lemma}
\begin{definition}\label{m}\lean{Nat.succ}\end{definition}
"""

CHAPTER_B = r"""\begin{lemma}\label{l2}\lean{P.z}\uses{m, l3}
\begin{itemize}\item nested \end{itemize}
\end{lemma}
\begin{proof}\uses{l4}\begin{equation}\label{eq1} x \end{equation}\end{proof}
\begin{lemma}\label{l3}\lean{P.w}\end{lemma}
\begin{lemma}\label{l4}\lean{P.v}\end{lemma}
\begin{lemma}\label{off}\lean{P.off}\uses{l3}\end{lemma}
"""


def gnode(name, deps=(), trusted=False):
    return {"name": name, "kind": "thm", "module": "P", "trusted": trusted, "internal": False,
            "type_deps": [], "value_deps": sorted(deps), "hash_type": "0" * 16, "hash_value": None}


# P.y and P.v are not in the graph; P.Top (tree target) is outside the closure of P.Root.
GRAPH = [
    gnode("Nat.succ", trusted=True),
    gnode("P.Root", ["P.x", "P.i", "P.ghost"]),
    gnode("P.Top", ["P.Root"]),
    gnode("P.ghost"),
    gnode("P.i", ["P.w"]),
    gnode("P.off", ["P.w"]),
    gnode("P.w"),
    gnode("P.x", ["P.z", "P.w"]),
    gnode("P.z", ["P.off", "Nat.succ"]),
]
PROJECT_DECLS = ["P.Root", "P.Top", "P.ghost", "P.i", "P.off", "P.v", "P.w", "P.x", "P.y", "P.z"]
# P.i is an interior node outside U; P.ghost is in the project but labelled only in a comment.
TREE_USES = {
    "P.Top": ["P.Root"],
    "P.Root": ["P.ghost", "P.i", "P.x"],
    "P.ghost": [],
    "P.i": ["P.w"],
    "P.x": ["P.w", "P.z"],
    "P.z": ["P.off"],
    "P.off": ["P.w"],
    "P.w": [],
}


def write_tex(root: Path) -> Path:
    tex = root / "src"
    (tex / "chapter").mkdir(parents=True)
    (tex / "chapter" / "a.tex").write_text(CHAPTER_A, encoding="utf-8")
    (tex / "chapter" / "b.tex").write_text(CHAPTER_B, encoding="utf-8")
    return tex


class ParserTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bp = blueprint.parse_dir(write_tex(Path(self.tmp.name)))

    def tearDown(self):
        self.tmp.cleanup()

    def test_nodes(self):
        self.assertEqual(sorted(self.bp), ["l1", "l2", "l3", "l4", "m", "off", "root"])
        self.assertNotIn("ghost", self.bp)
        self.assertEqual(self.bp["l1"]["lean"], {"P.x", "P.y"})
        self.assertEqual(self.bp["l1"]["uses"], {"l3"})
        self.assertEqual(self.bp["m"]["lean"], {"Nat.succ"})

    def test_uses_from_following_proof(self):
        self.assertEqual(self.bp["root"]["uses"], {"l1", "l2"})  # commented `off` dropped
        self.assertEqual(self.bp["l2"]["uses"], {"m", "l3", "l4"})

    def test_closure_b(self):
        self.assertEqual(blueprint.blueprint_closure(self.bp, "root"),
                         {"root", "l1", "l2", "l3", "l4", "m"})


class CalibrationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bp = blueprint.parse_dir(write_tex(Path(self.tmp.name)))
        self.graph = {r["name"]: r for r in GRAPH}

    def tearDown(self):
        self.tmp.cleanup()

    def test_missing_in_graph(self):
        b = blueprint.blueprint_closure(self.bp, "root")
        self.assertEqual(blueprint.missing_in_graph(self.bp, b, self.graph, "P.Root"), ["P.v", "P.y"])

    def test_sets(self):
        label_map = blueprint.labels_of(self.bp)
        u_set = {n for n in label_map if n in PROJECT_DECLS}
        self.assertEqual(u_set, {"P.Root", "P.off", "P.v", "P.w", "P.x", "P.y", "P.z"})
        t = blueprint.tree_closure(TREE_USES, "P.Root")
        self.assertEqual(t, {"P.Root", "P.ghost", "P.i", "P.off", "P.w", "P.x", "P.z"})
        pt = {lab for n in t & u_set for lab in label_map[n]}
        self.assertEqual(pt, {"root", "l1", "l2", "l3", "off"})
        pe = blueprint.projected_edges(TREE_USES, t, u_set, label_map)
        # root -> l3 goes through the interior P.i; root never reaches l2 or off directly.
        self.assertEqual(pe, {("root", "l1"), ("root", "l3"), ("l1", "l2"), ("l1", "l3"),
                              ("l2", "off"), ("off", "l3")})

    def test_values(self):
        result = blueprint.calibrate(self.bp, self.graph, PROJECT_DECLS, TREE_USES, "root", "P.Root")
        # PB = {root, l1, l2, l3, l4} (m is Mathlib only);
        # BE = {(root,l1), (root,l2), (l1,l3), (l2,l3), (l2,l4)}; PE ∩ BE = {(root,l1), (l1,l3)}.
        # BR adds (root,l3) and (root,l4) (through l1 or l2); PE ∩ BR also has (root,l3);
        # (l1,l2) has no blueprint path and (l2,off), (off,l3) leave PB.
        self.assertEqual(result, {
            "format": "lazarillo-calibration/1",
            "root_label": "root",
            "root_decl": "P.Root",
            "missing_in_graph": ["P.v", "P.y"],
            "nodes": {"precision": 4 / 5, "recall": 4 / 5},
            "edges": {"precision": 3 / 6, "precision_direct": 2 / 6, "recall": 2 / 5},
        })

    def test_empty_denominators(self):
        result = blueprint.calibrate(self.bp, self.graph, PROJECT_DECLS, TREE_USES, "nope", "P.nope")
        self.assertEqual(result["missing_in_graph"], [])
        self.assertEqual(result["nodes"], {"precision": 0.0, "recall": 0.0})
        self.assertEqual(result["edges"], {"precision": 0.0, "precision_direct": 0.0, "recall": 0.0})


class CommandTest(unittest.TestCase):
    def test_writes_calibration(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            tex = write_tex(root)
            run = root / "run"
            run.mkdir()
            jsonio.write_ndjson(run / "graph.ndjson", GRAPH)
            jsonio.write_lines(run / "project_decls.txt", PROJECT_DECLS)
            jsonio.write_json(run / "tree.json", {
                "format": "lazarillo-tree/1", "target": "P.Top",
                "nodes": [{"name": n, "uses": u} for n, u in TREE_USES.items()]})
            out = root / "results" / "pfr" / "calibration.json"
            code = cli.main(["blueprint", "--tex-dir", str(tex), "--run", str(run),
                             "--root-label", "root", "--root-decl", "P.Root", "--out", str(out)])
            self.assertEqual(code, 0)
            text = out.read_text(encoding="utf-8")
            data = json.loads(text)
            self.assertEqual(text, jsonio.dumps_json(data))
            self.assertEqual(data["nodes"], {"precision": 0.8, "recall": 0.8})
            self.assertEqual(data["missing_in_graph"], ["P.v", "P.y"])


if __name__ == "__main__":
    unittest.main()
