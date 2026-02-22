#!/usr/bin/env python3
"""Generate TypeScript OpenAPI types for the frontend client."""

import argparse
import json
import pathlib
import sys
from typing import Any, Dict, List, Tuple


def ref_to_ts(ref: str) -> str:
    prefix = "#/components/schemas/"
    if ref.startswith(prefix):
        name = ref[len(prefix):]
        return f'components["schemas"]["{name}"]'
    return "unknown"


def indent(level: int) -> str:
    return "  " * level


def union_types(parts: List[str]) -> str:
    ordered: List[str] = []
    for part in parts:
        if part not in ordered:
            ordered.append(part)
    if not ordered:
        return "unknown"
    if len(ordered) == 1:
        return ordered[0]
    return " | ".join(ordered)


def schema_to_ts(schema: Dict[str, Any], level: int = 0) -> str:
    if not schema:
        return "unknown"

    if "$ref" in schema:
        return ref_to_ts(schema["$ref"])

    if "oneOf" in schema:
        return union_types([schema_to_ts(item, level) for item in schema["oneOf"]])

    if "anyOf" in schema:
        return union_types([schema_to_ts(item, level) for item in schema["anyOf"]])

    if "allOf" in schema:
        return union_types([schema_to_ts(item, level) for item in schema["allOf"]])

    enum_values = schema.get("enum")
    if enum_values:
        return union_types([json.dumps(value) for value in enum_values])

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        mapped = [schema_to_ts({**schema, "type": value}, level) for value in schema_type]
        return union_types(mapped)

    if schema_type == "string":
        return "string"
    if schema_type == "integer" or schema_type == "number":
        return "number"
    if schema_type == "boolean":
        return "boolean"
    if schema_type == "null":
        return "null"
    if schema_type == "array":
        item_type = schema_to_ts(schema.get("items") or {}, level)
        if " | " in item_type:
            item_type = f"({item_type})"
        return f"{item_type}[]"

    if schema_type == "object" or "properties" in schema or "additionalProperties" in schema:
        properties = schema.get("properties") or {}
        required = set(schema.get("required") or [])
        addl = schema.get("additionalProperties", None)

        if not properties and addl is True:
            return "Record<string, unknown>"
        if not properties and isinstance(addl, dict):
            return f"Record<string, {schema_to_ts(addl, level + 1)}>"
        if not properties and addl is None:
            return "Record<string, unknown>"

        lines = ["{"]
        for key in sorted(properties.keys()):
            prop = properties[key]
            optional = "" if key in required else "?"
            prop_type = schema_to_ts(prop, level + 1)
            lines.append(f"{indent(level + 1)}{key}{optional}: {prop_type};")

        if addl is True:
            lines.append(f"{indent(level + 1)}[key: string]: unknown;")
        elif isinstance(addl, dict):
            addl_type = schema_to_ts(addl, level + 1)
            lines.append(f"{indent(level + 1)}[key: string]: {addl_type};")

        lines.append(f"{indent(level)}}}")
        return "\n".join(lines)

    return "unknown"


def collect_parameters(path_item: Dict[str, Any], method_item: Dict[str, Any]) -> Dict[str, Dict[str, Tuple[Dict[str, Any], bool]]]:
    grouped: Dict[str, Dict[str, Tuple[Dict[str, Any], bool]]] = {
        "query": {},
        "path": {},
        "header": {},
        "cookie": {},
    }

    for parameter_list in (path_item.get("parameters") or [], method_item.get("parameters") or []):
        for source in parameter_list:
            if not isinstance(source, dict):
                continue
            location = source.get("in")
            name = source.get("name")
            if location not in grouped or not name:
                continue
            grouped[location][name] = (
                source.get("schema") or {},
                bool(source.get("required", False)),
            )

    return grouped


def render_parameters(path_item: Dict[str, Any], method_item: Dict[str, Any], level: int) -> List[str]:
    grouped = collect_parameters(path_item, method_item)
    blocks: List[str] = []
    for location in ("query", "path", "header", "cookie"):
        params = grouped.get(location) or {}
        if not params:
            continue

        blocks.append(f"{indent(level + 1)}{location}: {{")
        for name in sorted(params.keys()):
            schema, required = params[name]
            optional = "" if required else "?"
            ts_type = schema_to_ts(schema, level + 2)
            blocks.append(f"{indent(level + 2)}{name}{optional}: {ts_type};")
        blocks.append(f"{indent(level + 1)}}};")

    if not blocks:
        return []

    return [f"{indent(level)}parameters: {{", *blocks, f"{indent(level)}}};"]


def render_request_body(method_item: Dict[str, Any], level: int) -> List[str]:
    request_body = method_item.get("requestBody")
    if not request_body:
        return []

    content = request_body.get("content") or {}
    body_lines: List[str] = []
    for content_type, content_schema in content.items():
        schema = (content_schema or {}).get("schema") or {}
        body_lines.append(
            f"{indent(level + 2)}\"{content_type}\": {schema_to_ts(schema, level + 2)};"
        )

    if not body_lines:
        body_lines.append(f"{indent(level + 2)}\"application/json\": unknown;")

    optional = "" if request_body.get("required") else "?"
    return [
        f"{indent(level)}requestBody{optional}: {{",
        f"{indent(level + 1)}content: {{",
        *body_lines,
        f"{indent(level + 1)}}};",
        f"{indent(level)}}};",
    ]


def render_responses(method_item: Dict[str, Any], level: int) -> List[str]:
    responses = method_item.get("responses") or {}
    lines = [f"{indent(level)}responses: {{"]

    for status_code in sorted(responses.keys(), key=lambda value: (len(str(value)), str(value))):
        response = responses[status_code] or {}
        content = response.get("content") or {}
        lines.append(f"{indent(level + 1)}\"{status_code}\": {{")

        if content:
            lines.append(f"{indent(level + 2)}content: {{")
            for content_type in sorted(content.keys()):
                schema = (content[content_type] or {}).get("schema") or {}
                lines.append(
                    f"{indent(level + 3)}\"{content_type}\": {schema_to_ts(schema, level + 3)};"
                )
            lines.append(f"{indent(level + 2)}}};")

        lines.append(f"{indent(level + 1)}}};")

    lines.append(f"{indent(level)}}};")
    return lines


def render_components(spec: Dict[str, Any]) -> List[str]:
    schemas = ((spec.get("components") or {}).get("schemas") or {})
    lines = ["export interface components {", "  schemas: {"]
    for name in sorted(schemas.keys()):
        ts_type = schema_to_ts(schemas[name], 2)
        if "\n" in ts_type:
            lines.append(f"    {name}: {ts_type};")
        else:
            lines.append(f"    {name}: {ts_type};")
    lines.append("  };")
    lines.append("}")
    return lines


def render_paths(spec: Dict[str, Any]) -> List[str]:
    paths = spec.get("paths") or {}
    lines = ["export interface paths {"]

    for path in sorted(paths.keys()):
        path_item = paths[path] or {}
        lines.append(f'  "{path}": {{')

        for method in sorted(path_item.keys()):
            if method.startswith("x-"):
                continue
            if method not in {"get", "post", "put", "patch", "delete", "head", "options"}:
                continue

            method_item = path_item[method] or {}
            lines.append(f"    {method}: {{")

            param_lines = render_parameters(path_item, method_item, 3)
            lines.extend(param_lines)

            body_lines = render_request_body(method_item, 3)
            lines.extend(body_lines)

            response_lines = render_responses(method_item, 3)
            lines.extend(response_lines)

            lines.append("    };")

        lines.append("  };")

    lines.append("}")
    return lines


def generate(spec: Dict[str, Any]) -> str:
    header = [
        "/* auto-generated by scripts/generate_openapi_ts.py; do not edit by hand */",
        "",
    ]
    body = [*render_components(spec), "", *render_paths(spec), ""]
    return "\n".join(header + body)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--spec", default="openapi/openapi.json")
    parser.add_argument("--out", default="src/generated/openapi.ts")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    spec_path = pathlib.Path(args.spec)
    out_path = pathlib.Path(args.out)

    if not spec_path.exists():
        print(f"OpenAPI spec not found: {spec_path}", file=sys.stderr)
        return 1

    with spec_path.open("r", encoding="utf-8") as fh:
        spec = json.load(fh)

    rendered = generate(spec)

    if args.check:
        existing = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
        if existing != rendered:
            print(f"Generated client is out of date: {out_path}", file=sys.stderr)
            return 1
        return 0

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(rendered, encoding="utf-8")
    print(f"Generated {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
