from __future__ import annotations

from time import perf_counter
from typing import Any

from core.diagnostics import attach_observation_diagnostics
from core.enums import ObservationState, ProviderType
from core.models import (
    GeneratedQuery,
    GroundingContent,
    GroundingRequest,
    ProviderCapabilities,
    ProviderField,
    utc_now,
)

from .base import GroundingProvider, as_plain_data


class MicrosoftWebIQProvider(GroundingProvider):
    id = "microsoft_web_iq"
    name = "Microsoft Web IQ"
    provider_type = ProviderType.RETRIEVAL
    default_model = "web-search"
    api_version = "v1"
    fields = (
        ProviderField("api_key", "Web IQ API key", secret=True),
        ProviderField("max_results", "Max results", required=False, default="10"),
    )
    capabilities = ProviderCapabilities(
        generated_queries=False,
        retrieved_sources=True,
        grounding_content=True,
        citations=False,
        market_control=True,
        language_control=True,
        response_text=False,
    )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors = super().validate_config(config)
        try:
            count = int(config.get("max_results") or 10)
            if not 1 <= count <= 50:
                errors.append("Web IQ max results must be between 1 and 50.")
        except (TypeError, ValueError):
            errors.append("Web IQ max results must be an integer.")
        return errors

    def run(self, request: GroundingRequest, config: dict[str, Any]):
        from webiq import WebIQClient
        from webiq.types import ContentFormat

        started = perf_counter()
        language, region = _locale(request)
        with WebIQClient(api_key=config["api_key"]) as client:
            response = client.web.search(
                request.input_phrase,
                max_results=max(1, min(int(config.get("max_results") or 10), 50)),
                language=language,
                region=region,
                content_format=ContentFormat.passage,
            )
        run = self.parse_response(response, request)
        run.latency_ms = round((perf_counter() - started) * 1000)
        run.finished_at = utc_now()
        return run

    def parse_response(self, raw_response: Any, request: GroundingRequest, model: str | None = None):
        raw = as_plain_data(raw_response) or {}
        run = self.new_run(request, model)
        run.raw_response = raw
        results = raw.get("webResults") or raw.get("web_results") or []
        run.generated_queries = [
            GeneratedQuery(request.input_phrase, 1, {"source": "input_phrase"})
        ]
        for index, item in enumerate(results, start=1):
            url = item.get("url")
            if not url:
                continue
            content = item.get("content")
            run.sources.append(
                self.build_source(
                    request,
                    url,
                    title=item.get("title"),
                    snippet=_snippet(content),
                    content=content,
                    position=index,
                    metadata={
                        key: value
                        for key, value in item.items()
                        if key not in {"url", "title", "content"}
                    },
                )
            )
            if content:
                run.grounding_content.append(
                    GroundingContent(
                        text=content,
                        source_url=url,
                        source_index=index,
                        metadata={"content_tier": item.get("contentTier")},
                    )
                )
        run.search_performed = (
            ObservationState.YES
            if results
            else ObservationState.NO
            if raw
            else ObservationState.UNKNOWN
        )
        language, region = _locale(request)
        run.metadata = {
            "market_requested": request.market,
            "market_applied": bool(region),
            "language_requested": request.language,
            "language_applied": bool(language),
            "result_count": len(results),
            "retrieval_note": (
                "Microsoft Web IQ returns ranked passage-level web results. "
                "This is retrieval evidence, not a model-generated citation layer."
            ),
        }
        run = self.finish_states(run, retrieval_complete=True, citation_complete=False)
        run.target_cited = ObservationState.NOT_APPLICABLE
        return attach_observation_diagnostics(run)


def _locale(request: GroundingRequest) -> tuple[str | None, str | None]:
    language = request.language
    region = None
    if request.market:
        parts = request.market.replace("_", "-").split("-")
        if len(parts) > 1 and len(parts[-1]) == 2:
            region = parts[-1].upper()
            language = language or parts[0].lower()
    return language, region


def _snippet(content: str | None, limit: int = 240) -> str | None:
    if not content:
        return None
    text = " ".join(content.split())
    return text if len(text) <= limit else f"{text[: limit - 1]}…"
