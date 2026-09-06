import json
from pathlib import Path

import pytest

from core.enums import MatchMode, ObservationState
from core.models import GroundingRequest, Target
from providers.gemini import GeminiProvider
from providers.microsoft_bing import MicrosoftBingProvider
from providers.microsoft_web import MicrosoftWebProvider
from providers.microsoft_web_iq import MicrosoftWebIQProvider
from providers.openai_web import OpenAIWebProvider

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "provider_responses.json").read_text()
)


@pytest.fixture
def request():
    return GroundingRequest(
        run_id="test-run",
        input_phrase="best luxury hotels in hong kong",
        targets=[Target("fourseasons.com", MatchMode.ROOT_DOMAIN)],
        market="en-GB",
        language="en",
    )


def test_gemini_citations_do_not_become_retrieval(request):
    run = GeminiProvider().parse_response(FIXTURES["gemini"], request)
    assert len(run.generated_queries) == 2
    assert run.search_performed is ObservationState.YES
    assert run.target_cited is ObservationState.YES
    assert run.target_retrieved is ObservationState.UNKNOWN
    assert run.citations[0].cited_text == "The Four Seasons"
    assert run.metadata["search_suggestions"]


def test_openai_distinguishes_sources_and_citations(request):
    run = OpenAIWebProvider().parse_response(FIXTURES["openai"], request)
    assert run.target_retrieved is ObservationState.YES
    assert run.target_cited is ObservationState.YES
    assert len(run.sources) == 2
    assert run.sources[0].cited is ObservationState.YES
    assert run.citations[0].cited_text is None


def test_openai_empty_observable_sources_is_no(request):
    fixture = {
        "output": [
            {"type": "web_search_call", "action": {"query": "q", "sources": []}},
            {"type": "message", "content": [{"type": "output_text", "text": "No result"}]},
        ]
    }
    run = OpenAIWebProvider().parse_response(fixture, request)
    assert run.target_retrieved is ObservationState.NO
    assert run.target_cited is ObservationState.NO
    assert "empty consulted-source list" in run.metadata["state_notes"]["target_retrieved"]


def test_openai_missing_sources_field_is_unknown(request):
    fixture = {
        "output": [
            {"type": "web_search_call", "action": {"type": "search", "query": "q"}},
            {"type": "message", "content": [{"type": "output_text", "text": "No result"}]},
        ]
    }
    run = OpenAIWebProvider().parse_response(fixture, request)
    assert run.target_retrieved is ObservationState.UNKNOWN
    assert run.metadata["sources_observable"] is False
    assert "sources" in run.metadata["state_notes"]["target_retrieved"].lower()


def test_microsoft_web_iq_exposes_retrieval_passages(request):
    run = MicrosoftWebIQProvider().parse_response(FIXTURES["microsoft_web_iq"], request)
    assert run.search_performed is ObservationState.YES
    assert run.target_retrieved is ObservationState.YES
    assert run.target_cited is ObservationState.NOT_APPLICABLE
    assert len(run.sources) == 2
    assert len(run.grounding_content) == 2
    assert run.sources[0].retrieved is ObservationState.YES
    assert run.sources[0].cited is ObservationState.NO
    assert "retrieval evidence" in run.metadata["retrieval_note"]


def test_microsoft_web_iq_empty_response_is_unknown_retrieval(request):
    run = MicrosoftWebIQProvider().parse_response({}, request)
    assert run.search_performed is ObservationState.UNKNOWN
    assert run.target_retrieved is ObservationState.NO
    assert run.target_cited is ObservationState.NOT_APPLICABLE


def test_microsoft_web_retrieval_remains_unknown(request):
    run = MicrosoftWebProvider().parse_response(FIXTURES["microsoft_web"], request)
    assert run.search_performed is ObservationState.YES
    assert run.target_retrieved is ObservationState.NO
    assert run.target_cited is ObservationState.NO
    assert len(run.sources) == 1


def test_bing_grounding_query_and_target_citation(request):
    run = MicrosoftBingProvider().parse_response(FIXTURES["microsoft_bing"], request)
    assert len(run.generated_queries) == 2
    assert run.generated_queries[0].metadata["query_url"].startswith("https://www.bing.com/")
    assert run.generated_queries[0].metadata["query_url_constructed"] is True
    assert run.target_retrieved is ObservationState.UNKNOWN
    assert run.target_cited is ObservationState.YES
    assert "does not expose" in run.metadata["retrieval_note"]


@pytest.mark.parametrize(
    "provider",
    [GeminiProvider(), OpenAIWebProvider(), MicrosoftWebProvider(), MicrosoftBingProvider()],
)
def test_empty_response_is_defensive(provider, request):
    run = provider.parse_response({}, request)
    assert run.search_performed in {ObservationState.NO, ObservationState.UNKNOWN}
    assert run.target_retrieved is ObservationState.UNKNOWN
    assert run.target_cited is ObservationState.NO
