MAX_SUBAGENT_MODELS = 24
SUBAGENT_MODEL_ID_LIMIT = 240

AGENT_LIMITS = {
    "maxSteps": (1, 32, 16),
    "maxToolCallsPerStep": (1, 4, 4),
    "maxToolCalls": (1, 32, 32),
    "toolTimeSeconds": (30, 180, 180),
    "shellTimeoutMs": (100, 15_000, 10_000),
    "shellMaxOutputBytes": (256, 16_000, 12_000),
    "subagentMaxDepth": (0, 2, 0),
    "subagentMaxActive": (1, 3, 2),
    "contextThresholdPercent": (20, 99, 80),
    "contextRetainPercent": (4, 80, 16),
    "contextRetainTokens": (0, 160_000, 0),
    "contextHeadroomTokens": (0, 65_536, 4_096),
    "contextSummaryTokens": (512, 8_192, 2_048),
    "contextSummaryRetries": (0, 2, 1),
}


def supports_delegation(model):
    return (
        isinstance(model, str)
        and 0 < len(model) <= SUBAGENT_MODEL_ID_LIMIT
        and (
            model in {"base", "harness", "claude_sonnet_5_5"}
            or model.startswith(("key/", "codex/", "chatgpt/"))
        )
    )


def normalize_agent_runtime(raw):
    raw = raw if isinstance(raw, dict) else {}
    values = {}
    for key, (minimum, maximum, default) in AGENT_LIMITS.items():
        value = raw.get(key)
        values[key] = value if type(value) is int and minimum <= value <= maximum else default
    values["contextCompaction"] = (
        "manual" if raw.get("contextCompaction") == "manual" else "automatic"
    )
    values["contextSummaryMode"] = (
        "model" if raw.get("contextSummaryMode") == "model" else "excerpts"
    )
    summary_model = raw.get("contextSummaryModel")
    values["contextSummaryModel"] = (
        summary_model if isinstance(summary_model, str) and len(summary_model) <= 240 else ""
    )
    if (
        not values["contextRetainTokens"]
        and values["contextRetainPercent"] >= values["contextThresholdPercent"]
    ):
        values["contextRetainPercent"] = AGENT_LIMITS["contextRetainPercent"][2]
    values["shellEnabled"] = raw.get("shellEnabled") is True
    values["modelReplayEnabled"] = raw.get("modelReplayEnabled") is True
    model = raw.get("subagentModel")
    values["subagentModel"] = (
        model if isinstance(model, str) and len(model) <= SUBAGENT_MODEL_ID_LIMIT else ""
    )
    allowed = raw.get("subagentAllowedModels")
    candidates = allowed[:MAX_SUBAGENT_MODELS] if isinstance(allowed, list) else []
    values["subagentAllowedModels"] = list(
        dict.fromkeys(model for model in candidates if supports_delegation(model))
    )
    values["subagentModelSelection"] = raw.get("subagentModelSelection") is True
    return values
