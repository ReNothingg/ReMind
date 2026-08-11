from ai_engine.personalization import build_system_prompt, render_visualize_tool_prompt


def test_visualize_prompt_exposes_remind_runtime_contract():
    prompt = render_visualize_tool_prompt()

    assert "```visualize:Accessible title" in prompt
    assert "window.remind" in prompt
    assert "--viz-series-6" in prompt
    assert "Never use gradients or shadows" in prompt


def test_visualize_prompt_respects_tools_enabled_setting():
    enabled = build_system_prompt(None, {"toolsEnabled": True, "history": []})
    disabled = build_system_prompt(None, {"toolsEnabled": False, "history": []})

    assert "Namespace: visualize" in enabled
    assert "Namespace: visualize" not in disabled


def test_visualize_prompt_is_not_advertised_on_telegram_surface():
    prompt = build_system_prompt(
        None,
        {
            "toolsEnabled": True,
            "history": [],
            "telegram_context": {"chat_id": 1},
        },
    )

    assert "Namespace: visualize" not in prompt
