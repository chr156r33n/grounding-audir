from providers.gemini import GeminiProvider
from providers.model_catalog import (
    GEMINI_GOOGLE_SEARCH,
    MICROSOFT_BING_GROUNDING,
    OPENAI_WEB_SEARCH,
    model_field,
)


def test_model_field_uses_catalog_defaults():
    field = model_field(OPENAI_WEB_SEARCH)
    assert field.default == "gpt-5.5"
    assert "gpt-5.5" in field.choices
    assert "gpt-4.1-mini" in field.choices


def test_provider_rejects_undocumented_model():
    errors = GeminiProvider().validate_config(
        {"api_key": "secret", "model": "not-a-real-model"}
    )
    assert any("documented options" in error for error in errors)


def test_catalog_defaults_match_provider_defaults():
    assert GeminiProvider.default_model == GEMINI_GOOGLE_SEARCH.default
    assert OPENAI_WEB_SEARCH.default == "gpt-5.5"
    assert MICROSOFT_BING_GROUNDING.default == "gpt-4.1-mini"
