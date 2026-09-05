from __future__ import annotations

from time import perf_counter
from typing import Any

from core.enums import ObservationState
from core.models import GeneratedQuery, GroundingRequest, ProviderCapabilities, ProviderField, utc_now

from .base import CANONICAL_INSTRUCTION, GroundingProvider, as_plain_data


class GeminiProvider(GroundingProvider):
    id = "gemini"
    name = "Gemini + Google Search"
    default_model = "gemini-3.6-flash"
    api_version = "v1"
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

        started = perf_counter()
        model = config.get("model") or self.default_model
        client = genai.Client(
            api_key=config["api_key"],
            http_options={"api_version": self.api_version},
        )
        response = client.interactions.create(
            model=model,
            input=CANONICAL_INSTRUCTION.format(query=request.input_phrase),
            tools=[{"type": "google_search", "search_types": ["web_search"]}],
        )
        run = self.parse_response(response, request, model)
        run.latency_ms = round((perf_counter() - started) * 1000)
        run.finished_at = utc_now()
        return run

    def parse_response(self, raw_response: Any, request: GroundingRequest, model: str | None = None):
        raw = as_plain_data(raw_response) or {}
        run = self.new_run(request, model)
        run.raw_response = raw
        steps = raw.get("steps") or [] if isinstance(raw, dict) else []
        text_parts: list[str] = []
        suggestions: list[str] = []
        search_calls = 0

        for step_index, step in enumerate(steps):
            step_type = step.get("type")
            if step_type == "google_search_call":
                search_calls += 1
                arguments = step.get("arguments") or {}
                for query in arguments.get("queries") or []:
                    if query:
                        run.generated_queries.append(
                            GeneratedQuery(
                                str(query),
                                len(run.generated_queries) + 1,
                                {
                                    "call_id": step.get("id"),
                                    "search_type": step.get("search_type"),
                                },
                            )
                        )
            elif step_type == "google_search_result":
                for result in step.get("result") or []:
                    markup = result.get("search_suggestions")
                    if markup:
                        suggestions.append(markup)
            elif step_type == "model_output":
                for content_index, content in enumerate(step.get("content") or []):
                    if content.get("type") != "text":
                        continue
                    text = content.get("text") or ""
                    text_parts.append(text)
                    for annotation in content.get("annotations") or []:
                        if annotation.get("type") != "url_citation" or not annotation.get("url"):
                            continue
                        start = annotation.get("start_index")
                        end = annotation.get("end_index")
                        run.citations.append(
                            self.build_citation(
                                request,
                                annotation["url"],
                                title=annotation.get("title"),
                                start_index=start,
                                end_index=end,
                                cited_text=_utf8_slice(text, start, end),
                                metadata={
                                    "step_index": step_index,
                                    "content_index": content_index,
                                },
                            )
                        )

        run.response_text = "\n".join(part for part in text_parts if part) or getattr(
            raw_response, "output_text", None
        )
        run.search_performed = (
            ObservationState.YES
            if search_calls
            else ObservationState.NO
            if steps
            else ObservationState.UNKNOWN
        )
        run.metadata = {
            "actual_prompt": CANONICAL_INSTRUCTION.format(query=request.input_phrase),
            "market_requested": request.market,
            "market_applied": False,
            "language_requested": request.language,
            "language_applied": False,
            "usage": raw.get("usage"),
            "interaction_id": raw.get("id"),
            "response_status": raw.get("status"),
            "actual_model": raw.get("model"),
            "search_call_count": search_calls,
            "search_suggestions": suggestions,
            "retrieval_note": (
                "Gemini Interactions does not expose raw SERP rows or a complete "
                "retrieved-source list; citations must not be treated as retrieval."
            ),
        }
        return self.finish_states(run, retrieval_complete=False)


def _utf8_slice(text: str, start: Any, end: Any) -> str | None:
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    try:
        return text.encode("utf-8")[start:end].decode("utf-8")
    except UnicodeDecodeError:
        return None
