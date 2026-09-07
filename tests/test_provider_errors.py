from core.provider_errors import (
    configuration_hint,
    extract_provider_error_details,
    invalid_config_message,
    validate_foundry_project_endpoint,
)


class FakeHttpError(Exception):
    def __init__(self, status_code: int, body: dict):
        self.status_code = status_code
        self.body = body


def test_validate_foundry_project_endpoint_requires_project_path():
    errors = validate_foundry_project_endpoint("https://example.services.ai.azure.com")
    assert any("/api/projects/" in error for error in errors)


def test_invalid_config_message_includes_api_message_and_foundry_hint():
    exc = FakeHttpError(
        404,
        {"error": {"message": "Deployment gpt-5.5 not found", "code": "DeploymentNotFound"}},
    )
    message = invalid_config_message(
        exc,
        provider_id="microsoft_web",
        config={
            "model": "gpt-5.5",
            "project_endpoint": "https://x.services.ai.azure.com/api/projects/demo",
        },
    )
    assert "Deployment gpt-5.5 not found" in message
    assert "exact deployment name" in message
    assert "Deployment `gpt-5.5` was not found" in message


def test_extract_provider_error_details_summarises_response_body():
    exc = FakeHttpError(400, {"error": {"message": "Invalid tool type", "code": "BadRequest"}})
    details = extract_provider_error_details(exc)
    assert details["status_code"] == 400
    assert details["response_body"]["error"]["message"] == "Invalid tool type"


def test_configuration_hint_flags_web_search_unsupported():
    hint = configuration_hint(
        "microsoft_web",
        {"model": "gpt-4.1-mini"},
        {"response_body": {"error": {"message": "web_search tool is not supported"}}},
    )
    assert "web_search" in hint.lower() or "bing grounding" in hint.lower()
