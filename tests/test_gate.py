import unittest

from skill_learning.gate import EvaluationGate


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


if __name__ == "__main__":
    unittest.main()
