import pytest

from core.enums import MatchMode, ObservationState
from core.models import GroundingRequest, Target
from providers.deepseek_web import DeepSeekWebProvider
from providers.openai_web import OpenAIWebProvider
from providers.responses_parsing import (
    collect_search_sources,
    extract_query_text,
    extract_url,
    normalize_generated_query,
    parse_markdown_link_citations,
)


@pytest.fixture
def request():
    return GroundingRequest(
        run_id="test-run",
        input_phrase="best luxury hotels in hong kong",
        targets=[Target("fourseasons.com", MatchMode.ROOT_DOMAIN)],
    )


def test_normalize_generated_query_strips_ws_call_id_suffix():
    assert (
        normalize_generated_query("香港四季酒店 米其林 ws_call_id=call_00_abc")
        == "香港四季酒店 米其林"
    )
    assert normalize_generated_query("ws_call_id=call_only") is None
    assert normalize_generated_query("[object Object]") is None


def test_extract_query_text_reads_nested_query_objects():
    assert extract_query_text({"query": "Four Seasons Hong Kong"}) == "Four Seasons Hong Kong"
    assert extract_query_text({"search_query": "luxury hotels"}) == "luxury hotels"
    assert extract_query_text([{"query": "ignored in list"}]) is None


def test_collect_search_sources_reads_open_page_url():
    item = {
        "type": "web_search_call",
        "status": "completed",
        "action": {
            "type": "open_page",
            "url": "https://www.fourseasons.com/zh/hongkong/#ws_call_id=call_01",
        },
    }
    records, fields = collect_search_sources(item)
    assert extract_url(records[0]) == "https://www.fourseasons.com/zh/hongkong/#ws_call_id=call_01"
    assert records[0]["source_origin"] == "open_page"
    assert "action" in fields


def test_deepseek_open_page_urls_support_retrieval_without_citations(request):
    fixture = {
        "output": [
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {
                    "type": "search",
                    "queries": [
                        {"query": "Four Seasons Hotel Hong Kong"},
                        {"query": "香港四季酒店 ws_call_id=call_00_bad"},
                    ],
                },
            },
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {
                    "type": "open_page",
                    "url": "https://www.fourseasons.com/zh/hongkong/",
                },
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "香港四季酒店位於中環。",
                        "annotations": [],
                    }
                ],
            },
        ]
    }
    run = DeepSeekWebProvider().parse_response(fixture, request)
    assert run.target_retrieved is ObservationState.YES
    assert run.target_cited is ObservationState.NO
    assert [item.query for item in run.generated_queries] == ["Four Seasons Hotel Hong Kong", "香港四季酒店"]
    opened = [source for source in run.sources if source.metadata.get("source_origin") == "open_page"]
    assert len(opened) == 1
    assert run.metadata["parsing_summary"]["opened_page_count"] == 1


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
