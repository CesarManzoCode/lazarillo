import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from lazarillo import jsonio, runner  # noqa: E402

CHILD = "import time; b = bytearray(64 * 1024 * 1024); b[::4096] = b'x' * len(b[::4096]); time.sleep(0.8)"


@unittest.skipUnless(os.path.exists(runner.TIME_BIN), "/usr/bin/time not available")
class RunnerTest(unittest.TestCase):
    def test_measured_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            code = runner.run_measured(out, "probe", [sys.executable, "-c", CHILD])
            self.assertEqual(code, 0)

            timings = jsonio.read_json(out / "timings.json")
            self.assertEqual(timings["format"], "lazarillo-timings/1")
            e = timings["stages"]["probe"]
            self.assertEqual(set(e), {"wall_s", "peak_rss_bytes", "time_max_rss_kb", "log_time", "log_rss"})
            self.assertEqual(e["log_time"], "logs/probe.time")
            self.assertEqual(e["log_rss"], "logs/probe.rss")

            time_text = (out / e["log_time"]).read_text()
            kb = int(re.search(r"Maximum resident set size \(kbytes\):\s*(\d+)", time_text).group(1))
            self.assertEqual(e["time_max_rss_kb"], kb)

            lines = (out / e["log_rss"]).read_text().splitlines()
            self.assertGreaterEqual(len(lines), 2)
            samples = []
            for line in lines:
                self.assertRegex(line, r"^\d+ \d+$")
                ms, b = map(int, line.split())
                samples.append((ms, b))
            self.assertEqual([ms for ms, _ in samples], sorted(ms for ms, _ in samples))
            self.assertEqual(e["peak_rss_bytes"], max(max(b for _, b in samples), kb * 1024))

            self.assertGreaterEqual(e["peak_rss_bytes"], 64 * 1024 * 1024)
            self.assertGreaterEqual(max(b for _, b in samples), 64 * 1024 * 1024)
            self.assertGreater(e["wall_s"], 0.5)

    def test_second_stage_is_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            runner.run_measured(out, "a", [sys.executable, "-c", "pass"])
            code = runner.run_measured(out, "b", [sys.executable, "-c", "raise SystemExit(3)"])
            self.assertEqual(code, 3)
            stages = jsonio.read_json(out / "timings.json")["stages"]
            self.assertEqual(set(stages), {"a", "b"})


class JsonioTest(unittest.TestCase):
    def test_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "x.json"
            q = Path(tmp) / "x.ndjson"
            jsonio.write_json(p, {"b": 1, "a": "ñ"})
            jsonio.write_ndjson(q, [{"b": 1, "a": [2, 3]}])
            self.assertEqual(p.read_text(encoding="utf-8"), '{\n  "a": "ñ",\n  "b": 1\n}\n')
            self.assertEqual(q.read_text(encoding="utf-8"), '{"a":[2,3],"b":1}\n')


if __name__ == "__main__":
    unittest.main()
