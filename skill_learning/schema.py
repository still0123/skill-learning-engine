from __future__ import annotations

import math
from typing import Any


class SchemaError(ValueError):
    pass


def validate_schema(value: Any, schema: dict[str, Any], path: str = "result") -> None:
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise SchemaError(f"{path} must be an object")
        for key in schema.get("required", []):
            if key not in value:
                raise SchemaError(f"{path}.{key} is required")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            unknown = sorted(set(value) - set(properties))
            if unknown:
                raise SchemaError(f"{path} contains unknown fields: {', '.join(unknown)}")
        for key, child in value.items():
            if key in properties:
                validate_schema(child, properties[key], f"{path}.{key}")
        return
    if expected == "array":
        if not isinstance(value, list):
            raise SchemaError(f"{path} must be an array")
        item_schema = schema.get("items")
        if item_schema:
            for index, item in enumerate(value):
                validate_schema(item, item_schema, f"{path}[{index}]")
        return
    if expected == "string" and not isinstance(value, str):
        raise SchemaError(f"{path} must be a string")
    if expected == "boolean" and not isinstance(value, bool):
        raise SchemaError(f"{path} must be a boolean")
    if expected in {"number", "integer"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SchemaError(f"{path} must be a {expected}")
        if expected == "integer" and not isinstance(value, int):
            raise SchemaError(f"{path} must be an integer")
        if not math.isfinite(float(value)):
            raise SchemaError(f"{path} must be finite")
    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path} must be one of {schema['enum']}")
