import pytest

from core.enums import MatchMode, ObservationState
from core.models import GroundingRequest, Target
from providers.deepseek_web import DeepSeekWebProvider
from providers.openai_web import OpenAIWebProvider
from providers.responses_parsing import (
    collect_search_sources,
    extract_url,
    parse_markdown_link_citations,
)


@pytest.fixture
def request():
    return GroundingRequest(
        run_id="test-run",
        input_phrase="best luxury hotels in hong kong",
        targets=[Target("fourseasons.com", MatchMode.ROOT_DOMAIN)],
    )


def test_collect_search_sources_reads_results_field():
    item = {
        "type": "web_search_call",
        "action": {
            "type": "search",
            "query": "hotels",
            "results": [{"url": "https://www.fourseasons.com/hongkong/", "title": "FS"}],
        },
    }
    records, fields = collect_search_sources(item)
    assert extract_url(records[0]) == "https://www.fourseasons.com/hongkong/"
    assert "action.results" in fields


def test_deepseek_anchor_only_citations_stay_unknown_for_target_cited(request):
    fixture = {
        "output": [
            {
                "type": "web_search_call",
                "action": {
                    "type": "search",
                    "query": "luxury hotels hong kong",
                    "results": [
                        {"title": "Four Seasons Hong Kong", "url": "https://www.fourseasons.com/hongkong/"}
                    ],
                },
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Four Seasons is recommended.",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "title": "Four Seasons Hong Kong",
                                "start_index": 0,
                                "end_index": 12,
                            }
                        ],
                    }
                ],
            },
        ]
    }
    run = DeepSeekWebProvider().parse_response(fixture, request)
    assert run.target_retrieved is ObservationState.YES
    assert run.citations == []
    assert len(run.metadata["anchor_references"]) == 1
    assert run.target_cited is ObservationState.UNKNOWN


def test_markdown_links_become_citations_when_structured_urls_missing(request):
    fixture = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "See [Four Seasons](https://www.fourseasons.com/hongkong/) for details.",
                        "annotations": [],
                    }
                ],
            }
        ]
    }
    run = OpenAIWebProvider().parse_response(fixture, request)
    assert len(run.citations) == 1
    assert run.target_cited is ObservationState.YES
    assert run.citations[0].metadata["citation_origin"] == "markdown_link"


def test_parse_markdown_link_citations_deduplicates(request):
    text = (
        "Read [A](https://example.com/a) and again [B](https://example.com/a) in the answer."
    )
    citations = parse_markdown_link_citations(OpenAIWebProvider(), request, text)
    assert len(citations) == 1
