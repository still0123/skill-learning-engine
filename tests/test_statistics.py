import unittest

from skill_learning.statistics import paired_bootstrap


class StatisticsTests(unittest.TestCase):
    def test_bootstrap_is_reproducible(self):
        baseline = {f"task-{index}": 0.0 for index in range(12)}
        candidate = {f"task-{index}": 1.0 for index in range(12)}
        first = paired_bootstrap(baseline, candidate, samples=200, seed=7)
        second = paired_bootstrap(baseline, candidate, samples=200, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(first.observed_delta, 1.0)
        self.assertEqual(first.p_value_method, "exact_sign_flip")
        self.assertAlmostEqual(first.p_value, 2 / (2**12))
        self.assertTrue(first.significant_improvement)

    def test_bootstrap_requires_paired_ids(self):
        with self.assertRaises(ValueError):
            paired_bootstrap({"a": 0.0}, {"b": 1.0}, samples=100)

    def test_single_pair_is_not_called_significant(self):
        result = paired_bootstrap({"a": 0.0}, {"a": 1.0}, samples=100)
        self.assertFalse(result.sufficient_pairs)
        self.assertFalse(result.significant_improvement)

    def test_sign_flip_p_value_uses_a_zero_effect_null(self):
        baseline = {f"task-{index}": 0.5 for index in range(12)}
        candidate = {
            f"task-{index}": 1.0 if index < 6 else 0.0
            for index in range(12)
        }
        result = paired_bootstrap(baseline, candidate, samples=200, seed=3)
        self.assertEqual(result.observed_delta, 0.0)
        self.assertEqual(result.p_value, 1.0)
        self.assertFalse(result.significant_improvement)


if __name__ == "__main__":
    unittest.main()
