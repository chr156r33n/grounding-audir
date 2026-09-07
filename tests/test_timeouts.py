from core.models import GroundingRequest, Target
from core.timeouts import configured_timeout_seconds, provider_timeout_seconds
from providers.openai_web import OpenAIWebProvider


def test_openai_uses_longer_provider_timeout():
    request = GroundingRequest(
        "run",
        "query",
        [Target("example.com")],
        provider_options={"timeout_seconds": 90},
    )
    assert provider_timeout_seconds(request, OpenAIWebProvider()) == 120.0


def test_configured_timeout_is_clamped():
    request = GroundingRequest(
        "run",
        "query",
        [Target("example.com")],
        provider_options={"timeout_seconds": 999},
    )
    assert configured_timeout_seconds(request) == 180.0
