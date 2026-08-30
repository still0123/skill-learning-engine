import tempfile
import unittest
from pathlib import Path

from skill_learning.agentloop_runtime import AgentLoopRuntime
from skill_learning.runtime import RuntimePolicy


class AgentLoopRuntimeTests(unittest.TestCase):
    def test_submit_result_contract(self):
        try:
            from agentloop.models import MockClient
        except ImportError:
            self.skipTest("AgentLoop source is not on PYTHONPATH")

        client = MockClient([
            [("submit_result", {"answer": "ok"})],
            "done",
        ])
        with tempfile.TemporaryDirectory() as temp:
            result = AgentLoopRuntime(client).run(
                role="test",
                system_prompt="Submit an answer.",
                user_prompt="Return ok.",
                result_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
                workdir=Path(temp),
            )
        self.assertEqual(result.payload, {"answer": "ok"})
        self.assertEqual(result.usage, {"input_tokens": 20, "output_tokens": 10})

    def test_executor_policy_exposes_only_submit_result(self):
        try:
            from agentloop.models import ModelResponse
        except ImportError:
            self.skipTest("AgentLoop source is not on PYTHONPATH")

        class RecordingClient:
            model = "recording-model"

            def __init__(self):
                self.calls = 0
                self.tool_names = []

            def complete(self, system, messages, tools):
                self.tool_names.append([item["name"] for item in tools])
                self.calls += 1
                if self.calls == 1:
                    return ModelResponse(blocks=[{
                        "type": "tool_use",
                        "id": "submit-1",
                        "name": "submit_result",
                        "input": {"answer": "ok"},
                    }])
                return ModelResponse(text="done", blocks=[{"type": "text", "text": "done"}])

        client = RecordingClient()
        with tempfile.TemporaryDirectory() as temp:
            AgentLoopRuntime(client).run(
                role="task-executor",
                system_prompt="Submit.",
                user_prompt="Return ok.",
                result_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
                workdir=Path(temp),
                policy=RuntimePolicy(),
            )
        self.assertEqual(client.tool_names, [["submit_result"], ["submit_result"]])

    def test_proposer_must_read_required_train_traces(self):
        try:
            from agentloop.models import MockClient
        except ImportError:
            self.skipTest("AgentLoop source is not on PYTHONPATH")

        client = MockClient([
            [("submit_result", {"answer": "too-early"})],
            [
                ("read_file", {"path": f"traces/task-{index}.json"})
                for index in range(4)
            ] + [("submit_result", {"answer": "ready"})],
            "done",
        ])
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "traces").mkdir()
            for index in range(4):
                (root / "traces" / f"task-{index}.json").write_text("{}", encoding="utf-8")
            result = AgentLoopRuntime(client).run(
                role="skill-proposer",
                system_prompt="Read traces then submit.",
                user_prompt="Inspect evidence.",
                result_schema={
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                    "required": ["answer"],
                },
                workdir=root,
                policy=RuntimePolicy(
                    allowed_tools=("read_file", "glob", "submit_result"),
                    required_read_prefix="traces",
                    min_required_reads=4,
                ),
            )
        self.assertEqual(result.payload, {"answer": "ready"})


if __name__ == "__main__":
    unittest.main()
