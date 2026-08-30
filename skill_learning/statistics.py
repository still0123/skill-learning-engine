from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class BootstrapResult:
    pairs: int
    samples: int
    seed: int
    observed_delta: float
    ci_low: float
    ci_high: float
    p_value: float
    p_value_method: str
    sufficient_pairs: bool
    significant_improvement: bool

    def to_dict(self) -> dict:
        return asdict(self)


def paired_bootstrap(
    baseline: dict[str, float],
    candidate: dict[str, float],
    *,
    samples: int = 1_000,
    seed: int = 0,
    min_pairs_for_significance: int = 10,
) -> BootstrapResult:
    if samples < 100:
        raise ValueError("bootstrap samples must be at least 100")
    if set(baseline) != set(candidate):
        raise ValueError("paired bootstrap requires identical sample IDs")
    if not baseline:
        raise ValueError("paired bootstrap requires at least one pair")
    if min_pairs_for_significance < 2:
        raise ValueError("min_pairs_for_significance must be at least 2")
    sample_ids = sorted(baseline)
    differences = [float(candidate[key]) - float(baseline[key]) for key in sample_ids]
    if any(not math.isfinite(value) for value in differences):
        raise ValueError("paired scores must be finite")

    observed = sum(differences) / len(differences)
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(samples):
        draw = [differences[rng.randrange(len(differences))] for _ in differences]
        means.append(sum(draw) / len(draw))
    means.sort()
    ci_low = _percentile(means, 0.025)
    ci_high = _percentile(means, 0.975)
    p_value, p_value_method = _sign_flip_p_value(
        differences,
        samples=samples,
        seed=seed,
    )
    sufficient_pairs = len(differences) >= min_pairs_for_significance
    significant = sufficient_pairs and observed > 0 and ci_low > 0 and p_value < 0.05
    return BootstrapResult(
        pairs=len(differences),
        samples=samples,
        seed=seed,
        observed_delta=observed,
        ci_low=ci_low,
        ci_high=ci_high,
        p_value=p_value,
        p_value_method=p_value_method,
        sufficient_pairs=sufficient_pairs,
        significant_improvement=significant,
    )


def _sign_flip_p_value(
    differences: list[float],
    *,
    samples: int,
    seed: int,
    exact_limit: int = 16,
) -> tuple[float, str]:
    """Two-sided paired randomization test under a symmetric zero-effect null."""

    observed = abs(sum(differences) / len(differences))
    tolerance = 1e-12
    if len(differences) <= exact_limit:
        total = 1 << len(differences)
        extreme = 0
        for mask in range(total):
            randomized = sum(
                value if mask & (1 << index) else -value
                for index, value in enumerate(differences)
            ) / len(differences)
            if abs(randomized) + tolerance >= observed:
                extreme += 1
        return extreme / total, "exact_sign_flip"

    rng = random.Random(seed ^ 0x5EED5EED)
    extreme = 0
    for _ in range(samples):
        randomized = sum(
            value if rng.randrange(2) else -value
            for value in differences
        ) / len(differences)
        if abs(randomized) + tolerance >= observed:
            extreme += 1
    return (extreme + 1) / (samples + 1), "monte_carlo_sign_flip"


def _percentile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("cannot calculate percentile of empty values")
    position = (len(values) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return values[lower]
    weight = position - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight
