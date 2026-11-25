import copy
import re
import sys
import tomllib
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import config  # noqa: E402

CORPORA = ("pfr", "zeta23", "zetalab", "poincare", "ns", "rh")
KEYS = {"git", "commit", "subdir", "toolchain", "license", "target", "stages", "depth", "explain_depth"}


class CorporaTomlTest(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load_corpora(REPO / "corpora.toml")

    def test_identical_to_contract_block(self):
        contract = (REPO / "vault" / "CONTRACT.md").read_text(encoding="utf-8")
        m = re.search(r"^```toml\n(.*?)^```$", contract, re.S | re.M)
        self.assertIsNotNone(m)
        self.assertEqual((REPO / "corpora.toml").read_text(encoding="utf-8"), m.group(1))

    def test_six_corpora_with_all_keys(self):
        self.assertEqual(set(self.cfg["corpus"]), set(CORPORA))
        for name, c in self.cfg["corpus"].items():
            with self.subTest(corpus=name):
                self.assertLessEqual(KEYS, set(c))
                self.assertEqual(sum(k in c for k in ("challenge_module", "reference")), 1)

    def test_commits_and_toolchains(self):
        tc = re.compile(r"^leanprover/lean4:v\S+$")
        self.assertRegex(self.cfg["verification"]["toolchain"], tc)
        for name, c in self.cfg["corpus"].items():
            with self.subTest(corpus=name):
                self.assertRegex(c["commit"], r"^[0-9a-f]{40}$")
                self.assertRegex(c["toolchain"], tc)
        for tag, commit in self.cfg["lean4export"].items():
            if tag != "git":
                self.assertRegex(commit, r"^[0-9a-f]{40}$")
        self.assertRegex(self.cfg["model"]["revision"], r"^[0-9a-f]{40}$")

    def test_xor_rule(self):
        both = copy.deepcopy(self.cfg)
        both["corpus"]["pfr"]["reference"] = "x/Reference.lean"
        with self.assertRaises(config.ConfigError):
            config.validate(both)
        neither = copy.deepcopy(self.cfg)
        del neither["corpus"]["pfr"]["challenge_module"]
        with self.assertRaises(config.ConfigError):
            config.validate(neither)

    def test_bad_commit_rejected(self):
        bad = copy.deepcopy(self.cfg)
        bad["corpus"]["rh"]["commit"] = "4a5b4a2"
        with self.assertRaises(config.ConfigError):
            config.validate(bad)

    def test_toml_parses_standalone(self):
        with open(REPO / "corpora.toml", "rb") as f:
            self.assertIn("corpus", tomllib.load(f))


class PathsTest(unittest.TestCase):
    def test_toolchain_dir(self):
        work = Path("/w")
        self.assertEqual(
            config.toolchain_dir("leanprover/lean4:v4.37.0-rc1", work),
            Path("/w/elan/toolchains/leanprover--lean4---v4.37.0-rc1"),
        )

    def test_work_dir_env(self):
        import os
        old = os.environ.get("LAZARILLO_WORK")
        try:
            os.environ["LAZARILLO_WORK"] = "/tmp/lzw"
            self.assertEqual(config.work_dir(), Path("/tmp/lzw"))
            del os.environ["LAZARILLO_WORK"]
            self.assertEqual(config.work_dir(), REPO / "work")
        finally:
            if old is not None:
                os.environ["LAZARILLO_WORK"] = old


if __name__ == "__main__":
    unittest.main()
