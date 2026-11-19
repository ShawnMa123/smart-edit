"""Provider and egress settings (assistant-model-gateway / design D5, D12)."""

from __future__ import annotations

import pytest

from app.assistant.settings import AssistantSettings, assert_production_safe


def test_defaults_disable_every_external_call():
    settings = AssistantSettings.from_env({})

    assert settings.model is None
    assert settings.web == "off"
    assert settings.web_enabled is False
    assert settings.approved_processor is False
    assert settings.egress_policy is None  # resolved by priority at load time (knowledge.json → sample → yaml)
    assert settings.processor_label == "fixture"


def test_model_must_use_the_doubao_prefix():
    with pytest.raises(ValueError):
        AssistantSettings.from_env({"SMART_EDIT_ASSISTANT_MODEL": "gpt-4o"})


def test_model_requires_credentials_instead_of_silent_fallback():
    with pytest.raises(ValueError):
        AssistantSettings.from_env({"SMART_EDIT_ASSISTANT_MODEL": "doubao:seed-1"})


def test_configured_model_is_reported_with_its_label():
    settings = AssistantSettings.from_env(
        {
            "SMART_EDIT_ASSISTANT_MODEL": "doubao:seed-1",
            "SMART_EDIT_ASSISTANT_API_KEY": "k",
            "SMART_EDIT_ASSISTANT_PROCESSOR_APPROVED": "1",
        }
    )

    assert settings.model_name == "seed-1"
    assert settings.model_provider == "doubao"
    assert settings.processor_label == "doubao:seed-1"
    assert settings.approved_processor is True


def test_web_provider_values_are_validated():
    with pytest.raises(ValueError):
        AssistantSettings.from_env({"SMART_EDIT_ASSISTANT_WEB": "google"})

    enabled = AssistantSettings.from_env({"SMART_EDIT_ASSISTANT_WEB": "fixture"})
    assert enabled.web_enabled is True


def test_production_fails_closed_without_an_approved_processor():
    assert_production_safe("local", None)

    with pytest.raises(RuntimeError):
        assert_production_safe("production", AssistantSettings())

    with pytest.raises(RuntimeError):
        assert_production_safe(
            "production", AssistantSettings(model="doubao:x", api_key="k", approved_processor=False)
        )

    assert_production_safe(
        "production", AssistantSettings(model="doubao:x", api_key="k", approved_processor=True)
    )


def test_general_web_channel_is_off_by_default():
    settings = AssistantSettings.from_env({})

    assert settings.general_web is False
    assert settings.web_search_max_keyword == 3


def test_general_web_and_keyword_are_parsed_and_clamped():
    enabled = AssistantSettings.from_env(
        {
            "SMART_EDIT_ASSISTANT_GENERAL_WEB": "1",
            "SMART_EDIT_ASSISTANT_WEB_SEARCH_MAX_KEYWORD": "9",
        }
    )
    assert enabled.general_web is True
    assert enabled.web_search_max_keyword == 5

    zero = AssistantSettings.from_env({"SMART_EDIT_ASSISTANT_WEB_SEARCH_MAX_KEYWORD": "0"})
    assert zero.web_search_max_keyword == 1

    with pytest.raises(ValueError):
        AssistantSettings.from_env({"SMART_EDIT_ASSISTANT_WEB_SEARCH_MAX_KEYWORD": "three"})
