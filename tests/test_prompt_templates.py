from ai_engine.personalization import build_system_prompt, render_user_md_with_settings
from ai_engine.prompt_templates import load_prompt, markdown_section, render_prompt


def test_load_prompt_rejects_paths_outside_ai_engine() -> None:
    assert load_prompt("../config.py") == ""


def test_render_prompt_replaces_dynamic_context() -> None:
    rendered = render_prompt(
        "context/active_mind.md",
        {
            "MIND_NAME": "Reviewer",
            "MIND_DESCRIPTION": "Reviews code",
            "MIND_INSTRUCTIONS": "Find correctness issues.",
        },
    )

    assert "Mind name: Reviewer" in rendered
    assert "Find correctness issues." in rendered
    assert "{{MIND_" not in rendered


def test_render_prompt_does_not_reprocess_inserted_values() -> None:
    rendered = render_prompt(
        "context/active_mind.md",
        {
            "MIND_NAME": "{{MIND_DESCRIPTION}}",
            "MIND_DESCRIPTION": "Description",
            "MIND_INSTRUCTIONS": "Instructions",
        },
    )

    assert "Mind name: {{MIND_DESCRIPTION}}" in rendered
    assert "Mind description: Description" in rendered


def test_markdown_section_extracts_only_requested_prompt() -> None:
    markdown = "# Tool\n\n## First\n\nOne\n\n## Second\n\nTwo"

    assert markdown_section(markdown, "First") == "One"


def test_system_prompt_keeps_markdown_sections_separated() -> None:
    base_prompt = load_prompt("prompt.md")
    user_prompt = render_user_md_with_settings(None, {})

    rendered = build_system_prompt(None, {})

    assert rendered.startswith(f"{base_prompt}\n\nThe user provided")
    assert "{{" not in user_prompt
