from __future__ import annotations

import fnmatch
import io
import json
import re
import sys
import unicodedata
from dataclasses import dataclass, field, replace
from itertools import groupby
from pathlib import Path

MAX_SCRIPT_BYTES = 8192
MAX_COMMANDS = 8
MAX_SCRIPT_COMMANDS = 16
MAX_SCRIPT_ARGUMENTS = 9
MAX_NAMES = 64
MAX_OPERANDS = 24
MAX_TEXT_BYTES = 8 * 1024 * 1024
MAX_LINES = 200_000
MAX_EXPORT_BYTES = 512 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
SAFE_ALIAS = re.compile(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,179}")
EXPORT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,110}\.(?:txt|md|json)", re.I)
NUMBER_PREFIX = re.compile(r"^[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
SCRIPT_ARGUMENT = re.compile(r'"\$([1-9])"(?=$|[ \t\n|<>&;])')
FLAGS = {
    "ls": "1",
    "cat": "n",
    "head": "",
    "tail": "",
    "wc": "lwc",
    "grep": "Finvc",
    "sort": "nru",
    "uniq": "cdu",
    "cut": "",
}
VALUE_OPTIONS = {"head": "n", "tail": "n", "grep": "m", "cut": "dfc"}


class ShellError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


@dataclass
class Word:
    text: str
    operator: bool = False
    pattern: str | None = None
    argument: int | None = None


@dataclass
class Command:
    name: str
    operands: list[str] = field(default_factory=list)
    flags: set[str] = field(default_factory=set)
    values: dict[str, str] = field(default_factory=dict)
    literal: str | None = None
    indices: tuple[int, ...] = ()


@dataclass
class Pipeline:
    commands: list[Command]
    required: list[str]
    input_name: str | None
    output_name: str | None


@dataclass
class Script:
    steps: list[tuple[str | None, Pipeline]]
    required: list[str]
    output_name: str | None


def is_workspace_name(name):
    return (
        isinstance(name, str)
        and 1 <= len(name) <= 240
        and not any(character in name for character in ("\\", ":"))
        and not any(unicodedata.category(character) in ("Cc", "Cf", "Cs") for character in name)
        and all(
            part and part not in (".", "..") and part == part.strip() for part in name.split("/")
        )
    )


def _words(line, *, script=False):
    whitespace = "\t\n" if script else "\t"
    if (
        not isinstance(line, str)
        or not line.strip()
        or len(line) > MAX_SCRIPT_BYTES
        or any(ord(char) < 32 and char not in whitespace for char in line)
    ):
        raise ShellError("shell_invalid_pipeline")
    try:
        if len(line.encode("utf-8")) > MAX_SCRIPT_BYTES:
            raise ShellError("shell_invalid_pipeline")
    except UnicodeError:
        raise ShellError("shell_invalid_pipeline") from None
    items = []
    index = 0
    operators = "|<>&;\n" if script else "|<>"
    while index < len(line):
        char = line[index]
        if char in " \t":
            index += 1
            continue
        if script and char == "#":
            newline = line.find("\n", index)
            index = newline if newline >= 0 else len(line)
            continue
        if script and char in "|&" and line.startswith(char * 2, index):
            items.append(Word(char * 2, operator=True))
            index += 2
            continue
        if char in operators:
            if char == "&":
                raise ShellError("shell_unsupported_syntax")
            if (
                char == ">"
                and index > 0
                and line[index - 1] not in " \t"
                and items
                and items[-1].text.isdecimal()
            ):
                raise ShellError("shell_unsupported_syntax")
            items.append(Word(char, operator=True))
            index += 1
            continue
        if script and (argument := SCRIPT_ARGUMENT.match(line, index)):
            items.append(Word("", argument=int(argument[1])))
            index = argument.end()
            continue
        value, pattern = [], []
        has_glob = False
        quote = None
        while index < len(line):
            char = line[index]
            if quote is None and (char in " \t" or char in operators):
                break
            if char == "\n":
                raise ShellError("shell_unsupported_syntax")
            index += 1
            if char == quote:
                quote = None
                continue
            if quote is None and char in ("'", '"'):
                quote = char
                continue
            if char == "\\" and quote != "'":
                if index == len(line) or line[index] == "\n":
                    raise ShellError("shell_invalid_pipeline")
                char = line[index]
                index += 1
                literal = True
            else:
                literal = quote is not None
                if (quote is None and char in ";&()") or (quote != "'" and char in "`$"):
                    raise ShellError("shell_unsupported_syntax")
            value.append(char)
            if not literal and char in "*?":
                has_glob = True
                pattern.append(char)
            elif char in "*?[":
                pattern.append(f"[{char}]")
            else:
                pattern.append(char)
        if quote is not None:
            raise ShellError("shell_invalid_pipeline")
        items.append(Word("".join(value), pattern="".join(pattern) if has_glob else None))
    return items


def _count(value, maximum, *, minimum=0):
    if re.fullmatch(r"[0-9]{1,5}", value) is None or not minimum <= int(value) <= maximum:
        raise ShellError("shell_invalid_option")
    return int(value)


def _positions(value):
    selected = set()
    for entry in value.split(","):
        bounds = entry.split("-")
        if len(bounds) > 2:
            raise ShellError("shell_invalid_option")
        first = _count(bounds[0], 1024, minimum=1)
        last = _count(bounds[-1], 1024, minimum=first)
        selected.update(range(first - 1, last))
    return tuple(sorted(selected))


def _options(words):
    command = Command(words[0].text)
    if words[0].argument is not None or command.name not in FLAGS:
        raise ShellError("shell_unsupported_command")
    simple = FLAGS[command.name]
    valued = VALUE_OPTIONS.get(command.name, "")
    index = 1
    while index < len(words):
        token = words[index]
        if token.argument is not None:
            break
        if token.text == "--":
            index += 1
            break
        if not token.text.startswith("-") or token.text == "-":
            break
        if token.pattern is not None:
            raise ShellError("shell_invalid_option")
        options = token.text[1:]
        index += 1
        for offset, flag in enumerate(options):
            if flag in simple:
                command.flags.add(flag)
            elif flag in valued and flag not in command.values:
                value = options[offset + 1 :]
                if not value:
                    if index == len(words) or words[index].argument is not None:
                        raise ShellError("shell_invalid_option")
                    value = words[index].text
                    index += 1
                command.values[flag] = value
                break
            else:
                raise ShellError("shell_invalid_option")
    for mode, value in command.values.items():
        if mode in ("n", "m"):
            _count(value, 10_000)
    if command.name == "cut":
        selections = [key for key in ("c", "f") if key in command.values]
        if (
            len(selections) != 1
            or len(command.values.get("d", "\t")) != 1
            or ("d" in command.values and selections[0] != "f")
        ):
            raise ShellError("shell_invalid_option")
        command.indices = _positions(command.values[selections[0]])
    if command.name == "grep":
        if (
            index >= len(words)
            or (words[index].argument is None and not 1 <= len(words[index].text) <= 240)
            or words[index].pattern is not None
        ):
            raise ShellError("shell_invalid_option")
        command.literal = words[index].text
        index += 1
    return command, words[index:]


def _matches(pattern, name):
    parts, names = pattern.split("/"), name.split("/")
    return len(parts) == len(names) and all(
        fnmatch.fnmatchcase(actual, segment) for segment, actual in zip(parts, names, strict=True)
    )


def _operands(command, tokens, files):
    result = []
    for token in tokens:
        if files is None and token.argument is not None:
            continue
        name = token.text.removeprefix("./")
        if command == "ls" and token.text in (".", "./"):
            result.append(".")
        elif command != "ls" and name == "-":
            result.append(name)
        else:
            name = name.rstrip("/") if command == "ls" else name
            if not is_workspace_name(name):
                raise ShellError("shell_file_unavailable")
            if files is None:
                result.append(name)
            elif token.pattern is not None:
                pattern = token.pattern.removeprefix("./")
                matched = sorted(key for key in files if _matches(pattern, key))
                if not matched:
                    raise ShellError("shell_file_unavailable")
                result.extend(matched)
            elif name in files or (
                command == "ls" and any(key.startswith(name + "/") for key in files)
            ):
                result.append(name)
            else:
                raise ShellError("shell_file_unavailable")
        if len(result) > MAX_OPERANDS:
            raise ShellError("shell_too_many_files")
    return result


def _check_files(files):
    if (
        not isinstance(files, dict)
        or len(files) > MAX_NAMES
        or any(
            not is_workspace_name(name)
            or not isinstance(alias, str)
            or SAFE_ALIAS.fullmatch(alias) is None
            for name, alias in files.items()
        )
    ):
        raise ShellError("shell_invalid_files")


def compile_pipeline(line, files):
    _check_files(files)
    return _compile_pipeline(_words(line), files)


def _compile_pipeline(words, files):
    segments = [[]]
    input_name, output_name = None, None
    index = 0
    while index < len(words):
        current = words[index]
        index += 1
        if not current.operator:
            segments[-1].append(current)
            continue
        if not segments[-1]:
            raise ShellError("shell_invalid_pipeline")
        if current.text == "|":
            segments.append([])
            if len(segments) > MAX_COMMANDS:
                raise ShellError("shell_invalid_pipeline")
            continue
        if index == len(words) or words[index].operator or words[index].pattern is not None:
            raise ShellError("shell_invalid_pipeline")
        token = words[index]
        target = token.text.removeprefix("./")
        unbound = files is None and token.argument is not None
        index += 1
        if current.text == "<" and len(segments) == 1 and input_name is None:
            if not (unbound or is_workspace_name(target)) or (
                files is not None and target not in files
            ):
                raise ShellError("shell_file_unavailable")
            input_name = target
        elif current.text == ">" and output_name is None and index == len(words):
            if not unbound and EXPORT_NAME.fullmatch(target) is None:
                raise ShellError("shell_invalid_output")
            output_name = target
        else:
            raise ShellError("shell_invalid_pipeline")
    commands = []
    required = {files[input_name]} if input_name is not None and files is not None else set()
    for segment in segments:
        if not segment:
            raise ShellError("shell_invalid_pipeline")
        command, raw = _options(segment)
        command.operands = _operands(command.name, raw, files)
        if command.name != "ls" and files is not None:
            required.update(files[name] for name in command.operands if name != "-")
        commands.append(command)
    if len(required) > MAX_OPERANDS:
        raise ShellError("shell_too_many_files")
    return Pipeline(commands, sorted(required), input_name, output_name)


def _script_steps(words):
    chain = []
    condition = None
    for word in words:
        if word.operator and word.text in {"\n", ";", "&&", "||"}:
            if word.text == "\n" and (not chain or (chain[-1].operator and chain[-1].text == "|")):
                continue
            if not chain:
                raise ShellError("shell_invalid_pipeline")
            yield condition, chain
            chain = []
            condition = word.text if word.text in {"&&", "||"} else None
        else:
            chain.append(word)
    if chain:
        yield condition, chain
    elif condition:
        raise ShellError("shell_invalid_pipeline")


def compile_script(source, files=None, arguments=None):
    if not isinstance(source, str):
        raise ShellError("shell_invalid_pipeline")
    words = _words(source.replace("\r\n", "\n"), script=True)
    if files is not None:
        _check_files(files)
        if (
            not isinstance(arguments, list)
            or len(arguments) > MAX_SCRIPT_ARGUMENTS
            or any(
                not isinstance(value, str)
                or not 1 <= len(value) <= 240
                or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in value)
                for value in arguments
            )
            or any((word.argument or 0) > len(arguments) for word in words)
        ):
            raise ShellError("shell_invalid_arguments")
        words = [
            replace(word, text=arguments[word.argument - 1]) if word.argument is not None else word
            for word in words
        ]
    steps = []
    required = set()
    commands = 0
    for condition, chain in _script_steps(words):
        if steps and steps[-1][1].output_name is not None:
            raise ShellError("shell_invalid_output")
        plan = _compile_pipeline(chain, files)
        required.update(plan.required)
        commands += len(plan.commands)
        if len(required) > MAX_OPERANDS:
            raise ShellError("shell_too_many_files")
        if commands > MAX_SCRIPT_COMMANDS:
            raise ShellError("shell_invalid_pipeline")
        steps.append((condition, plan))
    if not steps:
        raise ShellError("shell_invalid_pipeline")
    return Script(steps, sorted(required), steps[-1][1].output_name)


def _lines(text):
    if text.count("\n") > MAX_LINES:
        raise ShellError("shell_output_limit")
    normalized = text.replace("\r\n", "\n")
    return normalized.removesuffix("\n").split("\n") if normalized else []


def _write_rows(rows):
    output = io.StringIO()
    size = 0
    for text in rows:
        size += len(text.encode("utf-8"))
        if size > MAX_TEXT_BYTES:
            raise ShellError("shell_output_limit")
        output.write(text)
    return output.getvalue()


def _row_text(lines):
    return _write_rows(line + "\n" for line in lines)


class SourceFiles:
    def __init__(self, files, root):
        self.files = files
        self.root = root
        self.cached = {}
        self.sizes = {}
        self.loaded_bytes = 0

    def read(self, key):
        alias = self.files[key]
        if alias not in self.cached:
            try:
                with (self.root / alias).open("rb") as handle:
                    raw = handle.read(MAX_TEXT_BYTES - self.loaded_bytes + 1)
                self.loaded_bytes += len(raw)
                if self.loaded_bytes > MAX_TEXT_BYTES:
                    raise ShellError("shell_output_limit")
                if b"\0" in raw:
                    raise ShellError("shell_text_required")
                self.cached[alias] = raw.decode("utf-8")
                self.sizes[alias] = len(raw)
            except UnicodeError:
                raise ShellError("shell_text_required") from None
            except OSError:
                raise ShellError("shell_file_unavailable") from None
        return self.cached[alias]

    def inputs(self, command, stdin):
        inputs = []
        size = 0
        stdin_size = len(stdin.encode("utf-8"))
        for name in command.operands or ["-"]:
            text = stdin if name == "-" else self.read(name)
            size += stdin_size if name == "-" else self.sizes[self.files[name]]
            if size > MAX_TEXT_BYTES:
                raise ShellError("shell_output_limit")
            inputs.append((name, text))
        return inputs


def _list_files(command, files):
    entries = set()
    for directory in command.operands or ["."]:
        if directory in files:
            entries.add(directory)
            continue
        prefix = "" if directory == "." else directory + "/"
        for name in files:
            if not name.startswith(prefix):
                continue
            first, divider, _ = name.removeprefix(prefix).partition("/")
            entries.add(first + divider)
    return _row_text(sorted(entries))


def _cat(command, sources):
    if "n" not in command.flags:
        return _write_rows(text for _, text in sources)
    rows = (line for _, text in sources for line in _lines(text))
    return _row_text(f"{index:6}\t{line}" for index, line in enumerate(rows, 1))


def _end(command, sources):
    count = int(command.values.get("n", "10"))

    def rows():
        for index, (name, text) in enumerate(sources):
            if len(sources) > 1:
                yield ("\n" if index else "") + f"==> {name} <==\n"
            lines = _lines(text)
            subset = lines[:count] if command.name == "head" else (lines[-count:] if count else [])
            for line in subset:
                yield line + "\n"

    return _write_rows(rows())


def _wc(command, sources):
    counts = [flag for flag in "lwc" if flag in command.flags] or ["l", "w", "c"]

    def rows():
        for name, text in sources:
            values = {"l": text.count("\n"), "w": len(text.split()), "c": len(text.encode("utf-8"))}
            padding = 8 if len(counts) > 1 else 1
            yield (
                " ".join(str(values[flag]).rjust(padding) for flag in counts)
                + ("" if name == "-" else " " + name)
                + "\n"
            )

    return _write_rows(rows())


def _grep(command, sources):
    literal = command.literal or ""
    insensitive, inverse = "i" in command.flags, "v" in command.flags
    needle = literal.casefold() if insensitive else literal
    maximum = int(command.values.get("m", str(MAX_LINES)))
    matched = 0

    def rows():
        nonlocal matched
        for name, text in sources:
            count = 0
            prefix = name + ":" if len(sources) > 1 else ""
            for index, line in enumerate(_lines(text), 1):
                if count >= maximum:
                    break
                value = line.casefold() if insensitive else line
                if (needle in value) == inverse:
                    continue
                count += 1
                if "c" not in command.flags:
                    yield prefix + (f"{index}:" if "n" in command.flags else "") + line + "\n"
            matched += count
            if "c" in command.flags:
                yield prefix + str(count) + "\n"

    return _write_rows(rows()), 0 if matched else 1


def _numeric(value):
    match = NUMBER_PREFIX.match(value.lstrip()[:120])
    return float(match[0]) if match else 0.0


def _sort(command, sources):
    lines = []
    for _, text in sources:
        rows = _lines(text)
        if len(lines) + len(rows) > MAX_LINES:
            raise ShellError("shell_output_limit")
        lines.extend(rows)
    lines.sort(key=_numeric if "n" in command.flags else None, reverse="r" in command.flags)
    if "u" in command.flags:
        lines = list(dict.fromkeys(lines))
    return _row_text(lines)


def _uniq(command, sources):
    rows = (line for _, text in sources for line in _lines(text))

    def selected():
        for line, entries in groupby(rows):
            count = sum(1 for _ in entries)
            if ("d" in command.flags and count < 2) or ("u" in command.flags and count > 1):
                continue
            yield (f"{count:7} " if "c" in command.flags else "") + line

    return _row_text(selected())


def _cut(command, sources):
    delimiter = command.values.get("d", "\t")
    field_mode = "f" in command.values

    def rows():
        for _, text in sources:
            for line in _lines(text):
                if field_mode and delimiter not in line:
                    yield line
                    continue
                parts = line.split(delimiter, 1024) if field_mode else line
                yield (delimiter if field_mode else "").join(
                    parts[index] for index in command.indices if index < len(parts)
                )

    return _row_text(rows())


PROGRAMS = {
    "cat": _cat,
    "head": _end,
    "tail": _end,
    "wc": _wc,
    "sort": _sort,
    "uniq": _uniq,
    "cut": _cut,
}


def run_pipeline(plan, files, input_root):
    return _run_pipeline(plan, SourceFiles(files, input_root))


def _run_pipeline(plan, sources):
    stdin = sources.read(plan.input_name) if plan.input_name is not None else ""
    statuses = []
    for command in plan.commands:
        code = 0
        if command.name == "ls":
            stdin = _list_files(command, sources.files)
        elif command.name == "grep":
            stdin, code = _grep(command, sources.inputs(command, stdin))
        else:
            stdin = PROGRAMS[command.name](command, sources.inputs(command, stdin))
        statuses.append({"command": command.name, "exit_code": code})
    return stdin, statuses


def _write_export(name, data):
    if not data:
        raise ShellError("shell_empty_output")
    if len(data) > MAX_EXPORT_BYTES:
        raise ShellError("shell_output_limit")
    if name.lower().endswith(".json"):
        try:
            json.loads(data)
        except (ValueError, RecursionError):
            raise ShellError("shell_invalid_output") from None
    (Path("output") / name).write_bytes(data)


def _run_script(plan, sources):
    stdout = []
    size = 0
    status = 0
    statuses = []
    artifact_created = False
    for index, (condition, step) in enumerate(plan.steps, 1):
        if (condition == "&&" and status != 0) or (condition == "||" and status == 0):
            continue
        text, stages = _run_pipeline(step, sources)
        statuses.extend({**stage, "step": index} for stage in stages)
        status = stages[-1]["exit_code"]
        data = text.encode("utf-8")
        if step.output_name:
            _write_export(step.output_name, data)
            artifact_created = True
        else:
            size += len(data)
            if size > MAX_TEXT_BYTES:
                raise ShellError("shell_output_limit")
            stdout.append(text)
    return "".join(stdout), statuses, artifact_created


def _report(text, statuses, limit):
    data = text.encode("utf-8")
    preview = data[:limit].decode("utf-8", errors="ignore")
    safe = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", preview)
    return {
        "ok": True,
        "exit_code": statuses[-1]["exit_code"],
        "stdout": safe,
        "stdout_truncated": len(data) > limit,
        "output_bytes": len(data),
        "stages": statuses,
    }


def run_job(request):
    source, files, limit = request["line"], request["files"], request["max_output_bytes"]
    sources = SourceFiles(files, Path("input"))
    if "arguments" in request:
        plan = compile_script(source, files, request["arguments"])
        if plan.required != sorted(request["staged_names"]):
            raise ShellError("shell_file_unavailable")
        text, statuses, created = _run_script(plan, sources)
        return {**_report(text, statuses, limit), "artifact_created": created}
    plan = compile_pipeline(source, files)
    if plan.required != sorted(request["staged_names"]):
        raise ShellError("shell_file_unavailable")
    text, statuses = _run_pipeline(plan, sources)
    if plan.output_name is not None:
        _write_export(plan.output_name, text.encode("utf-8"))
    return _report(text, statuses, limit)


def main():
    try:
        raw = sys.stdin.buffer.read(MAX_MANIFEST_BYTES + 1)
        if len(raw) > MAX_MANIFEST_BYTES:
            raise ShellError("shell_invalid_pipeline")
        result = run_job(json.loads(raw))
    except ShellError as error:
        result = {"ok": False, "error": error.code}
    except (KeyError, OSError, TypeError, ValueError, RecursionError):
        result = {"ok": False, "error": "shell_pipeline_failed"}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
