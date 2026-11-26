import os
import shutil
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "reproduce.sh"
CORPORA = ("pfr", "zeta23", "zetalab", "poincare", "ns", "rh")
COMMANDS = ("fetch", "measure", "mutate", "blueprint", "summarize")


class ReproduceScriptTest(unittest.TestCase):
    def test_exists_and_executable(self):
        self.assertTrue(SCRIPT.is_file())
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_strict_mode_and_work_dir(self):
        text = SCRIPT.read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", text)
        self.assertIn("LAZARILLO_WORK", text)

    @unittest.skipIf(shutil.which("bash") is None, "bash not available")
    def test_syntax(self):
        proc = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_names_corpora_and_commands(self):
        text = SCRIPT.read_text(encoding="utf-8")
        for word in CORPORA + COMMANDS:
            self.assertIn(word, text)
        self.assertIn("--model", text)
        self.assertIn("--root-decl PFR_conjecture", text)


if __name__ == "__main__":
    unittest.main()
