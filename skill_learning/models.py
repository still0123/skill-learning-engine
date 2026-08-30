from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
from typing import Any


@dataclass(frozen=True)
class Task:
    id: str
    split: str
    input: str
    expected: Any
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Score:
    value: float
    metrics: dict[str, float] = field(default_factory=dict)
    feedback: str = ""

    def __post_init__(self) -> None:
        _unit_interval(self.value, "score")
        for name, value in self.metrics.items():
            if not name.strip():
                raise ValueError("metric name must not be empty")
            _unit_interval(value, f"metric {name!r}")


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
    metrics: dict[str, float] = field(default_factory=dict)
    feedback: str = ""
    model_id: str = "unknown"
    duration_ms: int = 0
    prompt_sha256: str = ""
    skill_sha256: str = ""
    messages: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Trace":
        return cls(**data)


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

    @property
    def task_scores(self) -> dict[str, float]:
        return {trace.task_id: trace.score for trace in self.traces}

    @property
    def metrics(self) -> dict[str, float]:
        names = sorted({name for trace in self.traces for name in trace.metrics})
        return {
            name: sum(trace.metrics.get(name, 0.0) for trace in self.traces) / len(self.traces)
            for name in names
        }

    @property
    def usage(self) -> dict[str, int]:
        keys = {key for trace in self.traces for key in trace.usage}
        return {key: sum(int(trace.usage.get(key, 0)) for trace in self.traces) for key in keys}

    def to_dict(self) -> dict[str, Any]:
        return {
            "split": self.split,
            "phase": self.phase,
            "mean_score": self.mean_score,
            "metrics": self.metrics,
            "usage": self.usage,
            "traces": [trace.to_dict() for trace in self.traces],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evaluation":
        return cls(
            split=data["split"],
            phase=data["phase"],
            mean_score=float(data["mean_score"]),
            traces=[Trace.from_dict(item) for item in data["traces"]],
        )


@dataclass
class EvolutionSummary:
    skill_name: str
    initial_version: int
    final_version: int
    initial_validation_score: float
    final_validation_score: float
    final_test_score: float | None
    accepted: int
    rejected: int
    completed_iterations: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _unit_interval(value: float, label: str) -> None:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    if not math.isfinite(float(value)) or not 0.0 <= float(value) <= 1.0:
        raise ValueError(f"{label} must be a finite number in [0, 1]")
