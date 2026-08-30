from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Callable

from .components import TaskExecutor
from .evolution import EvolutionEngine
from .gate import EvaluationGate
from .runtime import StructuredRuntime
from .statistics import paired_bootstrap
from .tasks import build_adapter
from .workspace import Workspace


_EXPERIMENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class ExperimentConfig:
    experiment_id: str
    dataset_path: Path
    adapter_name: str
    skill_name: str
    skill_path: Path
    iterations: int = 3
    repeats: int = 3
    epsilon: float = 0.0
    min_improved_tasks: int = 1
    max_regressed_tasks: int | None = None
    bootstrap_samples: int = 1_000
    bootstrap_seed: int = 0

    def __post_init__(self) -> None:
        if not _EXPERIMENT_ID.fullmatch(self.experiment_id):
            raise ValueError("experiment_id must be a safe path component")
        if self.iterations < 1:
            raise ValueError("iterations must be at least 1")
        if self.repeats < 1:
            raise ValueError("repeats must be at least 1")
        if self.bootstrap_samples < 100:
            raise ValueError("bootstrap_samples must be at least 100")

    def to_dict(self) -> dict:
        data = asdict(self)
        data["dataset_path"] = str(self.dataset_path.resolve())
        data["skill_path"] = str(self.skill_path.resolve())
        return data


class ExperimentRunner:
    def __init__(
        self,
        *,
        output_dir: str | Path,
        config: ExperimentConfig,
        runtime_factory: Callable[[], StructuredRuntime],
    ) -> None:
        self.output_dir = Path(output_dir).resolve()
        self.config = config
        self.runtime_factory = runtime_factory

    def run(self) -> dict:
        if self.output_dir.exists():
            raise FileExistsError(f"experiment output already exists: {self.output_dir}")
        self.output_dir.mkdir(parents=True)
        seed_skill = self.config.skill_path.read_text(encoding="utf-8")
        adapter = build_adapter(self.config.adapter_name, self.config.dataset_path)
        prompts = _load_prompts()
        first_runtime = self.runtime_factory()
        manifest = self._write_manifest(
            runtime=first_runtime,
            dataset_sha256=adapter.dataset_fingerprint(),
            seed_skill=seed_skill,
            prompts=prompts,
        )
        repeat_results: list[dict] = []
        for index in range(1, self.config.repeats + 1):
            runtime = first_runtime if index == 1 else self.runtime_factory()
            try:
                if runtime.describe() != manifest["runtime"]:
                    raise ValueError(
                        f"runtime configuration changed before repeat {index}; "
                        "all repeats must use the manifest runtime"
                    )
                repeat_results.append(self._run_repeat(index, runtime, seed_skill, prompts))
            except Exception as exc:
                _write_json(
                    self.output_dir / f"repeat-{index:03d}" / "failure.json",
                    {"type": type(exc).__name__, "message": str(exc)},
                )
                raise

        summary = self._summarize(manifest, repeat_results)
        _write_json(self.output_dir / "summary.json", summary)
        _atomic_write(self.output_dir / "report.md", self._render_report(summary))
        return summary

    def _run_repeat(
        self,
        index: int,
        runtime: StructuredRuntime,
        seed_skill: str,
        prompts: dict[str, str],
    ) -> dict:
        repeat_dir = self.output_dir / f"repeat-{index:03d}"
        workspace = Workspace(repeat_dir / "workspace")
        workspace.initialize(skill_name=self.config.skill_name, skill_text=seed_skill)
        adapter = build_adapter(
            self.config.adapter_name,
            self.output_dir / "inputs" / "tasks.jsonl",
        )
        gate = EvaluationGate(
            self.config.epsilon,
            min_improved_tasks=self.config.min_improved_tasks,
            max_regressed_tasks=self.config.max_regressed_tasks,
        )
        evolution = EvolutionEngine(
            workspace=workspace,
            runtime=runtime,
            adapter=adapter,
            gate=gate,
            prompts=prompts,
        ).run(iterations=self.config.iterations, evaluate_test=False)

        state = workspace.load_state()
        final_skill = workspace.read_skill(self.config.skill_name)
        executor = TaskExecutor(
            runtime,
            adapter,
            system_prompt=prompts["executor.md"],
        )
        conditions = (
            ("no_skill", "", -1),
            ("seed_skill", seed_skill, 0),
            ("evolved_skill", final_skill, int(state["version"])),
        )
        evaluations = {}
        for condition, skill_text, version in conditions:
            evaluation_skill_name = self.config.skill_name if skill_text.strip() else "no-skill"
            evaluation = executor.evaluate(
                tasks=adapter.tasks("test"),
                skill_name=evaluation_skill_name,
                skill_version=version,
                skill_text=skill_text,
                iteration=int(state["iteration"]),
                phase=f"test-{condition.replace('_', '-')}",
                workdir=workspace.root,
            )
            workspace.record_evaluation(evaluation)
            evaluations[condition] = {
                "mean_score": evaluation.mean_score,
                "metrics": evaluation.metrics,
                "usage": evaluation.usage,
                "duration_ms": sum(trace.duration_ms for trace in evaluation.traces),
                "task_scores": evaluation.task_scores,
            }

        result = {
            "repeat": index,
            "runtime": runtime.describe(),
            "evolution": evolution.to_dict(),
            "final_skill_sha256": _sha256_text(final_skill),
            "conditions": evaluations,
        }
        _write_json(repeat_dir / "summary.json", result)
        return result

    def _write_manifest(
        self,
        *,
        runtime: StructuredRuntime,
        dataset_sha256: str,
        seed_skill: str,
        prompts: dict[str, str],
    ) -> dict:
        inputs = self.output_dir / "inputs"
        prompt_dir = inputs / "prompts"
        prompt_dir.mkdir(parents=True)
        shutil.copy2(self.config.dataset_path, inputs / "tasks.jsonl")
        _atomic_write(inputs / "seed-skill.md", seed_skill)
        prompt_hashes: dict[str, str] = {}
        for name, text in prompts.items():
            _atomic_write(prompt_dir / name, text)
            prompt_hashes[name] = _sha256_text(text)
        source = _source_state()
        manifest = {
            "schema_version": 2,
            "experiment_id": self.config.experiment_id,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "python": platform.python_version(),
            "source": source,
            "runtime": runtime.describe(),
            "config": self.config.to_dict(),
            "inputs": {
                "dataset_sha256": dataset_sha256,
                "seed_skill_sha256": _sha256_text(seed_skill),
                "prompt_sha256": prompt_hashes,
            },
        }
        _write_json(self.output_dir / "manifest.json", manifest)
        return manifest

    def _summarize(self, manifest: dict, repeats: list[dict]) -> dict:
        condition_names = ("no_skill", "seed_skill", "evolved_skill")
        conditions = {
            name: {
                "mean_score": sum(item["conditions"][name]["mean_score"] for item in repeats)
                / len(repeats),
                "repeat_scores": [item["conditions"][name]["mean_score"] for item in repeats],
                "usage": _sum_usage(item["conditions"][name]["usage"] for item in repeats),
                "duration_ms": sum(item["conditions"][name]["duration_ms"] for item in repeats),
            }
            for name in condition_names
        }
        paired = {
            "seed_vs_no_skill": self._bootstrap(repeats, "no_skill", "seed_skill"),
            "evolved_vs_seed_skill": self._bootstrap(repeats, "seed_skill", "evolved_skill"),
            "evolved_vs_no_skill": self._bootstrap(repeats, "no_skill", "evolved_skill"),
        }
        return {
            "schema_version": 2,
            "experiment_id": self.config.experiment_id,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "manifest": manifest,
            "conditions": conditions,
            "paired_statistics": paired,
            "evolution": {
                "accepted": sum(item["evolution"]["accepted"] for item in repeats),
                "rejected": sum(item["evolution"]["rejected"] for item in repeats),
                "final_versions": [item["evolution"]["final_version"] for item in repeats],
                "final_validation_scores": [
                    item["evolution"]["final_validation_score"] for item in repeats
                ],
            },
            "repeats": repeats,
        }

    def _bootstrap(self, repeats: list[dict], baseline: str, candidate: str) -> dict:
        baseline_samples: dict[str, list[float]] = {}
        candidate_samples: dict[str, list[float]] = {}
        for repeat in repeats:
            for task_id, score in repeat["conditions"][baseline]["task_scores"].items():
                baseline_samples.setdefault(task_id, []).append(score)
            for task_id, score in repeat["conditions"][candidate]["task_scores"].items():
                candidate_samples.setdefault(task_id, []).append(score)
        baseline_scores = {
            task_id: sum(values) / len(values)
            for task_id, values in baseline_samples.items()
        }
        candidate_scores = {
            task_id: sum(values) / len(values)
            for task_id, values in candidate_samples.items()
        }
        return paired_bootstrap(
            baseline_scores,
            candidate_scores,
            samples=self.config.bootstrap_samples,
            seed=self.config.bootstrap_seed,
        ).to_dict()

    def _render_report(self, summary: dict) -> str:
        runtime = summary["manifest"]["runtime"]
        conditions = summary["conditions"]
        comparisons = summary["paired_statistics"]
        deterministic_note = (
            "本报告来自确定性 Demo Runtime，只验证实验编排，不代表真实模型效果。"
            if runtime.get("runtime") == "demo"
            else "本报告来自真实模型调用；结论仍受任务规模、模型随机性和运行次数限制。"
        )
        lines = [
            f"# Experiment Report: {self.config.experiment_id}",
            "",
            deterministic_note,
            "",
            "## Protocol",
            "",
            f"- Adapter: `{self.config.adapter_name}`",
            f"- Model: `{runtime.get('model', 'unknown')}`",
            f"- Repeats: {self.config.repeats}",
            f"- Evolution iterations: {self.config.iterations}",
            f"- Bootstrap samples: {self.config.bootstrap_samples}",
            "- Confidence interval: paired percentile Bootstrap by unique Test task.",
            "- P-value: two-sided paired sign-flip randomization test.",
            "- Test was evaluated only after evolution under all three conditions.",
            "",
            "## Test Results",
            "",
            "| Condition | Mean score | Input tokens | Output tokens |",
            "|---|---:|---:|---:|",
        ]
        for name in ("no_skill", "seed_skill", "evolved_skill"):
            item = conditions[name]
            lines.append(
                f"| {name} | {item['mean_score']:.4f} | "
                f"{item['usage'].get('input_tokens', 0)} | "
                f"{item['usage'].get('output_tokens', 0)} |"
            )
        lines.extend([
            "",
            "## Paired Statistics",
            "",
            "| Comparison | Unique tasks | Delta | 95% CI | p-value | Significant improvement |",
            "|---|---:|---:|---:|---:|---|",
        ])
        for name, item in comparisons.items():
            lines.append(
                f"| {name} | {item['pairs']} | {item['observed_delta']:.4f} | "
                f"[{item['ci_low']:.4f}, {item['ci_high']:.4f}] | "
                f"{item['p_value']:.4f} | {item['significant_improvement']} |"
            )
        lines.extend([
            "",
            "## Evolution",
            "",
            f"- Accepted proposals: {summary['evolution']['accepted']}",
            f"- Rejected proposals: {summary['evolution']['rejected']}",
            f"- Final versions: {summary['evolution']['final_versions']}",
            "",
            "## Interpretation Boundary",
            "",
            "本仓库是受 WikiSkill 启发的独立工程实现。本报告不构成对论文五个 Benchmark、"
            "其他 Baseline 或跨模型迁移结果的复现；少于 10 个唯一 Test task 时也不会标记"
            "统计显著提升。",
            "",
        ])
        return "\n".join(lines)


def _source_state() -> dict[str, object]:
    root = Path(__file__).resolve().parents[1]
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip())
        return {"commit": commit, "dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def _load_prompts() -> dict[str, str]:
    return {
        name: resources.files("skill_learning").joinpath("prompts", name).read_text(
            encoding="utf-8"
        )
        for name in ("executor.md", "maintainer.md", "proposer.md")
    }


def _sum_usage(items) -> dict[str, int]:
    result: dict[str, int] = {}
    for item in items:
        for key, value in item.items():
            result[key] = result.get(key, 0) + int(value)
    return result


def _write_json(path: Path, value: object) -> None:
    _atomic_write(path, json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
