from __future__ import annotations

import argparse
import json
import os
import sys
from importlib import resources
from pathlib import Path

from .agentloop_runtime import AgentLoopRuntime
from .evolution import EvolutionEngine
from .experiment import ExperimentConfig, ExperimentRunner
from .gate import EvaluationGate
from .runtime import DemoRuntime
from .tasks import build_adapter
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
    run.add_argument("--adapter", choices=("exact", "json"), default="exact")
    run.add_argument("--iterations", type=int, default=1)
    run.add_argument("--epsilon", type=float, default=0.0)
    run.add_argument("--min-improved-tasks", type=int, default=1)
    run.add_argument("--max-regressed-tasks", type=int)

    experiment = sub.add_parser(
        "experiment",
        help="run repeated real-model evolution with three Test baselines and a report",
    )
    experiment.add_argument("--output", required=True, type=Path)
    experiment.add_argument("--experiment-id")
    experiment.add_argument("--tasks", required=True, type=Path)
    experiment.add_argument("--adapter", choices=("exact", "json"), required=True)
    experiment.add_argument("--skill-name", required=True)
    experiment.add_argument("--skill-file", required=True, type=Path)
    experiment.add_argument("--iterations", type=int, default=3)
    experiment.add_argument("--repeats", type=int, default=3)
    experiment.add_argument("--epsilon", type=float, default=0.0)
    experiment.add_argument("--min-improved-tasks", type=int, default=1)
    experiment.add_argument("--max-regressed-tasks", type=int)
    experiment.add_argument("--bootstrap-samples", type=int, default=1_000)
    experiment.add_argument("--bootstrap-seed", "--seed", dest="bootstrap_seed", type=int, default=0)
    experiment.add_argument("--max-turns", type=int, default=20)
    experiment.add_argument("--runtime", choices=("agentloop", "demo"), default="agentloop")

    demo = sub.add_parser("demo", help="run deterministic local orchestration demo")
    demo.add_argument("--workspace", required=True, type=Path)
    demo.add_argument("--iterations", type=int, default=1)
    return parser


def _run_engine(args: argparse.Namespace, runtime) -> dict:
    workspace = Workspace(args.workspace)
    adapter = build_adapter(getattr(args, "adapter", "exact"), args.tasks)
    engine = EvolutionEngine(
        workspace=workspace,
        runtime=runtime,
        adapter=adapter,
        gate=EvaluationGate(
            getattr(args, "epsilon", 0.0),
            min_improved_tasks=getattr(args, "min_improved_tasks", 1),
            max_regressed_tasks=getattr(args, "max_regressed_tasks", None),
        ),
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
            demo_resource = resources.files("skill_learning").joinpath(
                "data", "normalization-tasks.jsonl"
            )
            with resources.as_file(demo_resource) as demo_tasks:
                args.tasks = demo_tasks
                args.adapter = "exact"
                summary = _run_engine(args, DemoRuntime())
        elif args.command == "experiment":
            if args.runtime == "demo":
                runtime_factory = DemoRuntime
            else:
                _load_dotenv()
                try:
                    from agentloop.models import build_client
                except ImportError as exc:
                    raise RuntimeError("AgentLoop dependency is not installed") from exc
                runtime_factory = lambda: AgentLoopRuntime(
                    build_client(),
                    max_turns=args.max_turns,
                )
            config = ExperimentConfig(
                experiment_id=args.experiment_id or args.output.name,
                dataset_path=args.tasks,
                adapter_name=args.adapter,
                skill_name=args.skill_name,
                skill_path=args.skill_file,
                iterations=args.iterations,
                repeats=args.repeats,
                epsilon=args.epsilon,
                min_improved_tasks=args.min_improved_tasks,
                max_regressed_tasks=args.max_regressed_tasks,
                bootstrap_samples=args.bootstrap_samples,
                bootstrap_seed=args.bootstrap_seed,
            )
            experiment_summary = ExperimentRunner(
                output_dir=args.output,
                config=config,
                runtime_factory=runtime_factory,
            ).run()
            summary = {
                "experiment_id": experiment_summary["experiment_id"],
                "report": str((args.output / "report.md").resolve()),
                "conditions": {
                    name: values["mean_score"]
                    for name, values in experiment_summary["conditions"].items()
                },
                "paired_statistics": experiment_summary["paired_statistics"],
            }
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
