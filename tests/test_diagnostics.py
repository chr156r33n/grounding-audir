from core.diagnostics import build_state_notes
from core.enums import ErrorType, MatchMode, ObservationState, RunStatus
from core.models import GroundingRequest, GroundingRun, ProviderError, Target
from providers.openai_web import OpenAIWebProvider


def test_openai_unknown_retrieval_explains_missing_sources():
    request = GroundingRequest(
        run_id="diag",
        input_phrase="best luxury hotels in hong kong",
        targets=[Target("fourseasons.com", MatchMode.ROOT_DOMAIN)],
    )
    fixture = {
        "output": [
            {"type": "web_search_call", "action": {"type": "search", "query": "luxury hotels"}},
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "Try the Peninsula."}],
            },
        ],
        "status": "completed",
    }
    run = OpenAIWebProvider().parse_response(fixture, request)
    assert run.target_retrieved is ObservationState.UNKNOWN
    assert run.metadata["sources_observable"] is False
    note = run.metadata["state_notes"]["target_retrieved"]
    assert "sources" in note.lower()
    assert "unknown" in note.lower() or "cannot confirm" in note.lower()


def test_citation_note_mentions_opened_pages_without_inline_citations(request):
    run = GroundingRun(
        run_id="opened",
        provider_id="deepseek_web",
        provider_name="DeepSeek Web Search",
        provider_type=OpenAIWebProvider.provider_type,
        input_phrase="query",
        target_cited=ObservationState.NO,
        sources=[
            OpenAIWebProvider().build_source(
                request,
                "https://www.fourseasons.com/zh/hongkong/",
                metadata={"source_origin": "open_page"},
            )
        ],
    )
    note = build_state_notes(run)["target_cited"]
    assert "opened" in note.lower()
    assert "inline url citations" in note.lower()


def test_failed_run_unknown_states_include_failure_reason():
    run = GroundingRun(
        run_id="fail",
        provider_id="openai_web",
        provider_name="OpenAI Web Search",
        provider_type=OpenAIWebProvider.provider_type,
        input_phrase="query",
        status=RunStatus.FAILED,
        error=ProviderError(
            type=ErrorType.AUTH_ERROR,
            safe_message="Authentication failed. Check this provider's credentials and access.",
            retryable=False,
        ),
    )
    notes = build_state_notes(run)
    assert "Authentication failed" in notes["target_retrieved"]
    assert "did not finish successfully" in notes["target_retrieved"]


def test_yes_retrieval_note_counts_matches():
    request = GroundingRequest(
        run_id="yes",
        input_phrase="hotels",
        targets=[Target("fourseasons.com", MatchMode.ROOT_DOMAIN)],
    )
    run = OpenAIWebProvider().parse_response(
        {
            "output": [
                {
                    "type": "web_search_call",
                    "action": {
                        "query": "hotels",
                        "sources": [{"url": "https://www.fourseasons.com/hongkong/"}],
                    },
                }
            ]
        },
        request,
    )
    assert run.target_retrieved is ObservationState.YES
    assert "matched 1 of 1" in run.metadata["state_notes"]["target_retrieved"]
