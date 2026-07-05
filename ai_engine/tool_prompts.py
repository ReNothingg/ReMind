from functools import lru_cache
from pathlib import Path

_TOOLS_DIR = Path(__file__).with_name("tools")


@lru_cache(maxsize=16)
def load_tool_prompt(filename: str) -> str:
    path = _TOOLS_DIR / filename
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

def load_tool_prompt_section(filename: str, heading: str) -> str:
    prompt = load_tool_prompt(filename)
    if not prompt:
        return ""
    return markdown_section(prompt, heading)
