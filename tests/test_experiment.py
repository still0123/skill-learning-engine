import json
import tempfile
import unittest
from pathlib import Path

from skill_learning.experiment import ExperimentConfig, ExperimentRunner
from skill_learning.runtime import DemoRuntime


class ExperimentTests(unittest.TestCase):
    def test_repeated_demo_writes_three_condition_report(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "experiment"
            config = ExperimentConfig(
                experiment_id="demo-v2",
                dataset_path=root / "examples" / "normalization" / "tasks.jsonl",
                adapter_name="exact",
                skill_name="normalize",
                skill_path=root / "examples" / "normalization" / "skills" / "normalize" / "SKILL.md",
                iterations=1,
                repeats=2,
                bootstrap_samples=100,
                bootstrap_seed=9,
            )
            summary = ExperimentRunner(
                output_dir=output,
                config=config,
                runtime_factory=DemoRuntime,
            ).run()

            self.assertEqual(summary["conditions"]["no_skill"]["mean_score"], 0.0)
            self.assertEqual(summary["conditions"]["seed_skill"]["mean_score"], 0.0)
            self.assertEqual(summary["conditions"]["evolved_skill"]["mean_score"], 1.0)
            comparison = summary["paired_statistics"]["evolved_vs_seed_skill"]
            self.assertEqual(comparison["observed_delta"], 1.0)
            self.assertFalse(comparison["sufficient_pairs"])
            self.assertFalse(comparison["significant_improvement"])
            self.assertTrue((output / "manifest.json").is_file())
            self.assertTrue((output / "inputs" / "tasks.jsonl").is_file())
            self.assertIn(
                "确定性 Demo Runtime",
                (output / "report.md").read_text(encoding="utf-8"),
            )
            events = output / "repeat-001" / "workspace" / "events" / "evaluations.jsonl"
            phases = [json.loads(line)["phase"] for line in events.read_text().splitlines()]
            self.assertLess(phases.index("validation-candidate"), phases.index("test-no-skill"))
            self.assertEqual(
                phases[-3:],
                ["test-no-skill", "test-seed-skill", "test-evolved-skill"],
            )
            snapshot = output / "inputs" / "prompts"
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(
                set(manifest["inputs"]["prompt_sha256"]),
                {"executor.md", "maintainer.md", "proposer.md"},
            )
            self.assertTrue(all((snapshot / name).is_file() for name in manifest["inputs"]["prompt_sha256"]))

    def test_existing_output_is_not_overwritten(self):
        root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "existing"
            output.mkdir()
            config = ExperimentConfig(
                experiment_id="existing",
                dataset_path=root / "examples" / "normalization" / "tasks.jsonl",
                adapter_name="exact",
                skill_name="normalize",
                skill_path=root / "examples" / "normalization" / "skills" / "normalize" / "SKILL.md",
                repeats=1,
                bootstrap_samples=100,
            )
            with self.assertRaises(FileExistsError):
                ExperimentRunner(
                    output_dir=output,
                    config=config,
                    runtime_factory=DemoRuntime,
                ).run()

    def test_runtime_configuration_cannot_drift_between_repeats(self):
        root = Path(__file__).resolve().parents[1]
        created = 0

        class DriftingRuntime(DemoRuntime):
            def __init__(self, model):
                self.model = model

            def describe(self):
                return {"runtime": "demo", "model": self.model}

        def factory():
            nonlocal created
            created += 1
            return DriftingRuntime(f"demo-{created}")

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "drift"
            config = ExperimentConfig(
                experiment_id="drift",
                dataset_path=root / "examples" / "normalization" / "tasks.jsonl",
                adapter_name="exact",
                skill_name="normalize",
                skill_path=root / "examples" / "normalization" / "skills" / "normalize" / "SKILL.md",
                iterations=1,
                repeats=2,
                bootstrap_samples=100,
            )
            with self.assertRaisesRegex(ValueError, "runtime configuration changed"):
                ExperimentRunner(
                    output_dir=output,
                    config=config,
                    runtime_factory=factory,
                ).run()
            self.assertTrue((output / "repeat-002" / "failure.json").is_file())


if __name__ == "__main__":
    unittest.main()
