"""`fetch`: elan, toolchains, corpora, exporter, judge and model (CONTRACT §3, §4).

The only module that uses the network. Every step checks first whether it is
already done and skips it, so `fetch` can be re-run after a failure.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import jsonio
from .config import ConfigError, load_corpora, toolchain_dir, work_dir

HF_URL = "https://huggingface.co/{repo}/resolve/{revision}/{file}"
LEAN_COMMIT_RE = re.compile(r"\bcommit ([0-9a-f]{40})\b")
CHUNK = 1 << 20

JUDGE_LAKEFILE = """name = "judge"
defaultTargets = ["Judge"]

[[lean_lib]]
name = "Judge"
"""


class FetchError(Exception):
    pass


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK):
            h.update(chunk)
    return h.hexdigest()


def http_download(url: str, dest: Path) -> None:
    with urllib.request.urlopen(url, timeout=60) as response, open(dest, "wb") as f:
        shutil.copyfileobj(response, f, CHUNK)


def run_logged(cmd: list[str], cwd: str, env: dict, log: Path) -> str:
    """Run `cmd`, append its combined output to `log` and return it; raise on failure."""
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"$ {shlex.join(cmd)}  (cwd {cwd})\n")
        f.flush()
        try:
            proc = subprocess.run(cmd, cwd=cwd, env=env, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, text=True, errors="replace")
        except OSError as e:
            f.write(f"[cannot run: {e}]\n")
            raise FetchError(f"cannot run {cmd[0]}: {e}") from None
        f.write(proc.stdout)
        f.write(f"[exit {proc.returncode}]\n")
    if proc.returncode != 0:
        raise FetchError(f"`{shlex.join(cmd)}` failed with exit code {proc.returncode} (see {log})")
    return proc.stdout


def depends_on_mathlib(project: Path) -> bool:
    manifest = project / "lake-manifest.json"
    if not manifest.is_file():
        return False
    with open(manifest, encoding="utf-8") as f:
        data = json.load(f)
    return any(p.get("name") == "mathlib" for p in data.get("packages", []))


class Fetcher:
    def __init__(self, cfg: dict, work: Path, run=run_logged, download=http_download):
        self.cfg = cfg
        self.work = Path(work).resolve()
        self.elan_home = self.work / "elan"
        self._run = run
        self._download = download
        env = dict(os.environ)
        env["ELAN_HOME"] = str(self.elan_home)
        env["PATH"] = str(self.elan_home / "bin") + os.pathsep + env.get("PATH", "")
        self.env = env
        self.log = None

    def run(self, cmd, cwd=None) -> str:
        return self._run([str(c) for c in cmd], str(cwd or self.work), self.env, self.log)

    def _note(self, text: str) -> None:
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(text + "\n")

    def download_verified(self, url: str, dest: Path, sha256: str, size: int | None = None) -> None:
        """Download to `<dest>.part`, check size and sha256, then rename to `dest`."""
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        part.unlink(missing_ok=True)
        self._note(f"# download {url} -> {dest}")
        try:
            self._download(url, part)
        except OSError as e:
            part.unlink(missing_ok=True)
            raise FetchError(f"download failed: {url}: {e}") from None
        if size is not None and part.stat().st_size != size:
            got = part.stat().st_size
            part.unlink()
            raise FetchError(f"size mismatch for {url}: expected {size}, got {got}")
        got = sha256_file(part)
        if got != sha256:
            part.unlink()
            raise FetchError(f"sha256 mismatch for {url}: expected {sha256}, got {got}")
        os.replace(part, dest)

    # 1. elan
    def install_elan(self) -> None:
        elan = self.elan_home / "bin" / "elan"
        if elan.is_file():
            return
        script = self.work / "downloads" / "elan-init.sh"
        self.download_verified(self.cfg["elan"]["installer"], script, self.cfg["elan"]["sha256"])
        self.run(["sh", script, "-y", "--no-modify-path", "--default-toolchain", "none"])
        if not elan.is_file():
            raise FetchError(f"elan installer finished but {elan} is missing")

    # 2. toolchains
    def install_toolchain(self, toolchain: str) -> None:
        lean = toolchain_dir(toolchain, self.work) / "bin" / "lean"
        if lean.is_file():
            return
        self.run(["elan", "toolchain", "install", toolchain])
        if not lean.is_file():
            raise FetchError(f"elan installed {toolchain} but {lean} is missing")

    def checkout(self, url: str, commit: str, dest: Path) -> None:
        if not (dest / ".git").exists():
            if dest.exists():
                raise FetchError(f"{dest} exists but is not a git clone")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".tmp")
            if tmp.exists():
                shutil.rmtree(tmp)
            self.run(["git", "clone", url, tmp])
            tmp.rename(dest)
        if self.run(["git", "rev-parse", "HEAD"], dest).strip() != commit:
            self.run(["git", "checkout", "--detach", commit], dest)

    # 3. corpus clone and build
    def clone_and_build(self, name: str, c: dict) -> Path:
        repo = self.work / "corpora" / name
        self.checkout(c["git"], c["commit"], repo)
        project = repo / c["subdir"]
        if not project.is_dir():
            raise FetchError(f"subdir {c['subdir']!r} not found in {repo}")
        stamp = self.work / "corpora" / f"{name}.built"
        if stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == c["commit"]:
            return project
        stamp.unlink(missing_ok=True)
        if depends_on_mathlib(project):
            self.run(["lake", "exe", "cache", "get"], project)
        self.run(["lake", "build"], project)
        if "challenge_module" in c:
            self.run(["lake", "build", c["challenge_module"]], project)
        stamp.write_text(c["commit"] + "\n", encoding="utf-8")
        return project

    # 4. exporter
    def exporter(self, toolchain: str) -> list[str]:
        leanexport = toolchain_dir(toolchain, self.work) / "bin" / "leanexport"
        if leanexport.is_file():
            return ["lake", "env", str(leanexport)]
        version = toolchain.split(":", 1)[1]
        commit = self.cfg["lean4export"].get(version)
        if version == "git" or commit is None:
            raise FetchError(f"{toolchain} has no bin/leanexport and [lean4export] has no commit for {version}")
        tool = self.work / "tools" / f"lean4export-{version}"
        binary = tool / ".lake" / "build" / "bin" / "lean4export"
        if not binary.is_file():
            self.checkout(self.cfg["lean4export"]["git"], commit, tool)
            self.run(["lake", "build"], tool)
            if not binary.is_file():
                raise FetchError(f"lake build of lean4export {version} did not produce {binary}")
        return ["lake", "env", str(binary)]

    # 5. judge
    def build_judge(self) -> None:
        judge = self.work / "judge"
        files = {"lean-toolchain": self.cfg["verification"]["toolchain"] + "\n",
                 "lakefile.toml": JUDGE_LAKEFILE,
                 "Judge.lean": ""}
        manifest = judge / "lake-manifest.json"
        current = all((judge / n).is_file() and (judge / n).read_text(encoding="utf-8") == t
                      for n, t in files.items())
        if current and manifest.is_file():
            return
        judge.mkdir(parents=True, exist_ok=True)
        for n, t in files.items():
            (judge / n).write_text(t, encoding="utf-8")
        self.run(["lake", "build"], judge)
        if not manifest.is_file():
            raise FetchError(f"lake build in {judge} did not create lake-manifest.json")

    # 6. model
    def fetch_model(self) -> Path:
        m = self.cfg["model"]
        dest = self.work / "models" / m["file"]
        if dest.is_file() and dest.stat().st_size == m["size"] and sha256_file(dest) == m["sha256"]:
            return dest
        url = HF_URL.format(repo=m["repo"], revision=m["revision"], file=m["file"])
        self.download_verified(url, dest, m["sha256"], m["size"])
        return dest

    def lean_commit(self, project: Path) -> str:
        out = self.run(["lean", "--version"], project)
        match = LEAN_COMMIT_RE.search(out)
        if not match:
            raise FetchError(f"cannot read the Lean commit from `lean --version`: {out.strip()!r}")
        return match.group(1)

    # 7. fetch.json
    def fetch_corpus(self, name: str, model: bool) -> dict:
        c = self.cfg["corpus"][name]
        corpora = self.work / "corpora"
        corpora.mkdir(parents=True, exist_ok=True)
        self.log = corpora / f"{name}.fetch.log"
        self.install_elan()
        self.install_toolchain(self.cfg["verification"]["toolchain"])
        self.install_toolchain(c["toolchain"])
        project = self.clone_and_build(name, c)
        exporter = self.exporter(c["toolchain"])
        self.build_judge()
        if model:
            self.fetch_model()
        record = {"project_dir": str(project), "toolchain": c["toolchain"],
                  "lean_commit": self.lean_commit(project), "exporter": exporter}
        jsonio.write_json(corpora / f"{name}.fetch.json", record)
        return record


def main(names, model: bool, cfg=None, work=None, run=run_logged, download=http_download) -> int:
    cfg = cfg if cfg is not None else load_corpora()
    unknown = [n for n in names if n not in cfg["corpus"]]
    if unknown:
        raise ConfigError(f"unknown corpus: {', '.join(unknown)}")
    fetcher = Fetcher(cfg, work if work is not None else work_dir(), run, download)
    status = 0
    for name in dict.fromkeys(names):
        try:
            fetcher.fetch_corpus(name, model)
        except FetchError as e:
            print(f"lazarillo: fetch {name}: {e}", file=sys.stderr)
            status = 1
        else:
            print(f"lazarillo: fetch {name}: ok")
    return status
