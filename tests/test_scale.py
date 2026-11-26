import json
import os
import random
import resource
import shlex
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import core, graph, jsonio, runner  # noqa: E402

NODES = 200_000
DEPS_PER_NODE = 10  # 2,000,000 edges
TYPE_DEPS = 3
TARGET = f"P.n{NODES - 1}"
MAX_RSS_GROWTH_BYTES = 1_500_000_000


def node_name(i: int) -> str:
    return f"{'T' if i < NODES // 2 else 'P'}.n{i}"


def node_module(i: int) -> str:
    return f"{'T' if i < NODES // 2 else 'P'}.M{i // 1000}"


def write_synthetic(path: Path) -> None:
    """Extractor NDJSON, one row at a time: node `i` uses 10 distinct other nodes (cycles allowed);
    the first half is the trusted base, the second half the project."""
    rng = random.Random(0)
    with open(path, "w", encoding="utf-8") as f:
        for i in range(NODES):
            deps = [x + (x >= i) for x in rng.sample(range(NODES - 1), DEPS_PER_NODE)]
            f.write(json.dumps({
                "name": node_name(i), "module": node_module(i), "kind": "thm" if i % 3 else "def",
                "internal": i % 7 == 0, "hash_type": f"{i:016x}", "hash_value": f"{3 * i:016x}",
                "type_deps": [node_name(d) for d in deps[:TYPE_DEPS]],
                "value_deps": [node_name(d) for d in deps[TYPE_DEPS:]],
            }) + "\n")


def max_rss_bytes() -> int:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024  # kilobytes on Linux


class ScaleTest(unittest.TestCase):
    def test_closure_and_core_stay_bounded(self):
        before = max_rss_bytes()
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            extracted = tmp / "batch-0000.ndjson"
            write_synthetic(extracted)
            trusted_of = {node_module(i): i < NODES // 2 for i in range(0, NODES, 1000)}

            g = graph.Graph()
            with open(extracted, encoding="utf-8") as f:
                g.load(f, trusted_of)
            extracted.unlink()
            self.assertEqual(len(g), NODES)
            self.assertEqual(len(g.type_deps) + len(g.value_deps), NODES * DEPS_PER_NODE)
            self.assertEqual(len(g.names), NODES)

            records = g.closure(TARGET)
            closure_decls = len(records)
            core_decls = sum(1 for r in records if not g.rec_flags[r] & graph._TRUSTED)
            self.assertGreater(core_decls, 0)
            out = tmp / "out"
            out.mkdir()
            graph.write_outputs(g, TARGET, out)
            del g, records

            proj = tmp / "proj"
            proj.mkdir()
            (proj / "lean-toolchain").write_text("leanprover/lean4:v4.37.0-rc1\n", encoding="utf-8")
            args = SimpleNamespace(out=str(out), project_dir=str(proj), theorem=TARGET)
            self.assertEqual(core.run_core(args), 0)
            data = jsonio.read_json(out / "core.json")
            self.assertEqual(data["closure_decls"], closure_decls)
            self.assertEqual(data["core_decls"], core_decls)
            self.assertEqual(data["project_decls"], NODES // 2)
            self.assertEqual(data["core"], sorted(data["core"]))
            del data

            nodes = core.load_graph(out / "graph.ndjson", keep=core.project_or(TARGET))
            self.assertEqual(len(nodes), core_decls)
            for row in nodes.values():
                self.assertFalse(row["trusted"])
                self.assertTrue(all(d in nodes for d in row["type_deps"] + row["value_deps"]))
            del nodes
        growth = max_rss_bytes() - before
        self.assertLess(growth, MAX_RSS_GROWTH_BYTES, f"peak RSS grew by {growth} bytes")

    def test_batches_respect_both_limits(self):
        rng = random.Random(1)
        fake = Path("/nonexistent")
        oleans = [graph.Olean(f"M{i}", fake / f"M{i}.olean", rng.randrange(1, 64 << 20), False)
                  for i in range(5000)]
        huge = graph.Olean("Huge", fake / "Huge.olean", 3 << 30, True)
        oleans.insert(2500, huge)
        batches = graph.make_batches(oleans)
        self.assertEqual([o for b in batches for o in b], oleans)
        self.assertIn([huge], batches)
        for i, b in enumerate(batches):
            size = sum(o.size for o in b)
            self.assertLessEqual(len(b), graph.MAX_BATCH_MODULES)
            if len(b) > 1:
                self.assertLessEqual(size, graph.MAX_BATCH_BYTES)
            if i + 1 < len(batches):  # a batch closes only when the next module would break a limit
                nxt = batches[i + 1][0]
                self.assertTrue(len(b) == graph.MAX_BATCH_MODULES or size + nxt.size > graph.MAX_BATCH_BYTES)

        tiny = [graph.Olean(f"S{i}", fake / f"S{i}.olean", 1024, False) for i in range(2500)]
        self.assertEqual([len(b) for b in graph.make_batches(tiny)], [1000, 1000, 500])
        big = [graph.Olean(f"B{i}", fake / f"B{i}.olean", 100 << 20, False) for i in range(50)]
        self.assertEqual([len(b) for b in graph.make_batches(big)], [20, 20, 10])


ORPHAN = "import time; b = bytearray(128 << 20); b[::4096] = b'x' * len(b[::4096]); time.sleep(1.0)"


@unittest.skipUnless(os.path.exists(runner.TIME_BIN), "/usr/bin/time not available")
class SamplerTest(unittest.TestCase):
    def test_orphaned_descendant_is_counted(self):
        # The subshell starts the allocator in the background and exits at once, so the
        # allocator is reparented outside the stage's process tree while the stage sleeps.
        script = f"( {shlex.quote(sys.executable)} -c {shlex.quote(ORPHAN)} & ) ; sleep 1.5"
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self.assertEqual(runner.run_measured(out, "orphan", ["sh", "-c", script]), 0)
            samples = [int(line.split()[1]) for line in (out / "logs" / "orphan.rss").read_text().splitlines()]
            self.assertGreaterEqual(max(samples), 128 << 20)


if __name__ == "__main__":
    unittest.main()
