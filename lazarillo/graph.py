"""Stage `graph`: declarations from `.olean` files, closure of the target (CONTRACT §2, §3, §5).

`lean/Extract.lean` runs in batches of at most 1,000 modules or 2 GiB of
`.olean`, one Lean process at a time. The batches are combined with names
interned as integers and adjacency lists in `array('I')` (CSR layout).
"""

import json
import subprocess
import sys
from array import array
from dataclasses import dataclass
from pathlib import Path

from . import jsonio
from .config import REPO, ConfigError, elan_home, lean_env, toolchain_dir_name

EXTRACT_LEAN = REPO / "lean" / "Extract.lean"
MAX_BATCH_MODULES = 1000
MAX_BATCH_BYTES = 2 << 30
OLEAN_PARTS = ("", ".server", ".private")

KINDS = ("axiom", "def", "thm", "opaque", "quot", "inductive", "ctor", "rec")
_KIND_CODE = {k: i for i, k in enumerate(KINDS)}
NO_DECL = 0xFFFFFFFF
_INTERNAL, _TRUSTED, _HAS_VALUE = 1, 2, 4


class GraphError(Exception):
    pass


@dataclass(frozen=True)
class Olean:
    module: str
    path: Path
    size: int  # bytes of the `.olean` plus its `.server`/`.private` parts
    trusted: bool


def trusted_packages(project: Path) -> set[str]:
    """`mathlib` and every package listed in `.lake/packages/mathlib/lake-manifest.json` (CONTRACT §2)."""
    names = {"mathlib"}
    manifest = Path(project) / ".lake" / "packages" / "mathlib" / "lake-manifest.json"
    if manifest.is_file():
        with open(manifest, encoding="utf-8") as f:
            data = json.load(f)
        names.update(p["name"] for p in data.get("packages", []))
    return names


def toolchain_lib(project: Path) -> Path:
    """`lib/lean` of the toolchain named by `PROJECT_DIR/lean-toolchain`."""
    path = Path(project) / "lean-toolchain"
    if not path.is_file():
        raise GraphError(f"missing {path}")
    toolchain = path.read_text(encoding="utf-8").strip()
    try:
        name = toolchain_dir_name(toolchain)
    except ConfigError as e:
        raise GraphError(str(e)) from None
    lib = elan_home() / "toolchains" / name / "lib" / "lean"
    if not lib.is_dir():
        raise GraphError(f"toolchain {toolchain} is not installed ({lib} missing)")
    return lib


def lib_oleans(lib: Path, trusted: bool) -> list[Olean]:
    """Every `<lib>/A/B.olean` as module `A.B`, sorted by module."""
    lib = Path(lib)
    if not lib.is_dir():
        return []
    out = []
    for p in lib.rglob("*.olean"):
        if not p.is_file():
            continue
        size = sum(q.stat().st_size for q in (Path(str(p) + s) for s in OLEAN_PARTS) if q.is_file())
        module = ".".join(p.relative_to(lib).with_suffix("").parts)
        out.append(Olean(module, p, size, trusted))
    return sorted(out, key=lambda o: o.module)


def discover(project: Path, tc_lib: Path, trusted: set[str]) -> list[Olean]:
    """Project modules first (root package, then untrusted packages), then the trusted base
    (trusted packages, then the toolchain). A module name seen twice keeps its first file."""
    project = Path(project)
    groups = [lib_oleans(project / ".lake" / "build" / "lib" / "lean", False)]
    packages = project / ".lake" / "packages"
    pkg_dirs = sorted(d for d in packages.iterdir() if d.is_dir()) if packages.is_dir() else []
    groups += [lib_oleans(d / ".lake" / "build" / "lib" / "lean", False)
               for d in pkg_dirs if d.name not in trusted]
    groups += [lib_oleans(d / ".lake" / "build" / "lib" / "lean", True)
               for d in pkg_dirs if d.name in trusted]
    groups.append(lib_oleans(tc_lib, True))
    seen, out = set(), []
    for group in groups:
        for o in group:
            if o.module in seen:
                print(f"lazarillo: graph: module {o.module} found twice, ignoring {o.path}", file=sys.stderr)
                continue
            seen.add(o.module)
            out.append(o)
    return out


def make_batches(oleans, max_modules=MAX_BATCH_MODULES, max_bytes=MAX_BATCH_BYTES) -> list[list[Olean]]:
    batches, cur, size = [], [], 0
    for o in oleans:
        if cur and (len(cur) >= max_modules or size + o.size > max_bytes):
            batches.append(cur)
            cur, size = [], 0
        cur.append(o)
        size += o.size
    if cur:
        batches.append(cur)
    return batches


def run_extractor(project: Path, batch: list[Olean], out_path: Path, log_path: Path, env: dict) -> None:
    """`lake env lean --run lean/Extract.lean <out> <files>` from PROJECT_DIR."""
    files = [str(o.path) for o in batch]
    cmd = ["lake", "env", "lean", "--run", str(EXTRACT_LEAN), str(out_path), *files]
    with open(log_path, "w", encoding="utf-8") as log:
        log.write(f"$ lake env lean --run {EXTRACT_LEAN} {out_path} <{len(files)} files: "
                  f"{batch[0].module} .. {batch[-1].module}>  (cwd {project})\n")
        log.flush()
        try:
            proc = subprocess.run(cmd, cwd=project, env=env, stdout=log, stderr=subprocess.STDOUT)
        except OSError as e:
            raise GraphError(f"cannot run lake: {e}") from None
        log.write(f"[exit {proc.returncode}]\n")
    if proc.returncode != 0:
        raise GraphError(f"extractor failed with exit code {proc.returncode} (see {log_path})")


class Graph:
    """All declarations, indexed by record; names interned as integers."""

    def __init__(self):
        self.names: list[str] = []
        self._ids: dict[str, int] = {}
        self.decl = array("I")  # name id -> record index or NO_DECL
        self.modules: list[str] = []
        self._module_ids: dict[str, int] = {}
        self.rec_name = array("I")
        self.rec_module = array("I")
        self.rec_kind = bytearray()
        self.rec_flags = bytearray()
        self.hash_type = array("Q")
        self.hash_value = array("Q")
        self.type_off = array("Q", [0])
        self.type_deps = array("I")
        self.value_off = array("Q", [0])
        self.value_deps = array("I")
        self.duplicates: list[str] = []

    def __len__(self) -> int:
        return len(self.rec_name)

    def intern(self, name: str) -> int:
        i = self._ids.get(name)
        if i is None:
            i = len(self.names)
            self._ids[name] = i
            self.names.append(name)
            self.decl.append(NO_DECL)
        return i

    def _module(self, module: str) -> int:
        i = self._module_ids.get(module)
        if i is None:
            i = len(self.modules)
            self._module_ids[module] = i
            self.modules.append(module)
        return i

    def add(self, row: dict, trusted: bool) -> bool:
        """Add one extractor line; a name already present keeps its first record."""
        nid = self.intern(row["name"])
        if self.decl[nid] != NO_DECL:
            self.duplicates.append(row["name"])
            return False
        kind = _KIND_CODE.get(row["kind"])
        if kind is None:
            raise GraphError(f"unknown kind {row['kind']!r} for {row['name']}")
        self.decl[nid] = len(self.rec_name)
        self.rec_name.append(nid)
        self.rec_module.append(self._module(row["module"]))
        self.rec_kind.append(kind)
        hv = row["hash_value"]
        self.rec_flags.append((_INTERNAL if row["internal"] else 0) | (_TRUSTED if trusted else 0)
                              | (_HAS_VALUE if hv is not None else 0))
        self.hash_type.append(int(row["hash_type"], 16))
        self.hash_value.append(int(hv, 16) if hv is not None else 0)
        self.type_deps.extend(dict.fromkeys(self.intern(d) for d in row["type_deps"]))
        self.type_off.append(len(self.type_deps))
        self.value_deps.extend(dict.fromkeys(self.intern(d) for d in row["value_deps"]))
        self.value_off.append(len(self.value_deps))
        return True

    def load(self, lines, trusted_of: dict[str, bool]) -> None:
        """Add NDJSON lines; trust comes from the module's origin (`trusted_of`)."""
        for line in lines:
            if not line.strip():
                continue
            row = json.loads(line)
            try:
                trusted = trusted_of[row["module"]]
            except KeyError:
                raise GraphError(f"declaration {row['name']} from unknown module {row['module']}") from None
            self.add(row, trusted)

    def _deps(self, r: int):
        yield from self.type_deps[self.type_off[r]:self.type_off[r + 1]]
        yield from self.value_deps[self.value_off[r]:self.value_off[r + 1]]

    def closure(self, target: str) -> list[int]:
        """Records reachable from `target` by type and value edges."""
        nid = self._ids.get(target)
        if nid is None or self.decl[nid] == NO_DECL:
            raise GraphError(f"target {target} not found in any module")
        seen = bytearray(len(self))
        root = self.decl[nid]
        seen[root] = 1
        stack, out, missing = [root], [], set()
        while stack:
            r = stack.pop()
            out.append(r)
            for d in self._deps(r):
                dr = self.decl[d]
                if dr == NO_DECL:
                    missing.add(self.names[d])
                elif not seen[dr]:
                    seen[dr] = 1
                    stack.append(dr)
        if missing:
            shown = ", ".join(sorted(missing)[:10])
            raise GraphError(f"{len(missing)} constants of the closure are in no module: {shown}")
        return out

    def name_of(self, r: int) -> str:
        return self.names[self.rec_name[r]]

    def _dep_names(self, deps, off, r: int) -> list[str]:
        return sorted({self.names[d] for d in deps[off[r]:off[r + 1]]})

    def row(self, r: int) -> dict:
        flags = self.rec_flags[r]
        return {
            "hash_type": f"{self.hash_type[r]:016x}",
            "hash_value": f"{self.hash_value[r]:016x}" if flags & _HAS_VALUE else None,
            "internal": bool(flags & _INTERNAL),
            "kind": KINDS[self.rec_kind[r]],
            "module": self.modules[self.rec_module[r]],
            "name": self.name_of(r),
            "trusted": bool(flags & _TRUSTED),
            "type_deps": self._dep_names(self.type_deps, self.type_off, r),
            "value_deps": self._dep_names(self.value_deps, self.value_off, r),
        }

    def rows(self, records):
        """`graph.ndjson` rows sorted by name."""
        for r in sorted(records, key=self.name_of):
            yield self.row(r)

    def project_decls(self) -> list[str]:
        return sorted(self.name_of(r) for r in range(len(self)) if not self.rec_flags[r] & _TRUSTED)


def write_outputs(graph: Graph, target: str, out: Path) -> None:
    jsonio.write_ndjson(out / "graph.ndjson", graph.rows(graph.closure(target)))
    jsonio.write_lines(out / "project_decls.txt", graph.project_decls())


def build_graph(project: Path, target: str, out: Path, tc_lib: Path | None = None,
                extract=run_extractor, env: dict | None = None) -> Graph:
    project, out = Path(project).resolve(), Path(out).resolve()
    oleans = discover(project, tc_lib if tc_lib is not None else toolchain_lib(project),
                      trusted_packages(project))
    if not any(not o.trusted for o in oleans):
        raise GraphError(f"no project .olean under {project}/.lake (run `lake build`)")
    trusted_of = {o.module: o.trusted for o in oleans}
    env = env if env is not None else lean_env()
    work = out / "work" / "graph"
    logs = out / "logs"
    work.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    graph = Graph()
    for i, batch in enumerate(make_batches(oleans)):
        nd = work / f"batch-{i:04d}.ndjson"
        extract(project, batch, nd, logs / f"graph-extract-{i:04d}.log", env)
        with open(nd, encoding="utf-8") as f:
            graph.load(f, trusted_of)
        nd.unlink()
    if graph.duplicates:
        shown = ", ".join(graph.duplicates[:10])
        print(f"lazarillo: graph: {len(graph.duplicates)} names declared in two modules, "
              f"kept the first: {shown}", file=sys.stderr)
    write_outputs(graph, target, out)
    return graph


def run_graph(args) -> int:
    try:
        build_graph(Path(args.project_dir), args.theorem, Path(args.out))
    except GraphError as e:
        print(f"lazarillo: graph: {e}", file=sys.stderr)
        return 1
    return 0
