import unittest

from skill_learning.schema import SchemaError, validate_schema


class SchemaTests(unittest.TestCase):
    def test_nested_schema_accepts_valid_payload(self):
        validate_schema(
            {"items": [{"id": "one"}]},
            {
                "type": "object",
                "properties": {
                    "items": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"id": {"type": "string"}},
                            "required": ["id"],
                        },
                    }
                },
                "required": ["items"],
            },
        )

    def test_missing_required_field_fails_closed(self):
        with self.assertRaises(SchemaError):
            validate_schema({}, {"type": "object", "required": ["answer"]})

    def test_non_finite_number_is_rejected(self):
        with self.assertRaises(SchemaError):
            validate_schema(float("nan"), {"type": "number"})

    def test_unknown_field_is_rejected_by_strict_object(self):
        schema = {
            "type": "object",
            "properties": {"answer": {"type": "string"}},
            "required": ["answer"],
            "additionalProperties": False,
        }
        with self.assertRaises(SchemaError):
            validate_schema({"answer": "ok", "debug": "leak"}, schema)


if __name__ == "__main__":
    unittest.main()
