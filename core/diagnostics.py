from __future__ import annotations

from core.enums import ObservationState, ProviderType, RunStatus
from core.models import GroundingRun

_OBSERVATION_FIELDS = (
    ("search_performed", "Search performed"),
    ("target_retrieved", "Target retrieved"),
    ("target_cited", "Target cited"),
)


def attach_observation_diagnostics(run: GroundingRun) -> GroundingRun:
    """Add human-readable reasons for each observation state on the run metadata."""
    run.metadata["state_notes"] = build_state_notes(run)
    return run


def build_state_notes(run: GroundingRun) -> dict[str, str]:
    notes: dict[str, str] = {}
    if run.error or run.status != RunStatus.COMPLETE:
        failure = run.error.safe_message if run.error else f"Run status is {run.status.value}."
        if run.status is RunStatus.TIMED_OUT:
            timeout = run.metadata.get("timeout_seconds")
            retry_count = run.metadata.get("retry_count", 0)
            timeout_hint = (
                f"Application deadline: {timeout:g}s."
                if isinstance(timeout, (int, float))
                else "Application deadline reached."
            )
            retry_hint = (
                f" Retry attempts before timeout: {retry_count}."
                if retry_count
                else ""
            )
            failure = f"{failure} {timeout_hint}{retry_hint}"
        for field, _label in _OBSERVATION_FIELDS:
            if getattr(run, field) == ObservationState.UNKNOWN:
                notes[field] = (
                    f"Left UNKNOWN because the provider run did not finish successfully: {failure}"
                )
        return notes

    notes["search_performed"] = _search_note(run)
    notes["target_retrieved"] = _retrieval_note(run)
    notes["target_cited"] = _citation_note(run)
    return {key: value for key, value in notes.items() if value}


def unknown_observation_fields(run: GroundingRun) -> list[tuple[str, str]]:
    return [
        (field, label)
        for field, label in _OBSERVATION_FIELDS
        if getattr(run, field) == ObservationState.UNKNOWN
    ]


def _search_note(run: GroundingRun) -> str:
    state = run.search_performed
    search_calls = run.metadata.get("search_call_count")
    if state is ObservationState.YES:
        count = search_calls if isinstance(search_calls, int) else "one or more"
        return f"At least one web search call was present in the response ({count} call(s) parsed)."
    if state is ObservationState.NO:
        if search_calls == 0:
            return "No web search call was found in the provider response output."
        return "Search was not observed in the parsed provider response."
    return "Search activity could not be determined from the provider response."


def _retrieval_note(run: GroundingRun) -> str:
    state = run.target_retrieved
    retrieval_note = run.metadata.get("retrieval_note")
    sources_observable = run.metadata.get("sources_observable")
    source_count = len(run.sources)
    matching_sources = sum(1 for source in run.sources if source.target_matches)

    if state is ObservationState.YES:
        return (
            f"The target matched {matching_sources} of {source_count} observed source URL(s) "
            "returned by the provider."
        )
    if state is ObservationState.NO:
        if source_count:
            return (
                f"The provider exposed {source_count} consulted source URL(s), and none matched "
                "the configured target."
            )
        if sources_observable is True:
            return (
                "The provider returned an empty consulted-source list "
                "(web_search_call.action.sources was present but contained no URLs)."
            )
        if run.provider_type is ProviderType.RETRIEVAL and source_count == 0:
            return "The retrieval API returned no web results for this query."
        return "Retrieval evidence was complete enough to conclude the target was not retrieved."

    if retrieval_note:
        base = str(retrieval_note)
    elif sources_observable is False and run.search_performed is ObservationState.YES:
        include_fields = run.metadata.get("include_fields") or [
            "web_search_call.action.sources"
        ]
        base = (
            "Search ran, but the response omitted the consulted-source field "
            f"({', '.join(include_fields)}). Without that field, the app cannot confirm or "
            "rule out target retrieval."
        )
    elif run.search_performed is ObservationState.NO:
        base = (
            "No search call was parsed, so there is no retrieval evidence to inspect."
        )
    else:
        base = "The provider did not expose enough retrieval evidence to decide YES or NO."

    if sources_observable is False and run.metadata.get("sources_requested"):
        base += (
            " The request asked for consulted sources; check Provider metadata for "
            "sources_observable=false and inspect the raw response."
        )
    return base


def _citation_note(run: GroundingRun) -> str:
    state = run.target_cited
    citation_count = len(run.citations)
    matching_citations = sum(1 for citation in run.citations if citation.target_matches)

    if state is ObservationState.NOT_APPLICABLE:
        return (
            run.metadata.get("retrieval_note")
            or "This provider exposes retrieval evidence only; citations are not applicable."
        )
    if state is ObservationState.YES:
        return (
            f"The target matched {matching_citations} of {citation_count} citation URL(s) "
            "in the provider response."
        )
    if state is ObservationState.NO:
        if citation_count:
            return (
                f"The provider returned {citation_count} citation URL(s), and none matched "
                "the configured target."
            )
        return "No URL citations were exposed in the provider response."
    if citation_count:
        return (
            f"{citation_count} citation URL(s) were parsed, but citation completeness is "
            "unknown for this provider response."
        )
    return "Citation attribution could not be determined from the provider response."
