from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Task:
    id: str
    split: str
    input: str
    expected: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RuntimeResult:
    payload: dict[str, Any]
    messages: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class Trace:
    id: str
    iteration: int
    phase: str
    split: str
    task_id: str
    skill_name: str
    skill_version: int
    task_input: str
    expected: Any
    answer: str
    score: float
    passed: bool
    messages: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Pattern:
    id: str
    title: str
    observation: str
    strategy: str
    evidence_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_ids"] = list(self.evidence_ids)
        return data


@dataclass(frozen=True)
class SkillProposal:
    skill_name: str
    summary: str
    old_text: str
    new_text: str
    evidence_ids: tuple[str, ...]
    pattern_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence_ids"] = list(self.evidence_ids)
        data["pattern_ids"] = list(self.pattern_ids)
        return data


@dataclass
class Evaluation:
    split: str
    phase: str
    mean_score: float
    traces: list[Trace]


@dataclass
class EvolutionSummary:
    skill_name: str
    initial_version: int
    final_version: int
    initial_validation_score: float
    final_validation_score: float
    final_test_score: float
    accepted: int
    rejected: int
    completed_iterations: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
