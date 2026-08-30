import json
import tempfile
import unittest
from pathlib import Path

from skill_learning.components import TaskExecutor
from skill_learning.models import RuntimeResult
from skill_learning.tasks import ExactMatchJSONLAdapter


class CapturingRuntime:
    def __init__(self):
        self.requests = []

    def describe(self):
        return {"runtime": "capture", "model": "capture-model"}

    def run(self, **kwargs):
        self.requests.append(kwargs)
        request = json.loads(kwargs["user_prompt"])
        return RuntimeResult(payload={"answer": request["task"]["input"]})


class ComponentTests(unittest.TestCase):
    def test_executor_hides_label_metadata_and_file_tools(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tasks.jsonl"
            lines = [
                {
                    "id": f"{split}-1",
                    "split": split,
                    "input": "ok",
                    "expected": "ok",
                    "metadata": {
                        "category": "safe",
                        "label": "secret-label",
                        "ground_truth": "secret-answer",
                        "_private": "secret",
                    },
                }
                for split in ("train", "validation", "test")
            ]
            path.write_text(
                "".join(json.dumps(item) + "\n" for item in lines),
                encoding="utf-8",
            )
            runtime = CapturingRuntime()
            adapter = ExactMatchJSONLAdapter(path)
            TaskExecutor(runtime, adapter).evaluate(
                tasks=adapter.tasks("test"),
                skill_name="safe-skill",
                skill_version=0,
                skill_text="Use the task only.",
                iteration=0,
                phase="test-final",
                workdir=Path(temp),
            )

            call = runtime.requests[0]
            request = json.loads(call["user_prompt"])
            self.assertEqual(request["task"]["metadata"], {"category": "safe"})
            self.assertEqual(call["policy"].allowed_tools, ("submit_result",))

    def test_executor_omits_skill_identity_for_no_skill_baseline(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tasks.jsonl"
            path.write_text(
                "".join(
                    json.dumps(
                        {
                            "id": f"{split}-1",
                            "split": split,
                            "input": "ok",
                            "expected": "ok",
                        }
                    )
                    + "\n"
                    for split in ("train", "validation", "test")
                ),
                encoding="utf-8",
            )
            runtime = CapturingRuntime()
            adapter = ExactMatchJSONLAdapter(path)

            TaskExecutor(runtime, adapter).evaluate(
                tasks=adapter.tasks("test"),
                skill_name="no-skill",
                skill_version=-1,
                skill_text="",
                iteration=0,
                phase="test-no-skill",
                workdir=Path(temp),
            )

            request = json.loads(runtime.requests[0]["user_prompt"])
            self.assertIsNone(request["skill_name"])
            self.assertIsNone(request["skill_version"])
            self.assertIsNone(request["skill"])


if __name__ == "__main__":
    unittest.main()
