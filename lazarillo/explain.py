"""Explanations of the tree with a local model, and `tree.html` (CONTRACT §5, §6; D05, D06;
RESEARCH §4).

Decisions inside the contract:
- The index of a node is its position in `nodes` (depth, then name: BFS order); it names
  `logs/prompts/<i>.txt`, `logs/llm/<i>.txt` and the anchor `n-<i>`.
- The three goal states are the first, middle (`len // 2`) and last `TacticInfo` of the node;
  a node with three or fewer keeps them all. The children shown are the first ten by name.
- `llm.version` is the first non-empty line of `--version`; its whole output stays in
  `logs/llm/version.txt`. stdout of each call is the raw output; stderr goes to
  `logs/llm/<i>.stderr.txt`. A non-zero exit fails the stage.
- The clean text drops every `<think>…</think>` block (and an unclosed one up to the end),
  a trailing `[end of text]` marker and surrounding blank space.
- The model must be `work/models/<file>` with the sha256 of `corpora.toml`; otherwise the
  stage fails without calling the model.
"""

import html
import os
import re
import shutil
import subprocess
from pathlib import Path

from .config import load_corpora, work_dir
from .fetch import sha256_file

LLAMA_ENV = "LAZARILLO_LLAMA"
LLAMA_NAME = "llama-completion"
MAX_GOALS = 3
MAX_CHILDREN = 10
N_PREDICT = 400
CTX_SIZE = 8192
SAMPLING = {"temp": 0.7, "top_p": 0.8, "top_k": 20, "min_p": 0, "seed": 0}

SYSTEM = ("You are an expert in Lean 4 and Mathlib. You explain formal declarations and their "
          "proofs to working mathematicians, accurately and concisely.")
INSTRUCTION = ("In English and in at most 150 words, explain what this declaration states and how "
               "its proof proceeds, citing the goal states above.")

THINK_RE = re.compile(r"<think>.*?(</think>|\Z)", re.DOTALL)
END_RE = re.compile(r"\s*\[end of text\]\s*\Z")


class ExplainError(Exception):
    pass


# --- prompt ----------------------------------------------------------------------

def pick_goals(goals: list[dict]) -> list[dict]:
    """First, middle and last goal states."""
    if len(goals) <= MAX_GOALS:
        return list(goals)
    return [goals[0], goals[len(goals) // 2], goals[-1]]


def _goal_text(g: dict) -> str:
    before = "\n\n".join(g["before"]) if g["before"] else "(no goals)"
    rng = g.get("range")
    where = f" (lines {rng[0]}-{rng[1]})" if rng else ""
    return f"Before `{g['tactic']}`{where}:\n{before}"


def user_message(node: dict, children: list[dict]) -> str:
    parts = [f"Declaration: {node['name']}", f"Kind: {node['kind']}",
             f"Type:\n{node['statement'] or '(not available)'}"]
    goals = pick_goals(node["goals"])
    if goals:
        lines = [f"Goal states ({len(goals)} of {len(node['goals'])}):"]
        for i, g in enumerate(goals, 1):
            lines.append(f"[{i}] {_goal_text(g)}")
        parts.append("\n".join(lines))
    else:
        parts.append("Goal states: none recorded.")
    shown = children[:MAX_CHILDREN]
    if shown:
        lines = [f"Declarations it relies on ({len(shown)} of {len(children)}):"]
        for c in shown:
            lines.append(f"- {c['name']} : {c['statement'] or '(type not available)'}")
        parts.append("\n".join(lines))
    else:
        parts.append("Declarations it relies on: none in the tree.")
    parts.append(INSTRUCTION)
    return "\n\n".join(parts)


def build_prompt(node: dict, children: list[dict]) -> str:
    """Qwen3 chat template with reasoning switched off (CONTRACT §6)."""
    return (f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
            f"<|im_start|>user\n{user_message(node, children)}<|im_end|>\n"
            "<|im_start|>assistant\n<think>\n\n</think>\n\n")


def clean(raw: str) -> str:
    return END_RE.sub("", THINK_RE.sub("", raw)).strip()


# --- binary and model ------------------------------------------------------------

def find_llama() -> str:
    """`$LAZARILLO_LLAMA` or `llama-completion` in `PATH`, as an absolute path."""
    env = os.environ.get(LLAMA_ENV)
    if env:
        path = Path(env)
        if not (path.is_file() and os.access(path, os.X_OK)):
            raise ExplainError(f"${LLAMA_ENV}={env} is not an executable file")
        return str(path.absolute())
    found = shutil.which(LLAMA_NAME)
    if found is None:
        raise ExplainError(f"{LLAMA_NAME} not found in PATH: install the Arch package llama-cpp "
                           f"(pacman -S llama-cpp) or set ${LLAMA_ENV}")
    return str(Path(found).absolute())


def llama_version(binary: str, log: Path) -> str:
    try:
        proc = subprocess.run([binary, "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, text=True, errors="replace")
    except OSError as e:
        raise ExplainError(f"cannot run {binary}: {e}") from None
    log.write_text(proc.stdout, encoding="utf-8")
    if proc.returncode != 0:
        raise ExplainError(f"{binary} --version exited {proc.returncode} (see {log})")
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise ExplainError(f"{binary} --version printed nothing")
    return lines[0]


def check_model(model_cfg: dict, work: Path) -> tuple[Path, str]:
    path = work / "models" / model_cfg["file"]
    if not path.is_file():
        raise ExplainError(f"model {path} not found: run `python3 -m lazarillo fetch --model CORPUS`")
    digest = sha256_file(path)
    if digest != model_cfg["sha256"]:
        raise ExplainError(f"model {path} has sha256 {digest}, corpora.toml says {model_cfg['sha256']}")
    return path, digest


def params(threads: int) -> dict:
    return {"n_predict": N_PREDICT, "ctx_size": CTX_SIZE, "threads": threads, **SAMPLING}


def llama_command(binary: str, model: Path, prompt: Path, threads: int) -> list[str]:
    """The exact invocation of CONTRACT §6."""
    return [binary, "-m", str(model), "-f", str(prompt), "-n", str(N_PREDICT), "-c", str(CTX_SIZE),
            "-t", str(threads), "--temp", str(SAMPLING["temp"]), "--top-p", str(SAMPLING["top_p"]),
            "--top-k", str(SAMPLING["top_k"]), "--min-p", str(SAMPLING["min_p"]),
            "--seed", str(SAMPLING["seed"]), "-no-cnv", "--no-display-prompt", "--offline",
            "--simple-io", "--log-disable"]


# --- stage step ------------------------------------------------------------------

def explain_tree(tree_nodes: list[dict], explain_depth: int, out: Path, model_cfg: dict | None = None,
                 work: Path | None = None) -> dict:
    """Fill `explanation` of every node with `depth <= explain_depth`, one call at a time in BFS
    order; return the `llm` object of `tree.json`."""
    out = Path(out)
    prompts, llm_logs = out / "logs" / "prompts", out / "logs" / "llm"
    prompts.mkdir(parents=True, exist_ok=True)
    llm_logs.mkdir(parents=True, exist_ok=True)
    model_cfg = model_cfg if model_cfg is not None else load_corpora()["model"]
    binary = find_llama()
    version = llama_version(binary, llm_logs / "version.txt")
    model, digest = check_model(model_cfg, work if work is not None else work_dir())
    threads = os.cpu_count() or 1
    by_name = {n["name"]: n for n in tree_nodes}
    for i, n in enumerate(tree_nodes):
        if n["depth"] > explain_depth:
            continue
        prompt = prompts / f"{i}.txt"
        prompt.write_text(build_prompt(n, [by_name[c] for c in n["children"]]), encoding="utf-8")
        raw = llm_logs / f"{i}.txt"
        err = llm_logs / f"{i}.stderr.txt"
        try:
            with open(raw, "wb") as f, open(err, "wb") as e:
                proc = subprocess.run(llama_command(binary, model, prompt, threads),
                                      stdin=subprocess.DEVNULL, stdout=f, stderr=e)
        except OSError as e:
            raise ExplainError(f"cannot run {binary}: {e}") from None
        if proc.returncode != 0:
            raise ExplainError(f"{LLAMA_NAME} exited {proc.returncode} on node {i} {n['name']} (see {err})")
        n["explanation"] = clean(raw.read_text(encoding="utf-8", errors="replace"))
    return {"binary": binary, "version": version, "model": model.name, "model_sha256": digest,
            "params": params(threads)}


# --- tree.html -------------------------------------------------------------------

def _e(text) -> str:
    return html.escape(str(text), quote=True)


def _node_body(i: int, n: dict, index: dict[str, int]) -> list[str]:
    out = [f'<details id="n-{i}">',
           f"<summary><code>{_e(n['name'])}</code> <small>{_e(n['kind'])}</small></summary>",
           '<div class="node">']
    where = _e(n["module"])
    if n["file"]:
        rng = f":{n['range'][0]}-{n['range'][1]}" if n["range"] else ""
        where += f" — <code>{_e(n['file'])}{_e(rng)}</code>"
    out.append(f"<p>{where}</p>")
    if n["statement"]:
        out.append(f"<pre>{_e(n['statement'])}</pre>")
    if n["explanation"] is not None:
        out.append(f'<p class="explanation">{_e(n["explanation"])}</p>')
    if n["uses"]:
        links = ", ".join(f'<a href="#n-{index[u]}"><code>{_e(u)}</code></a>' for u in n["uses"])
        out.append(f"<p>Uses: {links}</p>")
    if n["goals"]:
        out.append(f"<details><summary>Goals ({len(n['goals'])})</summary><ol>")
        for g in n["goals"]:
            before = "\n\n".join(g["before"]) if g["before"] else "(no goals)"
            out.append(f"<li><code>{_e(g['tactic'])}</code><pre>{_e(before)}</pre></li>")
        out.append("</ol></details>")
    return out


STYLE = ("body{font-family:sans-serif;max-width:60em;margin:1em auto;padding:0 1em}"
         "details{margin:.3em 0 .3em 1.2em}.node{border-left:2px solid #ccc;padding-left:.6em}"
         "pre{white-space:pre-wrap;background:#f6f6f6;padding:.4em}.explanation{white-space:pre-wrap}")


def tree_html(data: dict) -> str:
    """One self-contained file: `<details>` nested by `children`, no scripts or external resources."""
    nodes = data["nodes"]
    index = {n["name"]: i for i, n in enumerate(nodes)}
    lines = ["<!DOCTYPE html>", '<html lang="en">', "<head>", '<meta charset="utf-8">',
             f"<title>{_e(data['target'])}</title>", f"<style>{STYLE}</style>", "</head>", "<body>",
             f"<h1><code>{_e(data['target'])}</code></h1>"]
    if nodes:
        stack = [("open", 0)]
        while stack:
            op, i = stack.pop()
            if op == "close":
                lines.append("</div></details>")
                continue
            lines.extend(_node_body(i, nodes[i], index))
            stack.append(("close", i))
            stack.extend(("open", index[c]) for c in reversed(nodes[i]["children"]))
    lines.extend(["</body>", "</html>"])
    return "\n".join(lines) + "\n"


def write_tree_html(path: Path, data: dict) -> None:
    Path(path).write_text(tree_html(data), encoding="utf-8")
