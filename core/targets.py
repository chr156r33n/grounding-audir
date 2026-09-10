from __future__ import annotations

from .brand_match import compile_brand_regex, match_brand
from .citation_redirects import should_resolve_citation_redirects
from .enums import MatchMode, ObservationState, TargetCategory
from .matching import is_grounding_redirect_url
from .models import GroundingRequest, GroundingRun, PropertyResult, Target

MAX_MONITOR_PROPERTIES = 5
CATEGORY_LABELS = {
    TargetCategory.OWNED: "Owned",
    TargetCategory.OF_INTEREST: "Of interest",
    TargetCategory.COMPETITION: "Competition",
}


def display_label(target: Target) -> str:
    return (target.label or "").strip() or target.value


def parse_target_category(value: str | TargetCategory | None) -> TargetCategory:
    if isinstance(value, TargetCategory):
        return value
    normalized = str(value or TargetCategory.OWNED.value).strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "owned": TargetCategory.OWNED,
        "of_interest": TargetCategory.OF_INTEREST,
        "interest": TargetCategory.OF_INTEREST,
        "competition": TargetCategory.COMPETITION,
        "competitor": TargetCategory.COMPETITION,
        "competitors": TargetCategory.COMPETITION,
    }
    return aliases.get(normalized, TargetCategory.OWNED)


def normalize_targets(targets: list[Target]) -> list[Target]:
    normalized: list[Target] = []
    seen: set[str] = set()
    for target in targets:
        value = str(target.value or "").strip()
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(
            Target(
                value=value,
                match_mode=target.match_mode,
                label=str(target.label or "").strip(),
                category=parse_target_category(target.category),
                brand_regex=str(target.brand_regex or "").strip(),
            )
        )
    return normalized


def validate_targets(targets: list[Target]) -> list[Target]:
    normalized = normalize_targets(targets)
    if not normalized:
        raise ValueError("Add at least one property to monitor.")
    if len(normalized) > MAX_MONITOR_PROPERTIES:
        raise ValueError(f"At most {MAX_MONITOR_PROPERTIES} properties are supported.")
    for target in normalized:
        compile_brand_regex(target.brand_regex or None)
    return normalized


def _property_retrieved(
    run: GroundingRun,
    target: Target,
    *,
    retrieval_complete: bool,
) -> ObservationState:
    if any(target.value in source.target_matches for source in run.sources):
        return ObservationState.YES
    return ObservationState.NO if retrieval_complete else ObservationState.UNKNOWN


def _property_cited(
    run: GroundingRun,
    target: Target,
    *,
    citation_complete: bool,
    resolve_redirects: bool,
    has_failed_redirects: bool,
) -> ObservationState:
    if any(target.value in citation.target_matches for citation in run.citations):
        return ObservationState.YES
    if (
        target.match_mode is MatchMode.URL_PREFIX
        and resolve_redirects
        and has_failed_redirects
    ):
        return ObservationState.UNKNOWN
    return ObservationState.NO if citation_complete else ObservationState.UNKNOWN


def compute_property_results(
    run: GroundingRun,
    request: GroundingRequest,
    *,
    retrieval_complete: bool = False,
    citation_complete: bool = True,
) -> list[PropertyResult]:
    resolve_redirects = should_resolve_citation_redirects(request)
    has_failed_redirects = any(
        is_grounding_redirect_url(citation.url)
        and citation.metadata.get("redirect_resolution") == "failed"
        for citation in run.citations
    )
    results: list[PropertyResult] = []
    for target in request.targets:
        brand_state, brand_matches = match_brand(run.response_text, target.brand_regex or None)
        results.append(
            PropertyResult(
                value=target.value,
                label=display_label(target),
                category=target.category,
                retrieved=_property_retrieved(
                    run,
                    target,
                    retrieval_complete=retrieval_complete,
                ),
                cited=_property_cited(
                    run,
                    target,
                    citation_complete=citation_complete,
                    resolve_redirects=resolve_redirects,
                    has_failed_redirects=has_failed_redirects,
                ),
                brand_mentioned=brand_state,
                brand_matches=tuple(brand_matches),
            )
        )
    return results


def aggregate_target_state(
    results: list[PropertyResult],
    field: str,
    *,
    prefer_category: TargetCategory | None = None,
) -> ObservationState:
    if not results:
        return ObservationState.UNKNOWN
    scoped = (
        [item for item in results if item.category is prefer_category]
        if prefer_category is not None
        else results
    ) or results
    states = [getattr(item, field) for item in scoped]
    if any(state is ObservationState.YES for state in states):
        return ObservationState.YES
    if any(state is ObservationState.UNKNOWN for state in states):
        return ObservationState.UNKNOWN
    if all(state is ObservationState.NOT_APPLICABLE for state in states):
        return ObservationState.NOT_APPLICABLE
    return ObservationState.NO


def property_results_to_dict(results: list[PropertyResult]) -> list[dict[str, object]]:
    return [
        {
            "value": item.value,
            "label": item.label,
            "category": item.category.value,
            "retrieved": item.retrieved.value,
            "cited": item.cited.value,
            "brandMentioned": item.brand_mentioned.value,
            "brandMatches": list(item.brand_matches),
        }
        for item in results
    ]
