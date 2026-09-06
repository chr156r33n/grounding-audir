from __future__ import annotations

from time import perf_counter
from typing import Any

from core.models import GroundingRequest, ProviderCapabilities, ProviderField, utc_now

from core.diagnostics import attach_observation_diagnostics
from .base import CANONICAL_INSTRUCTION, GroundingProvider
from .microsoft_common import parse_responses_result


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
        run = parse_responses_result(
            self,
            raw_response,
            request,
            model,
            (
                "OpenAI Web Search was asked to include consulted sources via "
                'include=["web_search_call.action.sources"]. Target retrieval remains '
                "UNKNOWN if that field is absent from the response."
            ),
            sources_supported=True,
        )
        run.metadata["market_applied"] = bool(_market_country(request.market))
        run.metadata["language_applied"] = False
        run.metadata["sources_requested"] = True
        run.metadata["include_fields"] = ["web_search_call.action.sources"]
        return attach_observation_diagnostics(run)


def _market_country(market: str | None) -> str | None:
    if not market:
        return None
    parts = market.replace("_", "-").split("-")
    return parts[-1].upper() if len(parts) > 1 and len(parts[-1]) == 2 else None
