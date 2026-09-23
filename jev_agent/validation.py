from __future__ import annotations

from typing import Any


class SchemaError(ValueError):
    pass


def validate_json_schema(value: Any, schema: dict[str, Any], path: str = "$") -> None:
    """Validate the JSON Schema subset used by the first prototype."""
    expected = schema.get("type")
    if expected == "object":
        if not isinstance(value, dict):
            raise SchemaError(f"{path} must be an object")
        required = schema.get("required", [])
        missing = [key for key in required if key not in value]
        if missing:
            raise SchemaError(f"{path} is missing required fields: {missing}")
        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extras = set(value) - set(properties)
            if extras:
                raise SchemaError(f"{path} has unexpected fields: {sorted(extras)}")
        for name, child in properties.items():
            if name in value:
                validate_json_schema(value[name], child, f"{path}.{name}")
    elif expected == "array":
        if not isinstance(value, list):
            raise SchemaError(f"{path} must be an array")
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise SchemaError(f"{path} has fewer than minItems")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise SchemaError(f"{path} has more than maxItems")
        if "items" in schema:
            for index, item in enumerate(value):
                validate_json_schema(item, schema["items"], f"{path}[{index}]")
    elif expected == "string":
        if not isinstance(value, str):
            raise SchemaError(f"{path} must be a string")
        if len(value) < schema.get("minLength", 0):
            raise SchemaError(f"{path} is shorter than minLength")
        if len(value) > schema.get("maxLength", float("inf")):
            raise SchemaError(f"{path} is longer than maxLength")
    elif expected == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise SchemaError(f"{path} must be an integer")
    elif expected == "number":
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SchemaError(f"{path} must be a number")
    elif expected == "boolean":
        if not isinstance(value, bool):
            raise SchemaError(f"{path} must be a boolean")
    elif expected == "null" and value is not None:
        raise SchemaError(f"{path} must be null")
    elif expected not in {None, "object", "array", "string", "integer", "number", "boolean", "null"}:
        raise SchemaError(f"{path} uses unsupported schema type: {expected}")

    if "enum" in schema and value not in schema["enum"]:
        raise SchemaError(f"{path} is not one of the allowed enum values")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise SchemaError(f"{path} is below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise SchemaError(f"{path} is above maximum")
