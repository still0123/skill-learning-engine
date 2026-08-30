from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .models import Pattern, SkillProposal, Trace


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
        self.save_state({
            "skill_name": skill_name,
            "version": 0,
            "iteration": 0,
            "best_validation_score": None,
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
