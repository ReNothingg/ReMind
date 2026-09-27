from __future__ import annotations

import csv
import io
import json
import math
from typing import Any

from services.artifact_workspace import ArtifactWorkspace
from services.document_tools import _read_file
from services.tool_protocol import ModelToolResult

MAX_ROWS = 20_000
MAX_COLUMNS = 128


def _rows(filename: str, files: list[dict]) -> tuple[list[str], list[dict[str, Any]]]:
    content = _read_file(filename, files)
    if filename.lower().endswith(".json"):
        try:
            rows = json.loads(content)
        except (ValueError, RecursionError) as exc:
            raise ValueError("invalid_json") from exc
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("json_array_of_objects_required")
        columns = list(dict.fromkeys(key for row in rows for key in row))
        if any(
            not isinstance(value, (str, int, float, bool, type(None)))
            for row in rows
            for value in row.values()
        ):
            raise ValueError("flat_table_required")
    elif filename.lower().endswith(".csv"):
        try:
            dialect = csv.Sniffer().sniff(content[:8192], delimiters=",;\t|")
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(content, newline=""), dialect, strict=True)
        try:
            columns = next(reader, [])
            if (
                not columns
                or len(columns) != len(set(columns))
                or any(not column.strip() for column in columns)
            ):
                raise ValueError("unique_column_names_required")
            rows = []
            for values in reader:
                if len(values) != len(columns):
                    raise ValueError("inconsistent_csv_columns")
                rows.append(dict(zip(columns, values, strict=True)))
                if len(rows) > MAX_ROWS:
                    raise ValueError("table_too_large")
        except csv.Error as exc:
            raise ValueError("invalid_csv") from exc
    else:
        raise ValueError("csv_or_json_required")
    if (
        len(rows) > MAX_ROWS
        or len(columns) > MAX_COLUMNS
        or any(len(column) > 160 for column in columns)
    ):
        raise ValueError("table_too_large")
    return columns, rows


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError):
        return None


def _public_row(row: dict) -> dict:
    return {
        key: (
            value[:500]
            if isinstance(value, str)
            else value if not isinstance(value, float) or math.isfinite(value) else None
        )
        for key, value in row.items()
    }


def execute_data_tool(
    name: str, arguments: dict, files: list[dict], workspace: ArtifactWorkspace
) -> ModelToolResult:
    try:
        columns, rows = _rows(arguments["filename"], files)
        if name == "table_inspect":
            stats = []
            for column in columns:
                values = [row.get(column) for row in rows]
                numeric = [number for value in values if (number := _number(value)) is not None]
                stats.append(
                    {
                        "name": column,
                        "empty": sum(value is None or value == "" for value in values),
                        "numeric": len(numeric),
                        "minimum": min(numeric) if numeric else None,
                        "maximum": max(numeric) if numeric else None,
                    }
                )
            return ModelToolResult(
                {
                    "ok": True,
                    "rows": len(rows),
                    "columns": stats,
                    "sample_columns": columns[:8],
                    "sample": [
                        _public_row({key: row.get(key) for key in columns[:8]}) for row in rows[:3]
                    ],
                }
            )
        selected = arguments.get("columns") or columns[:32]
        if len(selected) != len(set(selected)):
            raise ValueError("duplicate_columns")
        if any(column not in columns for column in selected):
            raise ValueError("unknown_column")
        filtered = rows
        for condition in arguments.get("filters", []):
            column, op, value = condition["column"], condition["operator"], condition["value"]
            if column not in columns:
                raise ValueError("unknown_column")
            if op in {"greater_than", "less_than"} and _number(value) is None:
                raise ValueError("numeric_filter_required")

            def matches(row: dict, column=column, op=op, value=value) -> bool:
                candidate = row.get(column)
                if op == "equals":
                    return str(candidate if candidate is not None else "") == value
                if op == "contains":
                    return (
                        value.casefold()
                        in str(candidate if candidate is not None else "").casefold()
                    )
                first, second = _number(candidate), _number(value)
                if first is None or second is None:
                    return False
                return first > second if op == "greater_than" else first < second

            filtered = [row for row in filtered if matches(row)]
        if arguments.get("aggregate") and not arguments.get("group_by"):
            raise ValueError("group_by_required")
        if arguments.get("group_by"):
            group = arguments["group_by"]
            measure = arguments.get("value_column")
            aggregate = arguments.get("aggregate", "count")
            if group not in columns or (aggregate != "count" and measure not in columns):
                raise ValueError("unknown_column")
            groups: dict[str, list[dict]] = {}
            for row in filtered:
                key = str(row.get(group) if row.get(group) is not None else "")
                groups.setdefault(key, []).append(row)
                if len(groups) > 1000:
                    raise ValueError("too_many_groups")
            aggregated = []
            for key, items in groups.items():
                numbers = [
                    number for item in items if (number := _number(item.get(measure))) is not None
                ]
                value = (
                    len(items)
                    if aggregate == "count"
                    else (
                        math.fsum(numbers)
                        if aggregate == "sum"
                        else (
                            math.fsum(numbers) / len(numbers)
                            if aggregate == "average" and numbers
                            else (
                                min(numbers)
                                if aggregate == "min" and numbers
                                else max(numbers) if aggregate == "max" and numbers else None
                            )
                        )
                    )
                )
                aggregated.append({"group": key, "value": value})
            filtered, selected = aggregated, ["group", "value"]
        sort_by = arguments.get("sort_by")
        if sort_by:
            if sort_by not in selected:
                raise ValueError("unknown_column")

            def sort_key(row: dict):
                value = row.get(sort_by)
                number = _number(value)
                return (0, number) if number is not None else (1, str(value or "").casefold())

            filtered = sorted(filtered, key=sort_key, reverse=arguments.get("descending", False))
        offset, limit = arguments.get("offset", 0), arguments.get("limit", 20)
        page = []
        output_chars = 0
        for row in filtered[offset : offset + limit]:
            candidate = _public_row({column: row.get(column) for column in selected})
            size = len(json.dumps(candidate, ensure_ascii=False))
            if output_chars + size > 24_000:
                break
            page.append(candidate)
            output_chars += size
        output = {
            "ok": True,
            "matched_rows": len(filtered),
            "columns": selected,
            "columns_truncated": not arguments.get("columns") and len(columns) > 32,
            "cell_preview_characters": 500,
            "rows": page,
            "next_offset": offset + len(page) if offset + len(page) < len(filtered) else None,
        }
        export = arguments.get("export_filename")
        if export:
            if not export.lower().endswith(".csv"):
                raise ValueError("csv_export_required")
            stream = io.StringIO(newline="")
            writer = csv.DictWriter(stream, fieldnames=selected, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(filtered)
            result = workspace.save(export, stream.getvalue(), files)
            result.output = {**output, **result.output}
            return result
        return ModelToolResult(output)
    except (ValueError, OSError, OverflowError) as exc:
        return ModelToolResult(
            {
                "ok": False,
                "error": str(exc) if isinstance(exc, ValueError) else "data_processing_failed",
            }
        )
