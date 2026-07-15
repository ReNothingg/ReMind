import re
from pathlib import Path
from typing import Mapping

_PROMPT_ROOT = Path(__file__).parent.resolve()
_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z][A-Za-z0-9_]*)\}\}")


def load_prompt(relative_path: str) -> str:
    path = (_PROMPT_ROOT / relative_path).resolve()
    try:
        path.relative_to(_PROMPT_ROOT)
    except ValueError:
        return ""

    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def markdown_section(markdown: str, heading: str) -> str:
    target = heading.strip().casefold()
    lines = markdown.splitlines()
    section_lines: list[str] = []
    section_level: int | None = None

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            marker, _, title = stripped.partition(" ")
            if marker and set(marker) == {"#"} and title:
                level = len(marker)
                normalized_title = title.strip().casefold()
                if normalized_title == target:
                    section_level = level
                    section_lines = []
                    continue
                if section_level is not None and level <= section_level:
                    break

        if section_level is not None:
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def load_prompt_section(relative_path: str, heading: str) -> str:
    prompt = load_prompt(relative_path)
    if not prompt:
        return ""
    return markdown_section(prompt, heading)


def render_prompt(relative_path: str, replacements: Mapping[str, object]) -> str:
    return _render(load_prompt(relative_path), replacements)


def render_prompt_section(
    relative_path: str, heading: str, replacements: Mapping[str, object]
) -> str:
    return _render(load_prompt_section(relative_path, heading), replacements)


def _render(template: str, replacements: Mapping[str, object]) -> str:
    def replace_placeholder(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in replacements:
            return match.group(0)
        return str(replacements[key])

    return _PLACEHOLDER_RE.sub(replace_placeholder, template)
