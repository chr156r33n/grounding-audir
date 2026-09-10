from core.enums import MatchMode, ObservationState, ProviderType, TargetCategory
from core.models import Citation, GroundingRequest, GroundingRun, Target
from core.targets import (
    aggregate_target_state,
    compute_property_results,
    normalize_targets,
    validate_targets,
)


def _request(*targets: Target) -> GroundingRequest:
    return GroundingRequest(
        run_id="run-1",
        input_phrase="luxury hotel tokyo",
        targets=list(targets),
    )


def test_validate_targets_limits_to_five():
    targets = [
        Target(f"example{i}.com", category=TargetCategory.OWNED) for i in range(6)
    ]
    try:
        validate_targets(targets)
    except ValueError as exc:
        assert "5 properties" in str(exc)
    else:
        raise AssertionError("expected ValueError")


def test_compute_property_results_per_target():
    owned = Target("owned.example", category=TargetCategory.OWNED)
    competitor = Target("competitor.example", category=TargetCategory.COMPETITION)
    request = _request(owned, competitor)
    run = GroundingRun(
        run_id="run-1",
        provider_id="openai_web",
        provider_name="OpenAI",
        provider_type=ProviderType.GROUNDING,
        input_phrase=request.input_phrase,
        citations=[
            Citation(url="https://owned.example/page", target_matches=["owned.example"]),
        ],
    )
    results = compute_property_results(run, request, citation_complete=True)
    assert len(results) == 2
    owned_result = next(item for item in results if item.value == "owned.example")
    competitor_result = next(item for item in results if item.value == "competitor.example")
    assert owned_result.cited is ObservationState.YES
    assert competitor_result.cited is ObservationState.NO
    assert aggregate_target_state(results, "cited") is ObservationState.YES


def test_normalize_targets_deduplicates_values():
    normalized = normalize_targets(
        [
            Target("Example.com"),
            Target("example.com", category=TargetCategory.COMPETITION),
        ]
    )
    assert len(normalized) == 1
    assert normalized[0].value == "Example.com"


def test_property_cited_unknown_when_url_prefix_redirect_fails():
    target = Target(
        "https://www.example.com/prefix/",
        match_mode=MatchMode.URL_PREFIX,
        category=TargetCategory.OWNED,
    )
    request = GroundingRequest(
        run_id="run-1",
        input_phrase="query",
        targets=[target],
        provider_options={"resolve_citation_redirects": True},
    )
    run = GroundingRun(
        run_id="run-1",
        provider_id="gemini",
        provider_name="Gemini",
        provider_type=ProviderType.GROUNDING,
        input_phrase="query",
        citations=[
            Citation(
                url="https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc",
                metadata={"redirect_resolution": "failed"},
            )
        ],
    )
    results = compute_property_results(run, request, citation_complete=True)
    assert results[0].cited is ObservationState.UNKNOWN
