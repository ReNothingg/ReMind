from __future__ import annotations

import math
from typing import Any


def argument_errors(value: Any, schema: dict, path: str = "$", depth: int = 0) -> list[str]:
    if depth > 16:
        return [f"{path}: nesting_limit"]
    kind = str(schema.get("type") or "")
    valid = {
        "object": isinstance(value, dict),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": type(value) in (int, float) and (type(value) is int or math.isfinite(value)),
        "boolean": type(value) is bool,
        "null": value is None,
    }.get(kind, False)
    if not valid:
        return [f"{path}: expected_{kind}"]
    if "enum" in schema and value not in schema["enum"]:
        return [f"{path}: invalid_choice"]
    errors: list[str] = []
    if kind == "object":
        properties = schema.get("properties", {})
        errors.extend(
            f"{path}.{key}: required" for key in schema.get("required", []) if key not in value
        )
        for key, item in value.items():
            if key not in properties:
                errors.append(f"{path}: unexpected_property")
            else:
                errors.extend(argument_errors(item, properties[key], f"{path}.{key}", depth + 1))
    elif kind == "array":
        if len(value) > schema.get("maxItems", 100):
            errors.append(f"{path}: too_many_items")
        elif len(value) < schema.get("minItems", 0):
            errors.append(f"{path}: too_few_items")
        else:
            for index, item in enumerate(value):
                errors.extend(
                    argument_errors(item, schema.get("items", {}), f"{path}[{index}]", depth + 1)
                )
    elif kind == "string":
        if len(value) > schema.get("maxLength", 1_000_000):
            errors.append(f"{path}: too_long")
        if len(value) < schema.get("minLength", 0):
            errors.append(f"{path}: too_short")
    elif kind in {"integer", "number"}:
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            errors.append(f"{path}: out_of_range")
    return errors[:8]
