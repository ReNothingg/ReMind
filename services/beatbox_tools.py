import json
from typing import Any


DRUM_TYPES = {"kick", "snare", "clap", "hihat", "open_hat", "tom", "triangle", "cowbell"}
ADSR_DEFAULTS = {
    "attack": 0.001,
    "decay": 0.1,
    "sustain": 0.0,
    "release": 0.05,
}


def normalize_beatbox_state(value: Any) -> dict[str, Any] | None:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return None

    if not isinstance(value, dict):
        return None

    raw_meta = value.get("meta") if isinstance(value.get("meta"), dict) else {}
    bpm = _clamp_int(raw_meta.get("bpm"), 120, 40, 240)
    bars = _clamp_int(raw_meta.get("bars"), 1, 1, 16)
    max_steps = bars * 16

    tracks: list[dict[str, Any]] = []
    for index, raw_track in enumerate(_safe_list(value.get("tracks"))[:32]):
        if not isinstance(raw_track, dict):
            continue

        steps = [
            1 if step is True or step == 1 else 0
            for step in _safe_list(raw_track.get("steps"))[:max_steps]
        ]
        if not steps:
            continue

        drum = _clean_string(raw_track.get("drum"), 40) or "kick"
        if drum not in DRUM_TYPES:
            drum = "kick"

        tracks.append(
            {
                "id": _clean_string(raw_track.get("id"), 80) or f"track_{index + 1}",
                "type": "drum",
                "drum": drum,
                "steps": steps,
                "adsr": _normalize_adsr(raw_track.get("adsr")),
            }
        )

    if not tracks:
        return None

    return {
        "meta": {"bpm": bpm, "bars": bars},
        "tracks": tracks,
        "isPlaying": False,
        "currentStep": 0,
        "timerId": None,
    }


def _normalize_adsr(value: Any) -> dict[str, float]:
    raw = value if isinstance(value, dict) else {}
    return {
        key: _clamp_float(raw.get(key), default, 0.0, 2.0)
        for key, default in ADSR_DEFAULTS.items()
    }


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _clean_string(value: Any, max_length: int) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


def _clamp_int(value: Any, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))


def _clamp_float(value: Any, default: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(min_value, min(max_value, parsed))
