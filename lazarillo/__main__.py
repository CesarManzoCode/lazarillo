"""Command line interface (CONTRACT §4)."""

import argparse
import importlib
import sys
from pathlib import Path

from .config import STAGES, ConfigError, parse_depth

STAGE_MODULES = {"graph": "graph", "core": "core", "kernels": "kernels", "audit": "audit", "tree": "tree"}


class UsageError(Exception):
    pass


def _stages_arg(text: str) -> list[str]:
    names = [s.strip() for s in text.split(",") if s.strip()]
    bad = [s for s in names if s not in STAGES]
    if not names or bad:
        raise argparse.ArgumentTypeError(f"invalid stages {text!r}; choose from {','.join(STAGES)}")
    return [s for s in STAGES if s in names]  # contract order, no repeats


def _depth_arg(text: str):
    try:
        return parse_depth(text)
    except ConfigError as e:
        raise argparse.ArgumentTypeError(str(e)) from None


def _explain_depth_arg(text: str) -> int:
    value = _depth_arg(text)
    if value == "all":
        raise argparse.ArgumentTypeError("--explain-depth must be a non-negative integer")
    return value


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("project_dir", metavar="PROJECT_DIR")
    p.add_argument("theorem", metavar="THEOREM")
    p.add_argument("--out", required=True, metavar="OUT")
    ref = p.add_mutually_exclusive_group()
    ref.add_argument("--challenge-module", metavar="MODULE")
    ref.add_argument("--reference", metavar="FILE")
    p.add_argument("--stages", type=_stages_arg, default=list(STAGES), metavar="graph,core,kernels,audit,tree")
    p.add_argument("--depth", type=_depth_arg, default=2, metavar="N|all")
    p.add_argument("--explain-depth", type=_explain_depth_arg, default=1, metavar="N")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lazarillo")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("fetch", help="install toolchains, clone and build corpora (network)")
    p.add_argument("--model", action="store_true")
    p.add_argument("corpora", nargs="+", metavar="CORPUS")

    _add_run_args(sub.add_parser("run", help="analyse a theorem of a compiled Lean project"))

    p = sub.add_parser("measure", help="run a corpus from corpora.toml and write its summary")
    p.add_argument("corpus", metavar="CORPUS")

    p = sub.add_parser("mutate", help="seeded mutations of the flattened reference")
    p.add_argument("--run", required=True, metavar="RUN_DIR")
    p.add_argument("--project", required=True, metavar="PROJECT_DIR")
    p.add_argument("--out", required=True, metavar="OUT")

    p = sub.add_parser("blueprint", help="calibrate the tree against a blueprint")
    p.add_argument("--tex-dir", required=True, metavar="DIR")
    p.add_argument("--run", required=True, metavar="RUN_DIR")
    p.add_argument("--root-label", required=True, metavar="LABEL")
    p.add_argument("--root-decl", required=True, metavar="DECL")
    p.add_argument("--out", required=True, metavar="FILE")

    sub.add_parser("summarize", help="collect work/results into work/results/summary.json")

    p = sub.add_parser("stage", help="internal: run one stage (used by `run`)")
    p.add_argument("stage_name", choices=STAGES, metavar="STAGE")
    _add_run_args(p)
    return parser


def run_argv(args) -> list[str]:
    """Normalised `run` arguments, forwarded verbatim to every `stage` child."""
    argv = [args.project_dir, args.theorem, "--out", args.out]
    if args.challenge_module:
        argv += ["--challenge-module", args.challenge_module]
    if args.reference:
        argv += ["--reference", args.reference]
    argv += ["--stages", ",".join(args.stages), "--depth", str(args.depth),
             "--explain-depth", str(args.explain_depth)]
    return argv


def validate_run(args) -> None:
    if not Path(args.project_dir).is_dir():
        raise UsageError(f"PROJECT_DIR is not a directory: {args.project_dir}")
    if args.reference and not Path(args.reference).is_file():
        raise UsageError(f"--reference is not a file: {args.reference}")
    if not args.theorem.strip():
        raise UsageError("THEOREM is empty")


def cmd_run(args) -> int:
    from . import runner

    validate_run(args)
    out = Path(args.out)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    argv = run_argv(args)
    for stage in args.stages:
        code = runner.run_stage(out, stage, argv)
        if code != 0:
            print(f"lazarillo: stage {stage} failed with exit code {code}", file=sys.stderr)
            return 1
    return 0


def cmd_fetch(args) -> int:
    from . import fetch

    return fetch.main(args.corpora, args.model)


def cmd_measure(args) -> int:
    from . import measure

    return measure.main(args.corpus)


def cmd_mutate(args) -> int:
    from . import mutate

    return mutate.main(args)


def cmd_blueprint(args) -> int:
    from . import blueprint

    return blueprint.main(args)


def cmd_stage(args) -> int:
    validate_run(args)
    module_name = f"lazarillo.{STAGE_MODULES[args.stage_name]}"
    try:
        module = importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name != module_name:
            raise
        print(f"lazarillo: stage {args.stage_name} is not implemented yet ({module_name} missing)",
              file=sys.stderr)
        return 2
    func = getattr(module, f"run_{args.stage_name}", None)
    if func is None:
        print(f"lazarillo: {module_name} has no run_{args.stage_name}", file=sys.stderr)
        return 2
    return func(args) or 0


def not_implemented(args) -> int:
    print(f"lazarillo: command {args.command!r} is not implemented yet", file=sys.stderr)
    return 2


COMMANDS = {"fetch": cmd_fetch, "run": cmd_run, "measure": cmd_measure, "mutate": cmd_mutate,
            "blueprint": cmd_blueprint, "stage": cmd_stage}


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return COMMANDS.get(args.command, not_implemented)(args)
    except (UsageError, ConfigError) as e:
        print(f"lazarillo: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
