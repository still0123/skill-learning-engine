from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .agentloop_runtime import AgentLoopRuntime
from .evolution import EvolutionEngine
from .gate import EvaluationGate
from .runtime import DemoRuntime
from .tasks import ExactMatchJSONLAdapter
from .workspace import Workspace


DEFAULT_SKILL = """# Normalize Text

## Procedure

Return the input unchanged.
"""


def _load_dotenv(path: Path = Path(".env")) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() and key.strip() not in os.environ:
            os.environ[key.strip()] = value.strip()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="skill-learning",
        description="Experience-driven Skill learning with persistent knowledge and evaluation gates.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="initialize a learning workspace")
    init.add_argument("--workspace", required=True, type=Path)
    init.add_argument("--skill-name", default="normalize")
    init.add_argument("--skill-file", type=Path)

    run = sub.add_parser("run", help="run real-model evolution through AgentLoop")
    run.add_argument("--workspace", required=True, type=Path)
    run.add_argument("--tasks", required=True, type=Path)
    run.add_argument("--iterations", type=int, default=1)
    run.add_argument("--epsilon", type=float, default=0.0)

    demo = sub.add_parser("demo", help="run deterministic local orchestration demo")
    demo.add_argument("--workspace", required=True, type=Path)
    demo.add_argument("--iterations", type=int, default=1)
    return parser


def _run_engine(args: argparse.Namespace, runtime) -> dict:
    workspace = Workspace(args.workspace)
    adapter = ExactMatchJSONLAdapter(args.tasks)
    engine = EvolutionEngine(
        workspace=workspace,
        runtime=runtime,
        adapter=adapter,
        gate=EvaluationGate(getattr(args, "epsilon", 0.0)),
    )
    return engine.run(iterations=args.iterations).to_dict()


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            skill_text = (
                args.skill_file.read_text(encoding="utf-8")
                if args.skill_file
                else DEFAULT_SKILL
            )
            Workspace(args.workspace).initialize(
                skill_name=args.skill_name,
                skill_text=skill_text,
            )
            print(f"initialized workspace: {args.workspace.resolve()}")
            return 0

        if args.command == "demo":
            workspace = Workspace(args.workspace)
            if not workspace.state_path.exists():
                workspace.initialize(skill_name="normalize", skill_text=DEFAULT_SKILL)
            args.tasks = Path(__file__).resolve().parents[1] / "examples" / "normalization" / "tasks.jsonl"
            summary = _run_engine(args, DemoRuntime())
        else:
            _load_dotenv()
            try:
                from agentloop.models import build_client
            except ImportError as exc:
                raise RuntimeError("AgentLoop dependency is not installed") from exc
            summary = _run_engine(args, AgentLoopRuntime(build_client()))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:  # CLI boundary
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
