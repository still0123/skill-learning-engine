from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class GateDecision:
    accepted: bool
    reason: str


class EvaluationGate:
    def __init__(self, epsilon: float = 0.0) -> None:
        if not math.isfinite(epsilon) or epsilon < 0:
            raise ValueError("epsilon must be a finite non-negative number")
        self.epsilon = epsilon

    def decide(self, *, baseline: float, candidate: float) -> GateDecision:
        if not math.isfinite(baseline) or not math.isfinite(candidate):
            return GateDecision(False, "non-finite validation score")
        threshold = baseline + self.epsilon
        if candidate > threshold:
            return GateDecision(
                True,
                f"candidate {candidate:.4f} strictly exceeds threshold {threshold:.4f}",
            )
        return GateDecision(
            False,
            f"candidate {candidate:.4f} does not strictly exceed threshold {threshold:.4f}",
        )
