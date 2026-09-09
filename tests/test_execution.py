import time

from core.enums import ErrorType, ProviderType, RunStatus
from core.execution import execute_providers
from core.models import GroundingRequest, Target
from providers.base import GroundingProvider


class FakeProvider(GroundingProvider):
    provider_type = ProviderType.GROUNDING
    default_model = "fake"

    def __init__(self, provider_id, behavior):
        self.id = provider_id
        self.name = provider_id
        self.behavior = behavior

    def run(self, request, config):
        if self.behavior == "fail":
            error = RuntimeError("private provider detail")
            error.status_code = 401
            raise error
        if self.behavior == "slow":
            time.sleep(0.2)
        return self.new_run(request)

    def parse_response(self, raw_response, request, model=None):
        return self.new_run(request, model)


def test_provider_failure_does_not_stop_other_provider():
    request = GroundingRequest("run", "query", [Target("example.com")])
    jobs = [(FakeProvider("good", "good"), {}), (FakeProvider("bad", "fail"), {})]
    runs = {run.provider_id: run for run in execute_providers(request, jobs, max_retries=0)}
    assert runs["good"].status is RunStatus.COMPLETE
    assert runs["bad"].status is RunStatus.FAILED
    assert runs["bad"].error.type is ErrorType.AUTH_ERROR
    assert "private provider detail" not in runs["bad"].error.safe_message


def test_provider_has_independent_timeout():
    request = GroundingRequest("run", "query", [Target("example.com")])
    jobs = [(FakeProvider("good", "good"), {}), (FakeProvider("slow", "slow"), {})]
    runs = {
        run.provider_id: run
        for run in execute_providers(request, jobs, timeout_seconds=0.03, max_retries=0)
    }
    assert runs["good"].status is RunStatus.COMPLETE
    assert runs["slow"].status is RunStatus.TIMED_OUT


def test_debug_mode_captures_failure_context_and_redacts_secrets():
    request = GroundingRequest(
        "run",
        "query",
        [Target("example.com")],
        provider_options={"debug_mode": True},
    )
    run = next(
        execute_providers(
            request,
            [(FakeProvider("bad", "fail"), {"api_key": "do-not-display"})],
            max_retries=0,
        )
    )

    assert run.status is RunStatus.FAILED
    assert run.metadata["debug"]["context"]["config"]["api_key"] == "[REDACTED]"
    assert run.metadata["debug"]["exception"]["type"] == "RuntimeError"
    assert run.metadata["debug"]["execution_trace"]


def test_invalid_config_includes_foundry_configuration_hint():
    class BadConfigProvider(FakeProvider):
        def run(self, request, config):
            exc = RuntimeError("ignored")
            exc.status_code = 404
            exc.body = {"error": {"message": "Deployment missing-model not found"}}
            raise exc

    request = GroundingRequest("run", "query", [Target("example.com")])
    run = next(
        execute_providers(
            request,
            [
                (
                    BadConfigProvider("microsoft_web", "bad"),
                    {
                        "project_endpoint": "https://x.services.ai.azure.com/api/projects/demo",
                        "model": "missing-model",
                    },
                )
            ],
            max_retries=0,
        )
    )

    assert run.status is RunStatus.FAILED
    assert run.error.type is ErrorType.INVALID_CONFIG
    assert "missing-model" in run.error.safe_message
    assert run.metadata.get("error_details", {}).get("status_code") == 404
