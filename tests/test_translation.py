from unittest.mock import patch

import pytest
import requests

from services.translation import TranslationUnavailableError, translate_text


def test_translate_text_uses_primary_provider_when_available():
    with (
        patch(
            "services.translation.generate_text_with_trace",
            return_value=("Bonjour", {"code": "ok"}),
        ),
        patch("services.translation._translate_with_fallback") as fallback,
    ):
        translated_text, used_fallback = translate_text("Hello", "fr")

    assert translated_text == "Bonjour"
    assert used_fallback is False
    fallback.assert_not_called()


def test_translate_text_uses_fallback_after_primary_provider_failure():
    with (
        patch(
            "services.translation.generate_text_with_trace",
            return_value=(None, {"code": "provider_failed"}),
        ),
        patch(
            "services.translation._translate_with_fallback",
            return_value="Привет, мир",
        ) as fallback,
    ):
        translated_text, used_fallback = translate_text("Hello world", "ru")

    assert translated_text == "Привет, мир"
    assert used_fallback is True
    fallback.assert_called_once_with("Hello world", "ru")


def test_translate_text_reports_when_both_providers_fail():
    with (
        patch(
            "services.translation.generate_text_with_trace",
            return_value=(None, {"code": "provider_failed"}),
        ),
        patch(
            "services.translation._translate_with_fallback",
            side_effect=requests.Timeout("timeout"),
        ),
        pytest.raises(TranslationUnavailableError),
    ):
        translate_text("Hello", "ru")
