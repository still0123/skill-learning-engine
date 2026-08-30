from __future__ import annotations

import math
from dataclasses import dataclass, field

from .models import Evaluation


@dataclass(frozen=True)
class GateDecision:
    accepted: bool
    reason: str
    delta: float = 0.0
    improved_tasks: tuple[str, ...] = ()
    unchanged_tasks: tuple[str, ...] = ()
    regressed_tasks: tuple[str, ...] = ()
    metric_deltas: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "delta": self.delta,
            "improved_tasks": list(self.improved_tasks),
            "unchanged_tasks": list(self.unchanged_tasks),
            "regressed_tasks": list(self.regressed_tasks),
            "metric_deltas": self.metric_deltas,
        }


class EvaluationGate:
    def __init__(
        self,
        epsilon: float = 0.0,
        *,
        min_improved_tasks: int = 1,
        max_regressed_tasks: int | None = None,
    ) -> None:
        if not math.isfinite(epsilon) or epsilon < 0:
            raise ValueError("epsilon must be a finite non-negative number")
        if min_improved_tasks < 0:
            raise ValueError("min_improved_tasks must be non-negative")
        if max_regressed_tasks is not None and max_regressed_tasks < 0:
            raise ValueError("max_regressed_tasks must be non-negative or None")
        self.epsilon = epsilon
        self.min_improved_tasks = min_improved_tasks
        self.max_regressed_tasks = max_regressed_tasks

    def decide(
        self,
        *,
        baseline: Evaluation | float,
        candidate: Evaluation | float,
    ) -> GateDecision:
        if isinstance(baseline, Evaluation) and isinstance(candidate, Evaluation):
            return self._decide_paired(baseline, candidate)
        if isinstance(baseline, Evaluation) or isinstance(candidate, Evaluation):
            return GateDecision(False, "baseline and candidate must use the same evaluation type")
        return self._decide_scores(float(baseline), float(candidate))

    def _decide_scores(self, baseline: float, candidate: float) -> GateDecision:
        if not math.isfinite(baseline) or not math.isfinite(candidate):
            return GateDecision(False, "non-finite validation score")
        threshold = baseline + self.epsilon
        delta = candidate - baseline
        if candidate > threshold:
            return GateDecision(
                True,
                f"candidate {candidate:.4f} strictly exceeds threshold {threshold:.4f}",
                delta=delta,
            )
        return GateDecision(
            False,
            f"candidate {candidate:.4f} does not strictly exceed threshold {threshold:.4f}",
            delta=delta,
        )

    def _decide_paired(self, baseline: Evaluation, candidate: Evaluation) -> GateDecision:
        baseline_scores = baseline.task_scores
        candidate_scores = candidate.task_scores
        if len(baseline_scores) != len(baseline.traces) or len(candidate_scores) != len(candidate.traces):
            return GateDecision(False, "duplicate validation task IDs")
        if set(baseline_scores) != set(candidate_scores):
            missing = sorted(set(baseline_scores) - set(candidate_scores))
            extra = sorted(set(candidate_scores) - set(baseline_scores))
            return GateDecision(
                False,
                f"validation task IDs do not align; missing={missing}, extra={extra}",
            )

        improved: list[str] = []
        unchanged: list[str] = []
        regressed: list[str] = []
        for task_id in sorted(baseline_scores):
            delta = candidate_scores[task_id] - baseline_scores[task_id]
            if delta > 0:
                improved.append(task_id)
            elif delta < 0:
                regressed.append(task_id)
            else:
                unchanged.append(task_id)

        metric_deltas = {
            name: candidate.metrics[name] - baseline.metrics[name]
            for name in sorted(set(baseline.metrics) & set(candidate.metrics))
        }
        score_decision = self._decide_scores(baseline.mean_score, candidate.mean_score)
        common = {
            "delta": score_decision.delta,
            "improved_tasks": tuple(improved),
            "unchanged_tasks": tuple(unchanged),
            "regressed_tasks": tuple(regressed),
            "metric_deltas": metric_deltas,
        }
        if not score_decision.accepted:
            return GateDecision(False, score_decision.reason, **common)
        if len(improved) < self.min_improved_tasks:
            return GateDecision(
                False,
                f"improved {len(improved)} tasks, fewer than required {self.min_improved_tasks}",
                **common,
            )
        if self.max_regressed_tasks is not None and len(regressed) > self.max_regressed_tasks:
            return GateDecision(
                False,
                f"regressed {len(regressed)} tasks, exceeding allowed {self.max_regressed_tasks}",
                **common,
            )
        return GateDecision(True, score_decision.reason, **common)
