"""corpora.toml loading and validation, work directory and toolchain paths."""

import os
import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORPORA_TOML = REPO / "corpora.toml"

STAGES = ("graph", "core", "kernels", "audit", "tree")
ALLOWED_AXIOMS = ("propext", "Quot.sound", "Classical.choice")
# Constants that Comparator requires in both exports (CONTRACT §2, RESEARCH §3.4).
KERNEL_ROOTS = ("semiOutParam", "autoParam", "String.mk", "eagerReduce", "Nat.shiftRight",
                "Nat.shiftLeft", "Nat.xor", "Nat.lor", "Nat.land", "Nat.gcd", "Nat.add", "Nat.sub",
                "Nat.mul", "Nat.div", "Nat.mod", "Nat.beq", "Nat.ble", "Nat.pow", "Nat.log2")

COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
TOOLCHAIN_RE = re.compile(r"^leanprover/lean4:v[0-9A-Za-z.\-]+$")

CORPUS_REQUIRED = ("git", "commit", "subdir", "toolchain", "license", "target",
                   "stages", "depth", "explain_depth")
CORPUS_EXCLUSIVE = ("challenge_module", "reference")


class ConfigError(ValueError):
    pass


def work_dir() -> Path:
    env = os.environ.get("LAZARILLO_WORK")
    return Path(env) if env else REPO / "work"


def toolchain_dir_name(toolchain: str) -> str:
    """`leanprover/lean4:v4.37.0-rc1` -> `leanprover--lean4---v4.37.0-rc1` (elan layout)."""
    if not TOOLCHAIN_RE.match(toolchain):
        raise ConfigError(f"invalid toolchain: {toolchain!r}")
    return toolchain.replace(":", "---").replace("/", "--")


def toolchain_dir(toolchain: str, work: Path | None = None) -> Path:
    return (work or work_dir()) / "elan" / "toolchains" / toolchain_dir_name(toolchain)


def elan_home(work: Path | None = None) -> Path:
    """`work/elan` if that elan exists; else the one in `PATH` (`$ELAN_HOME` or `~/.elan`)."""
    local = (work or work_dir()) / "elan"
    if (local / "bin" / "elan").is_file():
        return local
    env = os.environ.get("ELAN_HOME")
    return Path(env) if env else Path.home() / ".elan"


def lean_env(work: Path | None = None) -> dict:
    """Environment for every Lean process: `ELAN_HOME=work/elan` and its `bin/` first in `PATH` (CONTRACT §3)."""
    env = dict(os.environ)
    local = (work or work_dir()) / "elan"
    if (local / "bin" / "elan").is_file():
        env["ELAN_HOME"] = str(local)
        env["PATH"] = str(local / "bin") + os.pathsep + env.get("PATH", "")
    return env


def parse_depth(value):
    """`all` or a non-negative integer."""
    if value == "all":
        return "all"
    if isinstance(value, bool):
        raise ConfigError(f"invalid depth: {value!r}")
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ConfigError(f"invalid depth: {value!r}") from None
    if n < 0 or (isinstance(value, float)):
        raise ConfigError(f"invalid depth: {value!r}")
    return n


def _need(table, key, where, kind=str):
    if key not in table:
        raise ConfigError(f"{where}: missing key {key!r}")
    value = table[key]
    if not isinstance(value, kind) or isinstance(value, bool) and kind is not bool:
        raise ConfigError(f"{where}.{key}: expected {kind.__name__}")
    return value


def validate_corpus(name: str, c: dict) -> None:
    where = f"corpus.{name}"
    for key in CORPUS_REQUIRED:
        if key not in c:
            raise ConfigError(f"{where}: missing key {key!r}")
    unknown = set(c) - set(CORPUS_REQUIRED) - set(CORPUS_EXCLUSIVE)
    if unknown:
        raise ConfigError(f"{where}: unknown keys {sorted(unknown)}")
    present = [k for k in CORPUS_EXCLUSIVE if k in c]
    if len(present) != 1:
        raise ConfigError(f"{where}: needs exactly one of challenge_module or reference, got {present}")
    for key in ("git", "subdir", "license", "target", present[0]):
        _need(c, key, where)
    if not COMMIT_RE.match(_need(c, "commit", where)):
        raise ConfigError(f"{where}.commit: expected 40 lowercase hex digits")
    if not TOOLCHAIN_RE.match(_need(c, "toolchain", where)):
        raise ConfigError(f"{where}.toolchain: expected leanprover/lean4:vX")
    stages = _need(c, "stages", where, list)
    if not stages or any(s not in STAGES for s in stages) or len(set(stages)) != len(stages):
        raise ConfigError(f"{where}.stages: invalid {stages!r}")
    if [s for s in STAGES if s in stages] != stages:
        raise ConfigError(f"{where}.stages: must follow the order {', '.join(STAGES)}")
    parse_depth(c["depth"])
    if parse_depth(c["explain_depth"]) == "all":
        raise ConfigError(f"{where}.explain_depth: expected an integer")


def validate(cfg: dict) -> None:
    ver = cfg.get("verification")
    if not isinstance(ver, dict):
        raise ConfigError("missing [verification]")
    if not TOOLCHAIN_RE.match(_need(ver, "toolchain", "verification")):
        raise ConfigError("verification.toolchain: expected leanprover/lean4:vX")

    elan = cfg.get("elan")
    if not isinstance(elan, dict):
        raise ConfigError("missing [elan]")
    _need(elan, "installer", "elan")
    if not SHA256_RE.match(_need(elan, "sha256", "elan")):
        raise ConfigError("elan.sha256: expected 64 hex digits")

    l4e = cfg.get("lean4export")
    if not isinstance(l4e, dict):
        raise ConfigError("missing [lean4export]")
    _need(l4e, "git", "lean4export")
    for tag, commit in l4e.items():
        if tag == "git":
            continue
        if not re.match(r"^v[0-9A-Za-z.\-]+$", tag):
            raise ConfigError(f"lean4export: invalid tag {tag!r}")
        if not isinstance(commit, str) or not COMMIT_RE.match(commit):
            raise ConfigError(f"lean4export.{tag}: expected 40 hex digits")

    model = cfg.get("model")
    if not isinstance(model, dict):
        raise ConfigError("missing [model]")
    for key in ("repo", "file"):
        _need(model, key, "model")
    if not COMMIT_RE.match(_need(model, "revision", "model")):
        raise ConfigError("model.revision: expected 40 hex digits")
    if not SHA256_RE.match(_need(model, "sha256", "model")):
        raise ConfigError("model.sha256: expected 64 hex digits")
    if _need(model, "size", "model", int) <= 0:
        raise ConfigError("model.size: expected a positive integer")

    corpora = cfg.get("corpus")
    if not isinstance(corpora, dict) or not corpora:
        raise ConfigError("missing [corpus.*]")
    for name, c in corpora.items():
        if not isinstance(c, dict):
            raise ConfigError(f"corpus.{name}: expected a table")
        validate_corpus(name, c)


def load_corpora(path=None) -> dict:
    with open(path or CORPORA_TOML, "rb") as f:
        cfg = tomllib.load(f)
    validate(cfg)
    return cfg
