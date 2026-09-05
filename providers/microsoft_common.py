from __future__ import annotations

from typing import Any

from core.enums import ObservationState
from core.models import GeneratedQuery, GroundingRequest

from .base import CANONICAL_INSTRUCTION, GroundingProvider, as_plain_data


class StaticTokenCredential:
    """Minimal Azure TokenCredential for a user-supplied short-lived bearer token."""

    def __init__(self, token: str):
        self._token = token

    def get_token(self, *_scopes: str, **_kwargs: Any):
        from azure.core.credentials import AccessToken

        # User-provided tokens are expected to be refreshed between runs.
        return AccessToken(self._token, 2**31 - 1)


def azure_credential(config: dict[str, Any]):
    token = str(config.get("azure_token", "")).strip()
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
):
    raw = as_plain_data(raw_response) or {}
    run = provider.new_run(request, model)
    run.raw_response = raw
    output = raw.get("output") or [] if isinstance(raw, dict) else []
    search_calls = 0

    for item in output:
        item_type = str(item.get("type", ""))
        if item_type in {"web_search_call", "bing_grounding_call"}:
            search_calls += 1
            action = item.get("action") or {}
            query = action.get("query")
            queries = action.get("queries") or ([query] if query else [])
            for query_value in queries:
                if query_value:
                    run.generated_queries.append(
                        GeneratedQuery(str(query_value), len(run.generated_queries) + 1)
                    )

        if item_type == "message":
            for content in item.get("content") or []:
                if content.get("type") not in {"output_text", "text"}:
                    continue
                text = content.get("text") or ""
                run.response_text = f"{run.response_text or ''}{text}" or None
                for annotation in content.get("annotations") or []:
                    if annotation.get("type") not in {"url_citation", "citation"}:
                        continue
                    url = annotation.get("url")
                    if not url:
                        continue
                    start = annotation.get("start_index")
                    end = annotation.get("end_index")
                    run.citations.append(
                        provider.build_citation(
                            request,
                            url,
                            title=annotation.get("title"),
                            start_index=start,
                            end_index=end,
                            cited_text=(
                                text[start:end]
                                if isinstance(start, int) and isinstance(end, int)
                                else None
                            ),
                            metadata={
                                key: value
                                for key, value in annotation.items()
                                if key not in {"type", "url", "title", "start_index", "end_index"}
                            },
                        )
                    )

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
    }
    return provider.finish_states(run, retrieval_complete=False)
