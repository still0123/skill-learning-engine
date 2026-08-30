import unittest

from skill_learning.gate import EvaluationGate
from skill_learning.models import Evaluation, Trace


def evaluation(phase, scores):
    return Evaluation(
        split="validation",
        phase=phase,
        mean_score=sum(scores.values()) / len(scores),
        traces=[
            Trace(
                id=f"{phase}-{task_id}",
                iteration=0,
                phase=phase,
                split="validation",
                task_id=task_id,
                skill_name="skill",
                skill_version=0,
                task_input="",
                expected="",
                answer="",
                score=score,
                passed=score == 1.0,
                metrics={"exact_match": score},
            )
            for task_id, score in scores.items()
        ],
    )


class GateTests(unittest.TestCase):
    def test_requires_strict_improvement(self):
        gate = EvaluationGate()
        self.assertTrue(gate.decide(baseline=0.5, candidate=0.6).accepted)
        self.assertFalse(gate.decide(baseline=0.5, candidate=0.5).accepted)
        self.assertFalse(gate.decide(baseline=0.5, candidate=0.4).accepted)

    def test_epsilon_is_applied(self):
        gate = EvaluationGate(epsilon=0.1)
        self.assertFalse(gate.decide(baseline=0.5, candidate=0.6).accepted)
        self.assertTrue(gate.decide(baseline=0.5, candidate=0.61).accepted)

    def test_paired_gate_reports_improvements_and_regressions(self):
        decision = EvaluationGate().decide(
            baseline=evaluation("baseline", {"a": 0.0, "b": 1.0, "c": 0.0}),
            candidate=evaluation("candidate", {"a": 1.0, "b": 0.0, "c": 1.0}),
        )
        self.assertTrue(decision.accepted)
        self.assertEqual(decision.improved_tasks, ("a", "c"))
        self.assertEqual(decision.regressed_tasks, ("b",))

    def test_paired_gate_can_reject_regressions(self):
        decision = EvaluationGate(max_regressed_tasks=0).decide(
            baseline=evaluation("baseline", {"a": 0.0, "b": 0.5}),
            candidate=evaluation("candidate", {"a": 1.0, "b": 0.0}),
        )
        self.assertFalse(decision.accepted)
        self.assertIn("regressed 1 tasks", decision.reason)

    def test_paired_gate_fails_closed_on_task_mismatch(self):
        decision = EvaluationGate().decide(
            baseline=evaluation("baseline", {"a": 0.0}),
            candidate=evaluation("candidate", {"b": 1.0}),
        )
        self.assertFalse(decision.accepted)
        self.assertIn("do not align", decision.reason)


if __name__ == "__main__":
    unittest.main()
