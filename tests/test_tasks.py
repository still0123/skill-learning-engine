import tempfile
import unittest
from pathlib import Path

from skill_learning.tasks import ExactMatchJSONLAdapter


class TaskAdapterTests(unittest.TestCase):
    def test_requires_all_three_splits(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "tasks.jsonl"
            path.write_text(
                '{"id":"one","split":"train","input":"x","expected":"x"}\n',
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                ExactMatchJSONLAdapter(path)

    def test_example_dataset_loads(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "normalization" / "tasks.jsonl"
        adapter = ExactMatchJSONLAdapter(path)
        self.assertEqual(len(adapter.tasks("train")), 3)
        self.assertEqual(len(adapter.tasks("validation")), 2)
        self.assertEqual(len(adapter.tasks("test")), 2)


if __name__ == "__main__":
    unittest.main()
