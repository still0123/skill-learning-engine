import json
import tempfile
import unittest
from pathlib import Path

from skill_learning.evolution import EvolutionEngine
from skill_learning.models import RuntimeResult
from skill_learning.runtime import DemoRuntime
from skill_learning.schema import validate_schema
from skill_learning.tasks import ExactMatchJSONLAdapter
from skill_learning.workspace import Workspace


INITIAL_SKILL = """# Normalize Text

## Procedure

Return the input unchanged.
"""


def example_adapter():
    path = Path(__file__).resolve().parents[1] / "examples" / "normalization" / "tasks.jsonl"
    return ExactMatchJSONLAdapter(path)


class NoImproveRuntime(DemoRuntime):
    def run(self, **kwargs):
        if kwargs["role"] != "task-executor":
            return super().run(**kwargs)
        request = json.loads(kwargs["user_prompt"])
        payload = {"answer": request["task"]["input"]}
        validate_schema(payload, kwargs["result_schema"])
        return RuntimeResult(payload=payload)


class EvolutionTests(unittest.TestCase):
    def test_demo_accepts_improving_skill(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(temp)
            workspace.initialize(skill_name="normalize", skill_text=INITIAL_SKILL)
            summary = EvolutionEngine(
                workspace=workspace,
                runtime=DemoRuntime(),
                adapter=example_adapter(),
            ).run(iterations=1)

            self.assertEqual(summary.initial_validation_score, 0.0)
            self.assertEqual(summary.final_validation_score, 1.0)
            self.assertEqual(summary.final_test_score, 1.0)
            self.assertEqual(summary.accepted, 1)
            self.assertEqual(summary.final_version, 1)
            self.assertIn("lowercase, trimmed", workspace.read_skill("normalize"))
            self.assertTrue((Path(temp) / "versions" / "normalize" / "v000" / "SKILL.md").is_file())
            proposer_view = Path(temp) / ".views" / "proposer" / "iteration-000"
            visible_paths = {path.relative_to(proposer_view).as_posix() for path in proposer_view.rglob("*")}
            self.assertIn("traces/train-001.json", visible_paths)
            self.assertFalse(any("validation" in path or "test" in path for path in visible_paths))
            impacts = (Path(temp) / "events" / "skill-impact.jsonl").read_text(encoding="utf-8")
            self.assertIn('"diff": "--- skills/normalize/SKILL.md', impacts)

    def test_rejected_candidate_does_not_change_active_skill_but_keeps_wiki(self):
        with tempfile.TemporaryDirectory() as temp:
            workspace = Workspace(temp)
            workspace.initialize(skill_name="normalize", skill_text=INITIAL_SKILL)
            summary = EvolutionEngine(
                workspace=workspace,
                runtime=NoImproveRuntime(),
                adapter=example_adapter(),
            ).run(iterations=1)

            self.assertEqual(summary.rejected, 1)
            self.assertEqual(summary.final_version, 0)
            self.assertEqual(workspace.read_skill("normalize"), INITIAL_SKILL)
            self.assertTrue((Path(temp) / "wiki" / "patterns" / "normalize-case-and-space.md").is_file())
            impact = workspace.read_impact_log()
            self.assertIn("rejected", impact)


if __name__ == "__main__":
    unittest.main()
