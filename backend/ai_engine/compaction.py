from dataclasses import dataclass


@dataclass(frozen=True)
class CompactionTurn:
    max_tokens: int


def supports_summary_model(model):
    return isinstance(model, str) and (
        model in {"base", "harness", "claude_sonnet_5_5"}
        or model.startswith(("key/", "chatgpt/", "codex/"))
    )


def compaction_turn(data):
    turn = data.get("_compaction_turn")
    return turn if isinstance(turn, CompactionTurn) else None


def compaction_output_limit(data, limit=None):
    turn = compaction_turn(data)
    if turn is None:
        return limit
    return min(turn.max_tokens, limit) if limit is not None else turn.max_tokens
