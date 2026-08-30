import json
import tempfile
import unittest
from pathlib import Path

from skill_learning.tasks import ExactMatchJSONLAdapter, JSONValueJSONLAdapter


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

    def test_json_adapter_accepts_semantic_json_and_answer_wrappers(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "record_ops" / "tasks.jsonl"
        adapter = JSONValueJSONLAdapter(path)
        task = adapter.tasks("train")[0]
        answer = "<answer>\n```json\n" + json.dumps(task.expected) + "\n```\n</answer>"
        score = adapter.score(task, answer)
        self.assertEqual(score.value, 1.0)
        self.assertEqual(score.metrics, {"valid_json": 1.0, "exact_match": 1.0})

    def test_json_adapter_separates_invalid_json_and_wrong_value(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "record_ops" / "tasks.jsonl"
        adapter = JSONValueJSONLAdapter(path)
        task = adapter.tasks("train")[0]
        invalid = adapter.score(task, "not-json")
        wrong = adapter.score(task, "[]")
        self.assertEqual(invalid.metrics["valid_json"], 0.0)
        self.assertEqual(wrong.metrics["valid_json"], 1.0)
        self.assertEqual(wrong.value, 0.0)

    def test_record_ops_split_counts_and_expected_values(self):
        path = Path(__file__).resolve().parents[1] / "examples" / "record_ops" / "tasks.jsonl"
        adapter = JSONValueJSONLAdapter(path)
        self.assertEqual(
            {split: len(adapter.tasks(split)) for split in ("train", "validation", "test")},
            {"train": 10, "validation": 6, "test": 12},
        )
        for split in ("train", "validation", "test"):
            for task in adapter.tasks(split):
                self.assertEqual(adapter.score(task, json.dumps(task.expected)).value, 1.0)


if __name__ == "__main__":
    unittest.main()
