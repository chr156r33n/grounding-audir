from unittest.mock import patch

import pytest

from core.citation_redirects import (
    enrich_citations_with_redirect_resolution,
    gemini_target_cited,
    resolve_grounding_redirect,
    should_resolve_citation_redirects,
)
from core.enums import MatchMode, ObservationState
from core.models import Citation, GroundingRequest, Target


@pytest.fixture
def request():
    return GroundingRequest(
        run_id="redirect-test",
        input_phrase="est restaurant tokyo",
        targets=[Target("https://www.fourseasons.com/tokyo/est/", MatchMode.URL_PREFIX)],
        provider_options={"resolve_citation_redirects": True},
    )


def test_should_resolve_defaults_on_for_url_prefix(request):
    assert should_resolve_citation_redirects(request) is True
    root_request = GroundingRequest(
        run_id="root",
        input_phrase="query",
        targets=[Target("fourseasons.com", MatchMode.ROOT_DOMAIN)],
    )
    assert should_resolve_citation_redirects(root_request) is False


def test_resolve_grounding_redirect_returns_final_url():
    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example"
    final_url = "https://www.fourseasons.com/tokyo/est/"

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return final_url

    with patch("core.citation_redirects.urlopen", return_value=FakeResponse()):
        resolved, error = resolve_grounding_redirect(redirect)
    assert resolved == final_url
    assert error is None


def test_enrich_citations_promotes_url_prefix_match(request):
    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example"
    citation = Citation(url=redirect, title="fourseasons.com")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return "https://www.fourseasons.com/tokyo/est/"

    with patch("core.citation_redirects.urlopen", return_value=FakeResponse()):
        enrich_citations_with_redirect_resolution([citation], request)

    assert citation.metadata["resolved_url"] == "https://www.fourseasons.com/tokyo/est/"
    assert citation.target_matches == ["https://www.fourseasons.com/tokyo/est/"]
    assert gemini_target_cited([citation], request) is ObservationState.YES


def test_gemini_target_cited_unknown_when_redirect_resolution_fails(request):
    redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example"
    citation = Citation(url=redirect, title="fourseasons.com", metadata={"redirect_resolution": "failed"})

    assert gemini_target_cited([citation], request) is ObservationState.UNKNOWN
