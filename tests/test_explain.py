import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import explain  # noqa: E402

# The fake binary records its argv in ARGS_LOG and answers with a fixed text that opens
# with a reasoning block, as a misbehaving model would.
FAKE_LLAMA = """#!/usr/bin/env python3
import json, os, sys
if "--version" in sys.argv:
    print("1.0.0-dev (build 12359, commit b1b770d90d)")
    print("built with fake")
    sys.exit(0)
with open(os.environ["FAKE_LLAMA_ARGS"], "a", encoding="utf-8") as f:
    f.write(json.dumps(sys.argv[1:]) + "\\n")
print("<think>\\nscratch\\n</think>\\n\\nThe lemma states that n + 0 = n. [end of text]")
"""

MODEL_BYTES = b"not really a gguf"


def tnode(name, depth, parent=None, children=(), goals=(), statement=None, uses=()):
    return {"name": name, "kind": "thm", "module": "P.A", "file": "P/A.lean", "range": [1, 2],
            "depth": depth, "parent": parent, "children": list(children), "uses": list(uses),
            "statement": statement, "tactic_proof": bool(goals), "goals": list(goals),
            "explanation": None}


def goal(i):
    return {"tactic": f"tac{i}", "range": [i, i], "before": [f"⊢ goal {i}"]}


class PromptTest(unittest.TestCase):
    def test_qwen3_template_without_reasoning(self):
        p = explain.build_prompt(tnode("P.T", 0, statement="True"), [])
        self.assertTrue(p.startswith("<|im_start|>system\n"))
        self.assertIn("<|im_end|>\n<|im_start|>user\n", p)
        self.assertTrue(p.endswith("<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"))
        self.assertEqual(p.count("<|im_start|>"), 3)
        self.assertIn("Declaration: P.T", p)
        self.assertIn("True", p)
        self.assertIn("150 words", p)
        self.assertIn("English", p)

    def test_three_goals_first_middle_last(self):
        goals = [goal(i) for i in range(7)]
        self.assertEqual(explain.pick_goals(goals), [goals[0], goals[3], goals[6]])
        self.assertEqual(explain.pick_goals(goals[:2]), goals[:2])
        msg = explain.user_message(tnode("P.T", 0, goals=goals), [])
        for i in (0, 3, 6):
            self.assertIn(f"goal {i}", msg)
            self.assertIn(f"`tac{i}`", msg)
        for i in (1, 2, 4, 5):
            self.assertNotIn(f"goal {i}", msg)
        self.assertIn("(3 of 7)", msg)

    def test_ten_children(self):
        kids = [tnode(f"P.c{i:02d}", 1, statement=f"type {i:02d}") for i in range(12)]
        msg = explain.user_message(tnode("P.T", 0), kids)
        for i in range(10):
            self.assertIn(f"- P.c{i:02d} : type {i:02d}", msg)
        self.assertNotIn("P.c10", msg)
        self.assertNotIn("P.c11", msg)
        self.assertIn("(10 of 12)", msg)

    def test_clean(self):
        self.assertEqual(explain.clean("<think>\nx\n</think>\n\nAnswer."), "Answer.")
        self.assertEqual(explain.clean("Answer.\n<think>never closed"), "Answer.")
        self.assertEqual(explain.clean("  Answer. [end of text]\n"), "Answer.")
        self.assertEqual(explain.clean("Plain."), "Plain.")

    def test_exact_invocation(self):
        cmd = explain.llama_command("/bin/llama", Path("/m.gguf"), Path("/p.txt"), 8)
        self.assertEqual(cmd, ["/bin/llama", "-m", "/m.gguf", "-f", "/p.txt", "-n", "400", "-c", "8192",
                               "-t", "8", "--temp", "0.7", "--top-p", "0.8", "--top-k", "20",
                               "--min-p", "0", "--seed", "0", "-no-cnv", "--no-display-prompt",
                               "--offline", "--simple-io"])


class ExplainTreeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.work, self.out = root / "work", root / "out"
        (self.work / "models").mkdir(parents=True)
        self.out.mkdir()
        (self.work / "models" / "M.gguf").write_bytes(MODEL_BYTES)
        self.model_cfg = {"file": "M.gguf", "sha256": hashlib.sha256(MODEL_BYTES).hexdigest()}
        self.llama = root / "bin" / "llama-completion"
        self.llama.parent.mkdir()
        self.llama.write_text(FAKE_LLAMA, encoding="utf-8")
        self.llama.chmod(0o755)
        self.args_log = root / "args.ndjson"
        env = {"LAZARILLO_LLAMA": str(self.llama), "FAKE_LLAMA_ARGS": str(self.args_log),
               "PATH": os.environ.get("PATH", "")}
        self.env = mock.patch.dict(os.environ, env, clear=True)
        self.env.start()
        self.nodes = [
            tnode("P.T", 0, children=["P.a", "P.b"], goals=[goal(0)], statement="T", uses=["P.a", "P.b"]),
            tnode("P.a", 1, "P.T", children=["P.d"], statement="A", uses=["P.d"]),
            tnode("P.b", 1, "P.T", statement="B"),
            tnode("P.d", 2, "P.a", statement="D"),
        ]

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def explain(self, depth=1):
        return explain.explain_tree(self.nodes, depth, self.out, model_cfg=self.model_cfg, work=self.work)

    def test_fake_llama(self):
        llm = self.explain()
        self.assertEqual(llm["binary"], str(self.llama))
        self.assertEqual(llm["version"], "1.0.0-dev (build 12359, commit b1b770d90d)")
        self.assertEqual(llm["model"], "M.gguf")
        self.assertEqual(llm["model_sha256"], self.model_cfg["sha256"])
        self.assertEqual(llm["params"]["ctx_size"], 8192)
        self.assertEqual(llm["params"]["temp"], 0.7)
        for n in self.nodes[:3]:
            self.assertEqual(n["explanation"], "The lemma states that n + 0 = n.")
        self.assertIsNone(self.nodes[3]["explanation"])
        # One call per explained node, in BFS order, with the logged prompt.
        calls = [json.loads(line) for line in self.args_log.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(calls), 3)
        for i, argv in enumerate(calls):
            prompt = self.out / "logs" / "prompts" / f"{i}.txt"
            self.assertEqual(argv[argv.index("-f") + 1], str(prompt))
            self.assertEqual(argv[argv.index("-m") + 1], str(self.work / "models" / "M.gguf"))
            self.assertIn(f"Declaration: {self.nodes[i]['name']}", prompt.read_text(encoding="utf-8"))
            raw = (self.out / "logs" / "llm" / f"{i}.txt").read_text(encoding="utf-8")
            self.assertIn("<think>", raw)
        self.assertFalse((self.out / "logs" / "prompts" / "3.txt").exists())
        self.assertIn("- P.d : D", (self.out / "logs" / "prompts" / "1.txt").read_text(encoding="utf-8"))

    def test_explain_depth_zero(self):
        self.explain(0)
        self.assertIsNotNone(self.nodes[0]["explanation"])
        self.assertTrue(all(n["explanation"] is None for n in self.nodes[1:]))

    def test_sha256_mismatch_fails(self):
        self.model_cfg["sha256"] = "0" * 64
        with self.assertRaises(explain.ExplainError):
            self.explain()
        self.assertFalse(self.args_log.exists())
        self.assertTrue(all(n["explanation"] is None for n in self.nodes))

    def test_missing_model_fails(self):
        (self.work / "models" / "M.gguf").unlink()
        with self.assertRaises(explain.ExplainError):
            self.explain()

    def test_missing_binary_names_package(self):
        del os.environ["LAZARILLO_LLAMA"]
        os.environ["PATH"] = str(Path(self.tmp.name) / "empty")
        with self.assertRaises(explain.ExplainError) as cm:
            self.explain()
        self.assertIn("llama-cpp", str(cm.exception))

    def test_binary_from_path(self):
        del os.environ["LAZARILLO_LLAMA"]
        os.environ["PATH"] = str(self.llama.parent) + os.pathsep + os.environ["PATH"]
        self.assertEqual(self.explain()["binary"], str(self.llama))

    def test_failing_binary(self):
        self.llama.write_text("#!/bin/sh\n[ \"$1\" = --version ] && echo v && exit 0\nexit 3\n",
                              encoding="utf-8")
        with self.assertRaises(explain.ExplainError):
            self.explain()


class HtmlTest(unittest.TestCase):
    def data(self):
        nodes = [
            tnode("P.T", 0, children=["P.a", "P.b"], uses=["P.a", "P.b"],
                  statement='∀ x, x < 1 & "q" \'s\'', goals=[goal(0)]),
            tnode("P.a", 1, "P.T", children=["P.d"], uses=["P.d", "P.b"], statement="A"),
            tnode("P.b", 1, "P.T", statement="B"),
            tnode("P.d", 2, "P.a", statement="D"),
        ]
        nodes[0]["explanation"] = 'Uses <script>alert("x")</script> & more.'
        return {"target": "P.T<&>", "nodes": nodes}

    def test_escaping_and_no_script(self):
        page = explain.tree_html(self.data())
        self.assertNotIn("<script", page.lower())
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt; &amp; more.", page)
        self.assertIn("x &lt; 1 &amp; &quot;q&quot; &#x27;s&#x27;", page)
        self.assertIn("P.T&lt;&amp;&gt;", page)
        self.assertNotIn("src=", page)
        self.assertNotIn("<link", page)
        self.assertNotIn("http", page)

    def test_nesting_anchors_and_links(self):
        page = explain.tree_html(self.data())
        for i in range(4):
            self.assertEqual(page.count(f'id="n-{i}"'), 1)
        self.assertIn('<a href="#n-1"><code>P.a</code></a>', page)
        self.assertIn('<a href="#n-2"><code>P.b</code></a>', page)
        self.assertIn('<a href="#n-3"><code>P.d</code></a>', page)
        # P.d nested in P.a, nested in P.T; P.b after P.a closes.
        pos = [page.index(f'id="n-{i}"') for i in range(4)]
        self.assertLess(pos[0], pos[1])
        self.assertLess(pos[1], pos[3])
        self.assertLess(pos[3], pos[2])
        between = page[pos[3]:pos[2]]
        self.assertEqual(between.count("</div></details>"), 2)  # closes P.d and P.a
        self.assertEqual(page.count("<details"), page.count("</details>"))


if __name__ == "__main__":
    unittest.main()
