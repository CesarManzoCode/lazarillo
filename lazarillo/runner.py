"""Measured stage runner: `/usr/bin/time -v` plus a process-tree VmRSS sampler (CONTRACT §3, §5).

The stage starts in its own session. A descendant whose parent exits is reparented outside
the tree, but keeps the session id, so each sample counts the tree walk plus every process
of the session: a process still alive at a sample is counted even if the process that
started it was born and died between two samples.
"""

import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import jsonio
from .config import REPO

TIME_BIN = "/usr/bin/time"
SAMPLE_INTERVAL_S = 0.2
TIMINGS_FORMAT = "lazarillo-timings/1"
_MAX_RSS_RE = re.compile(r"Maximum resident set size \(kbytes\):\s*(\d+)")


def _children(pid: int) -> list[int]:
    out = []
    try:
        tasks = os.listdir(f"/proc/{pid}/task")
    except OSError:
        return out
    for tid in tasks:
        try:
            with open(f"/proc/{pid}/task/{tid}/children") as f:
                out.extend(int(x) for x in f.read().split())
        except OSError:
            pass
    return out


def _vmrss_bytes(pid: int) -> int:
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0  # gone, or a zombie without VmRSS


def session_members(sid: int) -> list[int]:
    """Processes whose session id (field 6 of `/proc/<pid>/stat`) is `sid`."""
    out = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            with open(f"/proc/{entry}/stat") as f:
                stat = f.read()
        except OSError:
            continue
        fields = stat[stat.rfind(")") + 2:].split()
        if len(fields) > 3 and fields[3] == str(sid):
            out.append(int(entry))
    return out


def tree_rss_bytes(root: int) -> int:
    """Sum of VmRSS over `root`, all its descendants and every process of the session `root`
    leads (orphaned descendants included), each process once."""
    total, seen, stack = 0, set(), [root, *session_members(root)]
    while stack:
        pid = stack.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += _vmrss_bytes(pid)
        stack.extend(_children(pid))
    return total


def _sample(pid: int, rss_path: Path, t0: float, stop: threading.Event, peak: list) -> None:
    with open(rss_path, "w", encoding="utf-8") as f:
        while True:
            ms = int((time.monotonic() - t0) * 1000)
            rss = tree_rss_bytes(pid)
            f.write(f"{ms} {rss}\n")
            f.flush()
            peak[0] = max(peak[0], rss)
            if stop.wait(SAMPLE_INTERVAL_S):
                break


def parse_time_max_rss_kb(path) -> int:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    m = _MAX_RSS_RE.search(text)
    if not m:
        raise RuntimeError(f"no 'Maximum resident set size' in {path}")
    return int(m.group(1))


def read_rss_max(path) -> int:
    peak = 0
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2:
            peak = max(peak, int(parts[1]))
    return peak


def record_timing(out: Path, name: str, entry: dict) -> None:
    path = out / "timings.json"
    data = None
    if path.exists():
        data = jsonio.read_json(path)
    if not isinstance(data, dict) or data.get("format") != TIMINGS_FORMAT:
        data = {"format": TIMINGS_FORMAT, "stages": {}}
    data["stages"][name] = entry
    jsonio.write_json(path, data)


def run_measured(out, name: str, cmd: list[str], env: dict | None = None) -> int:
    """Run `cmd` under `/usr/bin/time -v`, sample tree RSS, record the stage in OUT/timings.json.

    Returns the child's exit code (as reported by GNU time).
    """
    out = Path(out)
    logs = out / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    time_path = logs / f"{name}.time"
    rss_path = logs / f"{name}.rss"

    stop = threading.Event()
    peak = [0]
    t0 = time.monotonic()
    proc = subprocess.Popen([TIME_BIN, "-v", "-o", str(time_path), *cmd], env=env, start_new_session=True)
    sampler = threading.Thread(target=_sample, args=(proc.pid, rss_path, t0, stop, peak), daemon=True)
    sampler.start()
    try:
        code = proc.wait()
    except BaseException:
        # The stage's own session does not get the terminal's signals: stop it here.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait()
        raise
    finally:
        wall = time.monotonic() - t0
        stop.set()
        sampler.join()

    kb = parse_time_max_rss_kb(time_path)
    record_timing(out, name, {
        "wall_s": round(wall, 3),
        "time_max_rss_kb": kb,
        "peak_rss_bytes": max(peak[0], kb * 1024),
        "log_time": time_path.relative_to(out).as_posix(),
        "log_rss": rss_path.relative_to(out).as_posix(),
    })
    return code


def stage_command(stage: str, run_argv: list[str]) -> list[str]:
    return [sys.executable, "-m", "lazarillo", "stage", stage, *run_argv]


def stage_env() -> dict:
    env = dict(os.environ)
    pp = env.get("PYTHONPATH")
    env["PYTHONPATH"] = str(REPO) + (os.pathsep + pp if pp else "")
    return env


def run_stage(out, stage: str, run_argv: list[str]) -> int:
    return run_measured(out, stage, stage_command(stage, run_argv), env=stage_env())
