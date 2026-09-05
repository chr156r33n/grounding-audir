from __future__ import annotations

from time import perf_counter
from typing import Any

from core.enums import ObservationState
from core.models import GeneratedQuery, GroundingRequest, ProviderCapabilities, ProviderField, utc_now

from .base import CANONICAL_INSTRUCTION, GroundingProvider, as_plain_data


class OpenAIWebProvider(GroundingProvider):
    id = "openai_web"
    name = "OpenAI Web Search"
    default_model = "gpt-5.5"
    fields = (
        ProviderField("api_key", "OpenAI API key", secret=True),
        ProviderField("model", "Model", required=True, default=default_model),
    )
    capabilities = ProviderCapabilities(
        generated_queries=True,
        retrieved_sources=True,
        citations=True,
        market_control=True,
        can_force_search=True,
    )

    def run(self, request: GroundingRequest, config: dict[str, Any]):
        from openai import OpenAI

        started = perf_counter()
        model = config.get("model") or self.default_model
        client = OpenAI(api_key=config["api_key"])
        tool: dict[str, Any] = {"type": "web_search"}
        country = _market_country(request.market)
        if country:
            tool["user_location"] = {"type": "approximate", "country": country}
        response = client.responses.create(
            model=model,
            input=CANONICAL_INSTRUCTION.format(query=request.input_phrase),
            tools=[tool],
            tool_choice="required",
            include=["web_search_call.action.sources"],
        )
        run = self.parse_response(response, request, model)
        run.latency_ms = round((perf_counter() - started) * 1000)
        run.finished_at = utc_now()
        return run

    def parse_response(self, raw_response: Any, request: GroundingRequest, model: str | None = None):
        raw = as_plain_data(raw_response) or {}
        run = self.new_run(request, model)
        run.raw_response = raw
        output = raw.get("output") or [] if isinstance(raw, dict) else []
        source_map: dict[str, Any] = {}
        sources_observable = False
        search_calls = 0
        search_actions = 0

        for output_index, item in enumerate(output):
            if item.get("type") == "web_search_call":
                search_calls += 1
                action = item.get("action") or {}
                if action.get("type") in {None, "search"}:
                    search_actions += 1
                query = action.get("query")
                queries = action.get("queries") or ([query] if query else [])
                for query_value in queries:
                    if query_value:
                        run.generated_queries.append(
                            GeneratedQuery(str(query_value), len(run.generated_queries) + 1)
                        )
                if "sources" in action:
                    sources_observable = True
                for source in action.get("sources") or []:
                    url = source.get("url")
                    if not url:
                        continue
                    built = self.build_source(
                        request,
                        url,
                        title=source.get("title"),
                        position=len(run.sources) + 1,
                        metadata={key: value for key, value in source.items() if key not in {"url", "title"}},
                    )
                    key = built.normalized_url or built.raw_url
                    if key not in source_map:
                        source_map[key] = built
                        run.sources.append(built)

            if item.get("type") == "message":
                for content_index, content in enumerate(item.get("content") or []):
                    if content.get("type") not in {"output_text", "text"}:
                        continue
                    text = content.get("text") or ""
                    if text:
                        run.response_text = f"{run.response_text or ''}{text}"
                    for annotation in content.get("annotations") or []:
                        if annotation.get("type") != "url_citation":
                            continue
                        url = annotation.get("url")
                        if not url:
                            continue
                        citation = self.build_citation(
                            request,
                            url,
                            title=annotation.get("title"),
                            start_index=annotation.get("start_index"),
                            end_index=annotation.get("end_index"),
                            cited_text=None,
                            metadata={
                                "output_index": output_index,
                                "content_index": content_index,
                            },
                        )
                        run.citations.append(citation)
                        key = self.build_source(request, url).normalized_url or url
                        if key in source_map:
                            source_map[key].cited = ObservationState.YES

        run.response_text = run.response_text or raw.get("output_text")
        run.search_performed = ObservationState.YES if search_calls else ObservationState.NO
        run.metadata = {
            "actual_prompt": CANONICAL_INSTRUCTION.format(query=request.input_phrase),
            "search_call_count": search_calls,
            "search_action_count": search_actions,
            "unique_generated_query_count": len({item.query for item in run.generated_queries}),
            "market_requested": request.market,
            "market_applied": bool(_market_country(request.market)),
            "language_requested": request.language,
            "language_applied": False,
            "usage": raw.get("usage"),
            "sources_observable": sources_observable,
            "response_id": raw.get("id"),
            "response_status": raw.get("status"),
            "actual_model": raw.get("model"),
            "service_tier": raw.get("service_tier"),
            "incomplete_details": raw.get("incomplete_details"),
        }
        return self.finish_states(run, retrieval_complete=sources_observable)


def _market_country(market: str | None) -> str | None:
    if not market:
        return None
    parts = market.replace("_", "-").split("-")
    return parts[-1].upper() if len(parts) > 1 and len(parts[-1]) == 2 else None
