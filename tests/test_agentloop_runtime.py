import tempfile
import unittest
from pathlib import Path

from skill_learning.agentloop_runtime import AgentLoopRuntime


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


if __name__ == "__main__":
    unittest.main()
