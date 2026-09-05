from __future__ import annotations

from time import perf_counter
from typing import Any

from core.enums import ObservationState
from core.models import GeneratedQuery, GroundingRequest, ProviderCapabilities, ProviderField, utc_now

from .base import CANONICAL_INSTRUCTION, GroundingProvider, as_plain_data


class GeminiProvider(GroundingProvider):
    id = "gemini"
    name = "Gemini + Google Search"
    default_model = "gemini-2.5-flash"
    fields = (
        ProviderField("api_key", "Gemini API key", secret=True),
        ProviderField("model", "Model", required=True, default=default_model),
    )
    capabilities = ProviderCapabilities(
        generated_queries=True,
        retrieved_sources=False,
        grounding_content=False,
        citations=True,
        market_control=False,
        language_control=False,
        can_force_search=False,
    )

    def run(self, request: GroundingRequest, config: dict[str, Any]):
        from google import genai
        from google.genai import types

        started = perf_counter()
        model = config.get("model") or self.default_model
        client = genai.Client(api_key=config["api_key"])
        response = client.models.generate_content(
            model=model,
            contents=CANONICAL_INSTRUCTION.format(query=request.input_phrase),
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())],
            ),
        )
        run = self.parse_response(response, request, model)
        run.latency_ms = round((perf_counter() - started) * 1000)
        run.finished_at = utc_now()
        return run

    def parse_response(self, raw_response: Any, request: GroundingRequest, model: str | None = None):
        raw = as_plain_data(raw_response) or {}
        run = self.new_run(request, model)
        run.raw_response = raw
        run.response_text = _response_text(raw_response, raw)
        candidate = ((raw.get("candidates") or [{}])[0]) if isinstance(raw, dict) else {}
        metadata = candidate.get("grounding_metadata") or candidate.get("groundingMetadata") or {}

        queries = metadata.get("web_search_queries") or metadata.get("webSearchQueries") or []
        run.generated_queries = [
            GeneratedQuery(str(query), index + 1)
            for index, query in enumerate(queries)
            if query
        ]

        chunks = metadata.get("grounding_chunks") or metadata.get("groundingChunks") or []
        for chunk in chunks:
            web = chunk.get("web") or {}
            url = web.get("uri") or web.get("url")
            if url:
                run.citations.append(
                    self.build_citation(
                        request,
                        url,
                        title=web.get("title"),
                        metadata={"source": "grounding_chunk"},
                    )
                )

        supports = metadata.get("grounding_supports") or metadata.get("groundingSupports") or []
        for support in supports:
            segment = support.get("segment") or {}
            for index in support.get("grounding_chunk_indices", support.get("groundingChunkIndices", [])):
                if isinstance(index, int) and 0 <= index < len(run.citations):
                    citation = run.citations[index]
                    citation.start_index = segment.get("start_index", segment.get("startIndex"))
                    citation.end_index = segment.get("end_index", segment.get("endIndex"))
                    citation.cited_text = segment.get("text")

        run.search_performed = (
            ObservationState.YES
            if queries or chunks or metadata.get("search_entry_point") or metadata.get("searchEntryPoint")
            else ObservationState.UNKNOWN
        )
        run.metadata = {
            "actual_prompt": CANONICAL_INSTRUCTION.format(query=request.input_phrase),
            "market_requested": request.market,
            "market_applied": False,
            "language_requested": request.language,
            "language_applied": False,
            "usage": raw.get("usage_metadata") or raw.get("usageMetadata"),
            "retrieval_note": (
                "The selected Gemini API surface does not expose a complete retrieved-source list; "
                "citations must not be treated as the full retrieval set."
            ),
        }
        return self.finish_states(run, retrieval_complete=False)


def _response_text(response: Any, raw: Any) -> str | None:
    text = getattr(response, "text", None)
    if text:
        return text
    if not isinstance(raw, dict):
        return None
    parts = (((raw.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
    values = [part.get("text") for part in parts if isinstance(part, dict) and part.get("text")]
    return "\n".join(values) or None
