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
