from __future__ import annotations

import io
import re
import stat
import unicodedata
import zipfile
import zlib
from pathlib import PurePosixPath

from backend.errors import ApiError
from python_runner.workspace_shell import MAX_SCRIPT_BYTES, ShellError, compile_script

MAX_ARCHIVE_BYTES = 512 * 1024
MAX_SKILL_BYTES = 64 * 1024
MAX_RESOURCE_BYTES = 32 * 1024
MAX_TOTAL_BYTES = 256 * 1024
MAX_RESOURCES = 16
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
RESOURCE_EXTENSIONS = {".md", ".txt", ".csv", ".tsv", ".json", ".yaml", ".yml"}
RESERVED_NAMES = {"compact"}


def skill_error(code, status=400):
    return ApiError(code, status=status, code=code)


def is_skill_name(value):
    return (
        isinstance(value, str)
        and len(value) <= 64
        and value not in RESERVED_NAMES
        and SKILL_NAME.fullmatch(value) is not None
    )


def _text(value, *, byte_limit, character_limit=None, empty=False, trim=True):
    if not isinstance(value, str):
        raise skill_error("skill_invalid_document")
    if trim:
        value = value.strip()
    try:
        size = len(value.encode("utf-8"))
    except UnicodeError:
        raise skill_error("skill_invalid_document") from None
    if (
        size > byte_limit
        or (character_limit is not None and len(value) > character_limit)
        or (not value and not empty)
        or any(ord(c) < 32 and c not in "\r\n\t" for c in value)
    ):
        raise skill_error("skill_invalid_document")
    return value


def _path_parts(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 240:
        raise skill_error("skill_invalid_path")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise skill_error("skill_invalid_path") from None
    if (
        any(char in value for char in ("\\", ":", "\0"))
        or unicodedata.normalize("NFC", value) != value
    ):
        raise skill_error("skill_invalid_path")
    parts = value.split("/")
    if len(parts) > 8 or any(
        not part
        or part in (".", "..")
        or part.rstrip(" .") != part
        or any(unicodedata.category(char) in {"Cc", "Cf", "Cs"} for char in part)
        for part in parts
    ):
        raise skill_error("skill_invalid_path")
    return tuple(parts)


def _resource_path(value):
    parts = _path_parts(value)
    if is_script_path(value):
        return value
    if (
        PurePosixPath(parts[-1]).suffix.lower() not in RESOURCE_EXTENSIONS
        or "scripts" in {part.casefold() for part in parts}
        or parts[-1].casefold() == "skill.md"
    ):
        raise skill_error("skill_unsupported_member")
    return "/".join(parts)


def is_script_path(path):
    return isinstance(path, str) and path.startswith("scripts/") and path.endswith(".sh")


def _check_script(source):
    try:
        compile_script(source)
    except ShellError:
        raise skill_error("skill_unsupported_script") from None


def normalize_skill(value):
    keys = {
        "name",
        "description",
        "body",
        "resources",
        "whenToUse",
        "compatibility",
        "license",
        "modelInvocable",
        "userInvocable",
    }
    if not isinstance(value, dict) or value.keys() - keys or not is_skill_name(value.get("name")):
        raise skill_error("skill_invalid_document")
    description = _text(value.get("description"), byte_limit=4096, character_limit=1024)
    body = _text(value.get("body"), byte_limit=MAX_SKILL_BYTES)
    resources = value.get("resources", {})
    if not isinstance(resources, dict) or len(resources) > MAX_RESOURCES:
        raise skill_error("skill_invalid_document")
    validated = {}
    seen = set()
    scripts = []
    size = len(body.encode("utf-8"))
    for path, text in resources.items():
        name = _resource_path(path)
        if name.casefold() in seen:
            raise skill_error("skill_invalid_path")
        seen.add(name.casefold())
        script = is_script_path(name)
        validated[name] = _text(
            text,
            byte_limit=MAX_SCRIPT_BYTES if script else MAX_RESOURCE_BYTES,
            empty=True,
            trim=False,
        )
        if script:
            _check_script(validated[name])
            scripts.append(name)
        size += len(validated[name].encode("utf-8"))
    if size > MAX_TOTAL_BYTES:
        raise skill_error("skill_package_too_large", 413)
    properties = {"scriptPaths": sorted(scripts)} if scripts else {}
    for key in ("modelInvocable", "userInvocable"):
        flag = value.get(key, True)
        if type(flag) is not bool:
            raise skill_error("skill_invalid_document")
        properties[key] = flag
    for key, maximum in (("whenToUse", 500), ("compatibility", 500), ("license", 250)):
        if key in value:
            properties[key] = _text(value[key], byte_limit=maximum * 4, character_limit=maximum)
    return {
        "name": value["name"],
        "description": description,
        "body": body,
        "resources": validated,
        "properties": properties,
    }


def _read_member(archive, entry, limit):
    if entry.file_size > limit:
        raise skill_error("skill_package_too_large", 413)
    with archive.open(entry) as member:
        raw = member.read(limit + 1)
    if len(raw) > limit:
        raise skill_error("skill_package_too_large", 413)
    return _text(raw.decode("utf-8-sig"), byte_limit=limit, empty=True, trim=False)


def unpack_skill(file):
    if file is None or PurePosixPath(file.filename or "").suffix.lower() not in {".zip", ".skill"}:
        raise skill_error("skill_invalid_package")
    raw = file.stream.read(MAX_ARCHIVE_BYTES + 1)
    if len(raw) > MAX_ARCHIVE_BYTES:
        raise skill_error("skill_package_too_large", 413)
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (
                len(entries) > MAX_RESOURCES * 3
                or sum(info.file_size for info in entries) > MAX_TOTAL_BYTES
            ):
                raise skill_error("skill_package_too_large", 413)
            files = {}
            seen = set()
            for info in entries:
                parts = _path_parts(
                    info.orig_filename.rstrip("/") if info.is_dir() else info.orig_filename
                )
                key = "/".join(parts).casefold()
                mode = stat.S_IFMT(info.external_attr >> 16)
                if (
                    key in seen
                    or info.flag_bits & 1
                    or mode not in (0, stat.S_IFDIR if info.is_dir() else stat.S_IFREG)
                    or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                ):
                    raise skill_error("skill_invalid_package")
                seen.add(key)
                if not info.is_dir():
                    files[parts] = info
            docs = [parts for parts in files if parts[-1] == "SKILL.md"]
            if len(docs) != 1:
                raise skill_error("skill_invalid_package")
            folder, doc = docs[0][:-1], docs[0]
            if len(files) - 1 > MAX_RESOURCES:
                raise skill_error("skill_package_too_large", 413)
            markdown = _read_member(archive, files[doc], MAX_SKILL_BYTES)
            resources = {}
            for parts, entry in files.items():
                if parts == doc:
                    continue
                if parts[: len(folder)] != folder:
                    raise skill_error("skill_invalid_path")
                path = _resource_path("/".join(parts[len(folder) :]))
                script = is_script_path(path)
                resources[path] = _read_member(
                    archive, entry, MAX_SCRIPT_BYTES if script else MAX_RESOURCE_BYTES
                )
                if script:
                    _check_script(resources[path])
    except (UnicodeError, OSError, zipfile.BadZipFile, ValueError, RuntimeError, zlib.error):
        raise skill_error("skill_invalid_package") from None
    return {"markdown": markdown, "resources": resources}
