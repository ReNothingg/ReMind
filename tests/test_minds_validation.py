import pytest

from routes.api_errors import ApiError
from routes.features.minds import _payload_to_mind_fields


def _mind_payload(instructions: str) -> dict[str, object]:
    return {
        "name": "OpenHand",
        "description": "Handwritten document assistant",
        "instructions": instructions,
        "starters": [],
        "category": "general",
        "visibility": "private",
    }


def test_mind_instructions_accept_literal_html_and_svg_examples():
    instructions = """# Документы OpenHand

Используй <span class="underline-wavy">подчёркивание</span>.

<figure class="imported-svg">
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 120">
  <path d="M 20 100 L 100 20 L 180 100 Z" fill="none" stroke="#111"/>
</svg>
</figure>

<details><summary>Показать ответ</summary>Готово.</details>
"""

    fields = _payload_to_mind_fields(_mind_payload(instructions))

    assert fields["instructions"] == instructions.strip()


def test_mind_instructions_still_reject_control_characters():
    with pytest.raises(ApiError, match="Instructions contains invalid characters"):
        _payload_to_mind_fields(_mind_payload("Допустимый текст с нулевым байтом\x00 внутри"))


def test_public_mind_fields_still_reject_html_markup():
    payload = _mind_payload("Подробные безопасные инструкции для mind.")
    payload["description"] = "Описание <script>alert(1)</script>"

    with pytest.raises(ApiError, match="Description contains invalid characters"):
        _payload_to_mind_fields(payload)
