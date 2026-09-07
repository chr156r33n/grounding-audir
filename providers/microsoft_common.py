from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote_plus

from core.enums import ObservationState
from core.models import GeneratedQuery, GroundingRequest

from .base import CANONICAL_INSTRUCTION, GroundingProvider, as_plain_data
from .responses_parsing import (
    RESPONSES_INCLUDE_FIELDS,
    URL_FIELD_KEYS,
    collect_search_sources,
    extract_title,
    extract_url,
    parse_markdown_link_citations,
    parse_structured_annotations,
)


class StaticTokenCredential:
    """Minimal Azure TokenCredential for a user-supplied short-lived bearer token."""

    def __init__(self, token: str):
        self._token = token

    def get_token(self, *_scopes: str, **_kwargs: Any):
        from azure.core.credentials import AccessToken

        # User-provided tokens are expected to be refreshed between runs.
        return AccessToken(self._token, 2**31 - 1)


def normalize_azure_token(raw: str) -> str:
    value = str(raw or "").strip()
    if not value:
        return ""
    if value.lower().startswith("bearer "):
        value = value[7:].strip()
    if value.startswith("{") and value.endswith("}"):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            for key in ("accessToken", "access_token", "token"):
                token = parsed.get(key)
                if isinstance(token, str) and token.strip():
                    return token.strip()
    return value.splitlines()[0].strip().strip('"').strip("'")


def azure_credential(config: dict[str, Any]):
    token = normalize_azure_token(str(config.get("azure_token", "")))
    if token:
        return StaticTokenCredential(token)
    from azure.identity import DefaultAzureCredential

    return DefaultAzureCredential(exclude_interactive_browser_credential=True)


def parse_responses_result(
    provider: GroundingProvider,
    raw_response: Any,
    request: GroundingRequest,
    model: str | None,
    retrieval_note: str,
    sources_supported: bool = False,
):
    raw = as_plain_data(raw_response) or {}
    run = provider.new_run(request, model)
    run.raw_response = raw
    output = raw.get("output") or [] if isinstance(raw, dict) else []
    search_calls = 0
    sources_observable = False
    source_fields_observed: list[str] = []
    source_map: dict[str, Any] = {}
    anchor_references: list[dict[str, Any]] = []
    structured_citation_count = 0
    markdown_citation_count = 0

    for output_index, item in enumerate(output):
        item_type = str(item.get("type", ""))
        is_search_item = item_type in {"web_search_call", "bing_grounding_call"} or str(
            item.get("name", "")
        ) in {"web_search", "bing_grounding"}
        if is_search_item:
            search_calls += 1
            action = item.get("action") or {}
            arguments = item.get("arguments")
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except (TypeError, ValueError):
                    arguments = {}
            records = _query_records(action) + _query_records(arguments)
            seen_in_call: set[tuple[str, str | None]] = set()
            for query_value, query_url in records:
                query_url_constructed = False
                if not query_url and provider.id == "microsoft_bing":
                    query_url = f"https://www.bing.com/search?q={quote_plus(query_value)}"
                    query_url_constructed = True
                key = (query_value, query_url)
                if key in seen_in_call:
                    continue
                seen_in_call.add(key)
                query_metadata = {
                    "call_id": item.get("call_id") or item.get("id"),
                    "status": item.get("status"),
                }
                if query_url:
                    query_metadata["query_url"] = query_url
                    query_metadata["query_url_constructed"] = query_url_constructed
                run.generated_queries.append(
                    GeneratedQuery(
                        query_value,
                        len(run.generated_queries) + 1,
                        query_metadata,
                    )
                )
            if sources_supported and "sources" in action:
                sources_observable = True
            source_records, observed_fields = collect_search_sources(item)
            if observed_fields:
                sources_observable = True
                source_fields_observed.extend(observed_fields)
            if sources_supported:
                for source in source_records:
                    url = extract_url(source)
                    if not url:
                        continue
                    built = provider.build_source(
                        request,
                        url,
                        title=extract_title(source),
                        position=len(run.sources) + 1,
                        metadata={
                            key: value
                            for key, value in source.items()
                            if key not in URL_FIELD_KEYS and key != "title"
                        },
                    )
                    key = built.normalized_url or built.raw_url
                    if key not in source_map:
                        source_map[key] = built
                        run.sources.append(built)

        if item_type == "message":
            for content_index, content in enumerate(item.get("content") or []):
                if content.get("type") not in {"output_text", "text"}:
                    continue
                text = content.get("text") or ""
                run.response_text = f"{run.response_text or ''}{text}" or None
                structured, anchors = parse_structured_annotations(
                    provider,
                    request,
                    text=text,
                    annotations=content.get("annotations") or [],
                    output_index=output_index,
                    content_index=content_index,
                )
                structured_citation_count += len(structured)
                anchor_references.extend(anchors)
                for citation in structured:
                    run.citations.append(citation)
                    source_key = provider.build_source(request, citation.url).normalized_url or citation.url
                    if source_key in source_map:
                        source_map[source_key].cited = ObservationState.YES

    if run.response_text and not structured_citation_count:
        markdown_citations = parse_markdown_link_citations(
            provider,
            request,
            run.response_text,
        )
        markdown_citation_count = len(markdown_citations)
        run.citations.extend(markdown_citations)

    run.response_text = run.response_text or raw.get("output_text")
    run.search_performed = ObservationState.YES if search_calls else ObservationState.NO
    run.metadata = {
        "actual_prompt": CANONICAL_INSTRUCTION.format(query=request.input_phrase),
        "search_call_count": search_calls,
        "unique_generated_query_count": len({item.query for item in run.generated_queries}),
        "market_requested": request.market,
        "language_requested": request.language,
        "usage": raw.get("usage"),
        "retrieval_note": retrieval_note,
        "sources_observable": sources_observable,
        "sources_requested": sources_supported,
        "include_fields": list(RESPONSES_INCLUDE_FIELDS) if sources_supported else [],
        "source_fields_observed": sorted(set(source_fields_observed)),
        "anchor_references": anchor_references,
        "parsing_summary": {
            "structured_citations_with_url": structured_citation_count,
            "markdown_citations": markdown_citation_count,
            "anchor_references_without_url": len(anchor_references),
            "observed_source_count": len(run.sources),
        },
        "citation_urls_observable": bool(structured_citation_count or markdown_citation_count),
        "response_id": raw.get("id"),
        "response_status": raw.get("status"),
        "actual_model": raw.get("model"),
        "service_tier": raw.get("service_tier"),
        "incomplete_details": raw.get("incomplete_details"),
    }
    citation_complete = not anchor_references or bool(run.citations)
    return provider.finish_states(
        run,
        retrieval_complete=sources_supported and sources_observable,
        citation_complete=citation_complete,
    )


def _query_records(value: Any) -> list[tuple[str, str | None]]:
    records: list[tuple[str, str | None]] = []
    if isinstance(value, dict):
        query_url = next(
            (
                item
                for key, item in value.items()
                if key.lower() in {"query_url", "search_query_url", "bing_search_url"}
                and isinstance(item, str)
            ),
            None,
        )
        for key, item in value.items():
            normalized_key = key.lower()
            if normalized_key in {"query", "search_query"} and isinstance(item, str):
                records.append((item, query_url))
            elif normalized_key in {"queries", "search_queries"} and isinstance(item, list):
                for nested in item:
                    if isinstance(nested, str):
                        records.append((nested, None))
                    else:
                        records.extend(_query_records(nested))
            elif isinstance(item, (dict, list)):
                records.extend(_query_records(item))
    elif isinstance(value, list):
        for item in value:
            records.extend(_query_records(item))
    return records
