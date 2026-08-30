from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .models import Evaluation, Pattern, SkillProposal, Trace


_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _component(value: str, label: str) -> str:
    if not _COMPONENT.fullmatch(value) or value in {".", ".."}:
        raise ValueError(f"invalid {label}: {value!r}")
    return value


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
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


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2) + "\n"


class Workspace:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()

    @property
    def state_path(self) -> Path:
        return self.root / "state.json"

    def initialize(self, *, skill_name: str, skill_text: str, purpose: str = "") -> None:
        if self.state_path.exists():
            raise FileExistsError(f"workspace already initialized: {self.root}")
        if not _SLUG.fullmatch(skill_name):
            raise ValueError("skill name must be a lowercase slug")
        if not skill_text.strip():
            raise ValueError("initial Skill must not be empty")
        for path in (
            self.root / "raw",
            self.root / "wiki" / "patterns",
            self.root / "skills" / skill_name,
            self.root / "candidates",
            self.root / "versions" / skill_name,
            self.root / "events",
            self.root / ".views" / "proposer",
        ):
            path.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.root / "skills" / skill_name / "SKILL.md", skill_text.rstrip() + "\n")
        _atomic_write(
            self.root / "skills" / skill_name / "PURPOSE.md",
            purpose.rstrip() + "\n" if purpose.strip() else "# Purpose\n\nInitial Skill version.\n",
        )
        _atomic_write(self.root / "wiki" / "index.md", "# Pattern Index\n\nNo patterns yet.\n")
        _atomic_write(self.root / "wiki" / "logs.md", "# Evolution Log\n")
        _atomic_write(
            self.root / "wiki" / "skill-impact.md",
            "# Skill Impact Log\n\n"
            "| Iteration | Skill | Decision | Baseline | Candidate | Summary | Reason |\n"
            "|---:|---|---|---:|---:|---|---|\n",
        )
        _atomic_write(self.root / "events" / "evaluations.jsonl", "")
        _atomic_write(self.root / "events" / "patterns.jsonl", "")
        _atomic_write(self.root / "events" / "skill-impact.jsonl", "")
        self.save_state({
            "skill_name": skill_name,
            "version": 0,
            "iteration": 0,
            "best_validation_score": None,
            "best_validation_iteration": None,
            "best_validation_phase": None,
        })

    def load_state(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            raise FileNotFoundError(f"workspace is not initialized: {self.root}")
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        for key in ("skill_name", "version", "iteration", "best_validation_score"):
            if key not in state:
                raise ValueError(f"state.json is missing {key}")
        return state

    def save_state(self, state: dict[str, Any]) -> None:
        _atomic_write(self.state_path, _json(state))

    def skill_dir(self, skill_name: str) -> Path:
        return self.root / "skills" / _component(skill_name, "skill name")

    def read_skill(self, skill_name: str) -> str:
        return (self.skill_dir(skill_name) / "SKILL.md").read_text(encoding="utf-8")

    def read_wiki_index(self) -> str:
        return (self.root / "wiki" / "index.md").read_text(encoding="utf-8")

    def read_impact_log(self) -> str:
        return (self.root / "wiki" / "skill-impact.md").read_text(encoding="utf-8")

    def write_traces(self, traces: list[Trace]) -> None:
        for trace in traces:
            phase = _component(trace.phase, "trace phase")
            task_id = _component(trace.task_id, "task id")
            path = self.root / "raw" / f"iteration-{trace.iteration:03d}" / phase / f"{task_id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            try:
                with path.open("x", encoding="utf-8") as handle:
                    handle.write(_json(trace.to_dict()))
            except FileExistsError as exc:
                raise FileExistsError(f"immutable trace already exists: {path}") from exc

    def record_evaluation(self, evaluation: Evaluation) -> None:
        self.write_traces(evaluation.traces)
        first = evaluation.traces[0]
        event = {
            "iteration": first.iteration,
            "phase": evaluation.phase,
            "split": evaluation.split,
            "skill_name": first.skill_name,
            "skill_version": first.skill_version,
            "skill_sha256": first.skill_sha256,
            "model_id": first.model_id,
            "mean_score": evaluation.mean_score,
            "metrics": evaluation.metrics,
            "usage": evaluation.usage,
            "duration_ms": sum(trace.duration_ms for trace in evaluation.traces),
            "tasks": [
                {
                    "task_id": trace.task_id,
                    "trace_id": trace.id,
                    "score": trace.score,
                    "metrics": trace.metrics,
                    "passed": trace.passed,
                }
                for trace in evaluation.traces
            ],
        }
        self._append_event("evaluations.jsonl", event)

    def load_evaluation(self, *, iteration: int, phase: str) -> Evaluation:
        trace_dir = self.root / "raw" / f"iteration-{iteration:03d}" / _component(phase, "phase")
        paths = sorted(trace_dir.glob("*.json"))
        if not paths:
            raise FileNotFoundError(f"evaluation traces not found: {trace_dir}")
        traces = [
            Trace.from_dict(json.loads(path.read_text(encoding="utf-8")))
            for path in paths
        ]
        mean_score = sum(trace.score for trace in traces) / len(traces)
        return Evaluation(
            split=traces[0].split,
            phase=phase,
            mean_score=mean_score,
            traces=traces,
        )

    def update_patterns(self, *, iteration: int, patterns: list[Pattern]) -> None:
        pattern_dir = self.root / "wiki" / "patterns"
        for pattern in patterns:
            if not _SLUG.fullmatch(pattern.id):
                raise ValueError(f"invalid pattern id {pattern.id!r}")
            body = (
                f"# {pattern.title}\n\n"
                f"- ID: `{pattern.id}`\n"
                f"- Evidence: {', '.join(f'`{value}`' for value in pattern.evidence_ids)}\n\n"
                f"## Observation\n\n{pattern.observation}\n\n"
                f"## Strategy\n\n{pattern.strategy}\n"
            )
            _atomic_write(pattern_dir / f"{pattern.id}.md", body)
        entries: list[str] = []
        for path in sorted(pattern_dir.glob("*.md")):
            lines = path.read_text(encoding="utf-8").splitlines()
            title = lines[0].removeprefix("# ") if lines else path.stem
            entries.append(f"- [{title}](patterns/{path.name}) (`{path.stem}`)")
        index = "# Pattern Index\n\n" + ("\n".join(entries) if entries else "No patterns yet.") + "\n"
        _atomic_write(self.root / "wiki" / "index.md", index)
        self.append_log(
            f"\n## Iteration {iteration}\n\nUpdated patterns: "
            + (", ".join(f"`{pattern.id}`" for pattern in patterns) if patterns else "none")
            + ".\n"
        )
        self._append_event(
            "patterns.jsonl",
            {
                "iteration": iteration,
                "patterns": [pattern.to_dict() for pattern in patterns],
            },
        )

    def append_log(self, text: str) -> None:
        path = self.root / "wiki" / "logs.md"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    def build_candidate(self, *, iteration: int, proposal: SkillProposal) -> Path:
        source = self.skill_dir(proposal.skill_name)
        target = self.root / "candidates" / f"iteration-{iteration:03d}" / proposal.skill_name
        if target.exists():
            raise FileExistsError(f"candidate already exists: {target}")
        shutil.copytree(source, target)
        skill_path = target / "SKILL.md"
        current = skill_path.read_text(encoding="utf-8")
        occurrences = current.count(proposal.old_text)
        if occurrences != 1:
            raise ValueError(
                f"proposal old_text must occur exactly once in SKILL.md, found {occurrences}"
            )
        updated = current.replace(proposal.old_text, proposal.new_text, 1)
        _atomic_write(skill_path, updated)
        purpose_path = target / "PURPOSE.md"
        purpose = purpose_path.read_text(encoding="utf-8") if purpose_path.exists() else "# Purpose\n"
        purpose += (
            f"\n## Iteration {iteration}\n\n"
            f"{proposal.summary}\n\n"
            f"Patterns: {', '.join(proposal.pattern_ids)}\n"
            f"Evidence: {', '.join(proposal.evidence_ids)}\n"
        )
        _atomic_write(purpose_path, purpose)
        return target

    def prepare_proposer_view(
        self,
        *,
        iteration: int,
        skill_name: str,
        traces: list[Trace],
    ) -> Path:
        target = self.root / ".views" / "proposer" / f"iteration-{iteration:03d}"
        if target.exists():
            raise FileExistsError(f"proposer view already exists: {target}")
        (target / "traces").mkdir(parents=True)
        shutil.copytree(self.root / "wiki", target / "wiki")
        shutil.copytree(self.skill_dir(skill_name), target / "skill")
        for trace in traces:
            if trace.split != "train" or trace.phase != "train":
                raise ValueError("proposer view accepts only current Train traces")
            _atomic_write(target / "traces" / f"{_component(trace.task_id, 'task id')}.json", _json(trace.to_dict()))
        return target

    def promote(self, *, candidate_dir: Path, skill_name: str, current_version: int) -> int:
        active = self.skill_dir(skill_name)
        snapshot = self.root / "versions" / skill_name / f"v{current_version:03d}"
        if snapshot.exists():
            raise FileExistsError(f"version snapshot already exists: {snapshot}")
        shutil.copytree(active, snapshot)
        for name in ("SKILL.md", "PURPOSE.md"):
            source = candidate_dir / name
            if not source.is_file():
                raise FileNotFoundError(f"candidate is missing {name}")
            _atomic_write(active / name, source.read_text(encoding="utf-8"))
        return current_version + 1

    def record_impact(
        self,
        *,
        iteration: int,
        skill_name: str,
        decision: str,
        baseline: float | None,
        candidate: float | None,
        summary: str,
        reason: str,
        proposal: SkillProposal | None = None,
        diff: str = "",
        version_before: int | None = None,
        version_after: int | None = None,
        comparison: dict[str, Any] | None = None,
    ) -> None:
        def clean(value: str) -> str:
            return value.replace("|", "\\|").replace("\n", " ").strip()

        baseline_text = "unknown" if baseline is None else f"{baseline:.4f}"
        candidate_text = "unknown" if candidate is None else f"{candidate:.4f}"
        row = (
            f"| {iteration} | {clean(skill_name)} | {clean(decision)} | "
            f"{baseline_text} | {candidate_text} | {clean(summary)} | {clean(reason)} |\n"
        )
        with (self.root / "wiki" / "skill-impact.md").open("a", encoding="utf-8") as handle:
            handle.write(row)
        self._append_event(
            "skill-impact.jsonl",
            {
                "iteration": iteration,
                "skill_name": skill_name,
                "decision": decision,
                "baseline": baseline,
                "candidate": candidate,
                "summary": summary,
                "reason": reason,
                "proposal": proposal.to_dict() if proposal else None,
                "diff": diff,
                "version_before": version_before,
                "version_after": version_after,
                "comparison": comparison or {},
            },
        )

    def _append_event(self, name: str, event: dict[str, Any]) -> None:
        path = self.root / "events" / _component(name, "event file")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
