import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import config, fetch  # noqa: E402

LEAN_COMMIT = "0b77e12952ad39077d80d8bd6b66d601f225c321"
ELAN_SCRIPT = b"#!/bin/sh\necho fake elan installer\n"
MODEL_BYTES = b"fake gguf weights"
MATHLIB_MANIFEST = json.dumps({"version": "1.1.0", "packages": [{"name": "mathlib"}]})
PLAIN_MANIFEST = json.dumps({"version": "1.1.0", "packages": []})


class FakeRunner:
    """Records commands and mimics their effect on disk; never touches the network."""

    def __init__(self, work: Path, cfg: dict, fail=None):
        self.work = work
        self.cfg = cfg
        self.fail = fail
        self.calls = []

    def __call__(self, cmd, cwd, env, log):
        self.calls.append((tuple(cmd), cwd))
        assert env["ELAN_HOME"] == str(self.work / "elan")
        assert env["PATH"].split(os.pathsep)[0] == str(self.work / "elan" / "bin")
        with open(log, "a", encoding="utf-8") as f:
            f.write(" ".join(cmd) + "\n")
        if self.fail is not None and tuple(cmd) == self.fail:
            raise fetch.FetchError(f"{' '.join(cmd)} failed")
        cwd = Path(cwd)
        if cmd[0] == "sh":
            _touch(self.work / "elan" / "bin" / "elan")
        elif cmd[:3] == ["elan", "toolchain", "install"]:
            bindir = config.toolchain_dir(cmd[3], self.work) / "bin"
            _touch(bindir / "lean")
            if cmd[3] == "leanprover/lean4:v4.37.0-rc1":
                _touch(bindir / "leanexport")
        elif cmd[:2] == ["git", "clone"]:
            dest = Path(cmd[3])
            (dest / ".git").mkdir(parents=True)
            (dest / ".git" / "fake-head").write_text("0" * 40)
            for name, c in self.cfg["corpus"].items():
                if c["git"] == cmd[2]:
                    manifest = MATHLIB_MANIFEST if name == "pfr" else PLAIN_MANIFEST
                    project = dest / c["subdir"]
                    project.mkdir(parents=True, exist_ok=True)
                    (project / "lake-manifest.json").write_text(manifest)
        elif cmd[:2] == ["git", "rev-parse"]:
            return (cwd / ".git" / "fake-head").read_text() + "\n"
        elif cmd[:3] == ["git", "checkout", "--detach"]:
            (cwd / ".git" / "fake-head").write_text(cmd[3])
        elif cmd == ["lake", "build"] and cwd == self.work / "judge":
            (cwd / "lake-manifest.json").write_text(PLAIN_MANIFEST)
        elif cmd == ["lake", "build"] and cwd.parent == self.work / "tools":
            _touch(cwd / ".lake" / "build" / "bin" / "lean4export")
        elif cmd == ["lean", "--version"]:
            return f"Lean (version 4.x, x86_64-unknown-linux-gnu, commit {LEAN_COMMIT}, Release)\n"
        return ""

    def commands(self):
        return [cmd for cmd, _ in self.calls]


class FakeDownload:
    def __init__(self, blobs: dict):
        self.blobs = blobs
        self.urls = []

    def __call__(self, url, dest):
        self.urls.append(url)
        Path(dest).write_bytes(self.blobs[url])


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FetchTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.work = Path(tmp.name).resolve()
        cfg = copy.deepcopy(config.load_corpora(REPO / "corpora.toml"))
        cfg["elan"]["sha256"] = _sha(ELAN_SCRIPT)
        cfg["model"]["sha256"] = _sha(MODEL_BYTES)
        cfg["model"]["size"] = len(MODEL_BYTES)
        self.cfg = cfg
        m = cfg["model"]
        self.model_url = f"https://huggingface.co/{m['repo']}/resolve/{m['revision']}/{m['file']}"
        self.download = FakeDownload({cfg["elan"]["installer"]: ELAN_SCRIPT, self.model_url: MODEL_BYTES})

    def fetch(self, names, model=False, runner=None):
        runner = runner or FakeRunner(self.work, self.cfg)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = fetch.main(names, model, cfg=self.cfg, work=self.work, run=runner, download=self.download)
        return code, runner

    def record(self, name):
        with open(self.work / "corpora" / f"{name}.fetch.json", encoding="utf-8") as f:
            return json.load(f)

    def test_sequence_with_leanexport(self):
        code, runner = self.fetch(["pfr"])
        self.assertEqual(code, 0)
        repo = self.work / "corpora" / "pfr"
        judge = self.work / "judge"
        w = str(self.work)
        self.assertEqual(runner.calls, [
            (("sh", str(self.work / "downloads" / "elan-init.sh"), "-y", "--no-modify-path",
              "--default-toolchain", "none"), w),
            (("elan", "toolchain", "install", "leanprover/lean4:v4.37.0-rc1"), w),
            (("git", "clone", "https://github.com/teorth/pfr", str(self.work / "corpora" / "pfr.tmp")), w),
            (("git", "rev-parse", "HEAD"), str(repo)),
            (("git", "checkout", "--detach", "1899ce8ed95fc310cce53d4c7ecfa2beb20ebec4"), str(repo)),
            (("lake", "exe", "cache", "get"), str(repo)),
            (("lake", "build"), str(repo)),
            (("lake", "build", "PFRPalomar.Challenge"), str(repo)),
            (("lake", "build"), str(judge)),
            (("lean", "--version"), str(repo)),
        ])
        leanexport = config.toolchain_dir("leanprover/lean4:v4.37.0-rc1", self.work) / "bin" / "leanexport"
        self.assertEqual(self.record("pfr"), {
            "project_dir": str(repo),
            "toolchain": "leanprover/lean4:v4.37.0-rc1",
            "lean_commit": LEAN_COMMIT,
            "exporter": ["lake", "env", str(leanexport)],
        })
        self.assertEqual((judge / "lean-toolchain").read_text(), "leanprover/lean4:v4.37.0-rc1\n")
        self.assertIn('name = "judge"', (judge / "lakefile.toml").read_text())
        self.assertIn('defaultTargets = ["Judge"]', (judge / "lakefile.toml").read_text())
        self.assertEqual((judge / "Judge.lean").read_text(), "")
        self.assertTrue((self.work / "corpora" / "pfr.fetch.log").is_file())
        self.assertEqual(self.download.urls, [self.cfg["elan"]["installer"]])

    def test_sequence_without_leanexport(self):
        code, runner = self.fetch(["zeta23"])
        self.assertEqual(code, 0)
        project = self.work / "corpora" / "zeta23" / "zeta23"
        tool = self.work / "tools" / "lean4export-v4.33.0-rc2"
        self.assertEqual(runner.commands(), [
            ("sh", str(self.work / "downloads" / "elan-init.sh"), "-y", "--no-modify-path",
             "--default-toolchain", "none"),
            ("elan", "toolchain", "install", "leanprover/lean4:v4.37.0-rc1"),
            ("elan", "toolchain", "install", "leanprover/lean4:v4.33.0-rc2"),
            ("git", "clone", "https://github.com/anthropics/formal-math",
             str(self.work / "corpora" / "zeta23.tmp")),
            ("git", "rev-parse", "HEAD"),
            ("git", "checkout", "--detach", "11b6c7e3c927df2658f513b6b68ea7f8929c62c5"),
            ("lake", "build"),
            ("lake", "build", "Challenge"),
            ("git", "clone", "https://github.com/leanprover/lean4export",
             str(self.work / "tools" / "lean4export-v4.33.0-rc2.tmp")),
            ("git", "rev-parse", "HEAD"),
            ("git", "checkout", "--detach", "9fb131bb100eb32ccf6836f14e4f8328d13b6792"),
            ("lake", "build"),
            ("lake", "build"),
            ("lean", "--version"),
        ])
        cwds = [cwd for _, cwd in runner.calls]
        self.assertEqual(cwds[6], str(project))
        self.assertEqual(cwds[11], str(tool))
        self.assertEqual(cwds[12], str(self.work / "judge"))
        self.assertEqual(cwds[13], str(project))
        record = self.record("zeta23")
        self.assertEqual(record["project_dir"], str(project))
        self.assertEqual(record["exporter"],
                         ["lake", "env", str(tool / ".lake" / "build" / "bin" / "lean4export")])

    def test_idempotent(self):
        code, _ = self.fetch(["pfr", "zeta23"], model=True)
        self.assertEqual(code, 0)
        code, runner = self.fetch(["pfr", "zeta23"], model=True)
        self.assertEqual(code, 0)
        self.assertEqual(runner.commands(), [
            ("git", "rev-parse", "HEAD"), ("lean", "--version"),
            ("git", "rev-parse", "HEAD"), ("lean", "--version"),
        ])
        self.assertEqual(self.download.urls, [self.cfg["elan"]["installer"], self.model_url])
        self.assertEqual((self.work / "models" / self.cfg["model"]["file"]).read_bytes(), MODEL_BYTES)

    def test_second_corpus_reuses_shared_steps(self):
        self.fetch(["pfr"])
        code, runner = self.fetch(["zeta23"])
        self.assertEqual(code, 0)
        cmds = runner.commands()
        self.assertNotIn("sh", [c[0] for c in cmds])
        self.assertNotIn(("elan", "toolchain", "install", "leanprover/lean4:v4.37.0-rc1"), cmds)
        self.assertNotIn(str(self.work / "judge"), [cwd for _, cwd in runner.calls])

    def test_bad_elan_sha256_aborts(self):
        self.cfg["elan"]["sha256"] = "0" * 64
        code, runner = self.fetch(["pfr"])
        self.assertEqual(code, 1)
        self.assertEqual(runner.calls, [])
        self.assertFalse((self.work / "downloads" / "elan-init.sh").exists())
        self.assertFalse((self.work / "downloads" / "elan-init.sh.part").exists())
        self.assertFalse((self.work / "corpora" / "pfr.fetch.json").exists())

    def test_bad_model_sha256_aborts(self):
        self.cfg["model"]["sha256"] = "0" * 64
        code, runner = self.fetch(["pfr"], model=True)
        self.assertEqual(code, 1)
        models = self.work / "models"
        self.assertFalse((models / self.cfg["model"]["file"]).exists())
        self.assertFalse((models / (self.cfg["model"]["file"] + ".part")).exists())
        self.assertNotIn(("lean", "--version"), runner.commands())
        self.assertFalse((self.work / "corpora" / "pfr.fetch.json").exists())

    def test_failing_step_stops_corpus(self):
        runner = FakeRunner(self.work, self.cfg, fail=("lake", "build", "PFRPalomar.Challenge"))
        code, runner = self.fetch(["pfr"], runner=runner)
        self.assertEqual(code, 1)
        self.assertEqual(runner.commands()[-1], ("lake", "build", "PFRPalomar.Challenge"))
        self.assertFalse((self.work / "corpora" / "pfr.built").exists())
        self.assertFalse((self.work / "corpora" / "pfr.fetch.json").exists())

    def test_unknown_corpus(self):
        with self.assertRaises(config.ConfigError):
            fetch.main(["nope"], False, cfg=self.cfg, work=self.work,
                       run=FakeRunner(self.work, self.cfg), download=self.download)


if __name__ == "__main__":
    unittest.main()
