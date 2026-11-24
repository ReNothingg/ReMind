from __future__ import annotations

import re
from dataclasses import dataclass, field

BEGIN = "*** Begin Patch"
END = "*** End Patch"
EOF = "*** End of File"
MOVE = "*** Move to: "
HEADERS = {"*** Add File: ": "add", "*** Delete File: ": "delete", "*** Update File: ": "update"}
PUNCTUATION = str.maketrans(
    {
        **dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212", "-"),
        **dict.fromkeys("\u2018\u2019\u201a\u201b", "'"),
        **dict.fromkeys("\u201c\u201d\u201e\u201f", '"'),
        **dict.fromkeys(
            "\u00a0\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u202f\u205f\u3000", " "
        ),
    }
)
MAX_PATCH_BYTES = 65_536
MAX_PATCH_OPERATIONS = 20
MAX_PATCH_HUNKS = 120
MAX_COMPARISONS = 1_000_000


class PatchError(ValueError):
    def __init__(self, code: str, line: int | None = None):
        super().__init__(code)
        self.code = code
        self.line = line


@dataclass
class Hunk:
    line: int
    context: str | None = None
    old: list[str] = field(default_factory=list)
    new: list[str] = field(default_factory=list)
    eof: bool = False

    def empty(self):
        return not (self.old or self.new)


@dataclass
class PatchOperation:
    kind: str
    path: str
    line: int
    added: list[str] = field(default_factory=list)
    hunks: list[Hunk] = field(default_factory=list)
    destination: str | None = None


def _validate_update(operation, line):
    if operation is not None and operation.kind == "update":
        if not operation.hunks or operation.hunks[-1].empty():
            raise PatchError("workspace_patch_invalid", line)


def _update_line(operation, text, number):
    header = text.rstrip()
    previous = operation.hunks[-1] if operation.hunks else None
    marker = header == "@@" or header.startswith("@@ ")
    if previous and previous.eof:
        if not header:
            return
        if not marker:
            raise PatchError("workspace_patch_invalid", number)
    if previous is None and operation.destination is None and header.startswith(MOVE):
        operation.destination = header[len(MOVE) :]
        return
    if marker:
        if previous and previous.empty():
            raise PatchError("workspace_patch_invalid", number)
        operation.hunks.append(
            Hunk(number, context=header[3:] if header.startswith("@@ ") else None)
        )
        return
    if header == EOF:
        if previous is None or previous.empty():
            raise PatchError("workspace_patch_invalid", number)
        previous.eof = True
        return
    if text and text[0] not in (" ", "+", "-"):
        raise PatchError("workspace_patch_invalid", number)
    hunk = previous or Hunk(number)
    if previous is None:
        operation.hunks.append(hunk)
    content = text[1:]
    if not text.startswith("+"):
        hunk.old.append(content)
    if not text.startswith("-"):
        hunk.new.append(content)


def parse_patch(patch):
    if not isinstance(patch, str) or "\0" in patch:
        raise PatchError("workspace_patch_invalid")
    try:
        size = len(patch.encode("utf-8"))
    except UnicodeError:
        raise PatchError("workspace_patch_invalid") from None
    if size > MAX_PATCH_BYTES:
        raise PatchError("workspace_patch_too_large")
    offset = patch[: len(patch) - len(patch.lstrip())].count("\n")
    lines = list(enumerate(re.split(r"\r?\n", patch.strip()), offset + 1))
    if len(lines) >= 4 and lines[0][1] in ("<<EOF", "<<'EOF'", '<<"EOF"') and lines[-1][1] == "EOF":
        lines = lines[1:-1]
    if lines[0][1].strip() != BEGIN or lines[-1][1].strip() != END:
        raise PatchError("workspace_patch_invalid", lines[0][0])

    operations = []
    current = None
    for number, text in lines[1:-1]:
        header = text.rstrip() if current is not None and current.kind == "update" else text.strip()
        for label, kind in HEADERS.items():
            if header.startswith(label):
                _validate_update(current, number)
                current = PatchOperation(kind, header[len(label) :], number)
                operations.append(current)
                break
        else:
            if current and current.kind == "add" and text.startswith("+"):
                current.added.append(text[1:])
            elif current and current.kind == "update":
                _update_line(current, text, number)
            else:
                raise PatchError("workspace_patch_invalid", number)
        if len(operations) > MAX_PATCH_OPERATIONS:
            raise PatchError("workspace_patch_too_large", number)
    _validate_update(current, lines[-1][0])
    if not operations:
        raise PatchError("workspace_patch_no_changes")
    if sum(len(operation.hunks) for operation in operations) > MAX_PATCH_HUNKS:
        raise PatchError("workspace_patch_too_large")
    return operations


def _literal(value):
    return value


def _punctuation(value):
    return value.strip().translate(PUNCTUATION)


def _seek(views, pattern, start, eof, budget):
    if not pattern:
        return start
    last = len(views[0][1]) - len(pattern)
    if last < start:
        return None
    first = last if eof else start
    for normalize, lines in views:
        expected = [normalize(line) for line in pattern]
        for position in range(first, last + 1):
            for offset, target in enumerate(expected):
                budget[0] -= 1
                if budget[0] < 0:
                    raise PatchError("workspace_patch_too_large")
                if lines[position + offset] != target:
                    break
            else:
                return position
    return None


def apply_hunks(before, hunks, budget):
    windows_lines = "\r\n" in before and "\n" not in before.replace("\r\n", "")
    original = before.replace("\r\n", "\n").split("\n")
    if original[-1] == "":
        original.pop()
    views = [
        (normalize, [normalize(line) for line in original])
        for normalize in (_literal, str.rstrip, str.strip, _punctuation)
    ]
    replacements = []
    cursor = 0
    for hunk in hunks:
        if hunk.context is not None:
            found = _seek(views, [hunk.context], cursor, False, budget)
            if found is None:
                raise PatchError("workspace_patch_context_missing", hunk.line)
            cursor = found + 1
        if not hunk.old:
            start = len(original) - 1 if original and original[-1] == "" else len(original)
            replacements.append((start, 0, hunk.new))
            continue
        pattern, new = hunk.old, hunk.new
        found = _seek(views, pattern, cursor, hunk.eof, budget)
        if found is None and pattern[-1] == "":
            pattern = pattern[:-1]
            new = new[:-1] if new and new[-1] == "" else new
            found = _seek(views, pattern, cursor, hunk.eof, budget)
        if found is None:
            raise PatchError("workspace_patch_context_missing", hunk.line)
        replacements.append((found, len(pattern), new))
        cursor = found + len(pattern)
    for start, size, new in reversed(sorted(replacements, key=lambda change: change[0])):
        original[start : start + size] = new
    if not original or original[-1] != "":
        original.append("")
    return ("\r\n" if windows_lines else "\n").join(original)
