from core.credentials_help import CREDENTIAL_SECTIONS, provider_ids_with_help
from core.provider_errors import FOUNDRY_ACCESS_TOKEN_COMMAND
from providers.registry import PROVIDERS


def test_every_provider_has_credentials_help():
    help_ids = set(provider_ids_with_help())
    assert help_ids == set(PROVIDERS)


def test_foundry_help_uses_current_token_command():
    foundry_sections = [
        section.body
        for section in CREDENTIAL_SECTIONS
        if section.provider_id in {"microsoft_web", "microsoft_bing"}
    ]
    assert foundry_sections
    assert all(FOUNDRY_ACCESS_TOKEN_COMMAND in body for body in foundry_sections)
    assert all("ai.azure.com/.default" in body for body in foundry_sections)
