from __future__ import annotations

from time import perf_counter
from typing import Any

from core.models import GroundingRequest, ProviderCapabilities, ProviderField, utc_now

from .base import CANONICAL_INSTRUCTION, GroundingProvider
from .microsoft_common import azure_credential, parse_responses_result


class MicrosoftWebProvider(GroundingProvider):
    id = "microsoft_web"
    name = "Microsoft Foundry Web Search"
    default_model = "gpt-5.5"
    api_version = "v1"
    fields = (
        ProviderField("project_endpoint", "Foundry project endpoint"),
        ProviderField("model", "Model deployment", default=default_model),
        ProviderField(
            "search_context_size",
            "Search context size (low, medium, or high)",
            required=False,
            default="medium",
        ),
        ProviderField(
            "azure_token",
            "Azure access token (optional when DefaultAzureCredential is configured)",
            secret=True,
            required=False,
        ),
    )
    capabilities = ProviderCapabilities(
        generated_queries=True,
        retrieved_sources=True,
        citations=True,
        market_control=True,
        can_force_search=True,
    )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors = super().validate_config(config)
        if (config.get("search_context_size") or "medium").lower() not in {
            "low",
            "medium",
            "high",
        }:
            errors.append("Search context size must be low, medium, or high.")
        return errors

    def run(self, request: GroundingRequest, config: dict[str, Any]):
        from azure.ai.projects import AIProjectClient

        started = perf_counter()
        model = config.get("model") or self.default_model
        country = _market_country(request.market)
        tool: dict[str, Any] = {
            "type": "web_search",
            "search_context_size": (config.get("search_context_size") or "medium").lower(),
        }
        if country:
            tool["user_location"] = {"type": "approximate", "country": country}
        with AIProjectClient(
            endpoint=config["project_endpoint"],
            credential=azure_credential(config),
        ) as project:
            with project.get_openai_client() as client:
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
                "Foundry Web Search was asked to include its complete consulted-source list. "
                "Retrieval remains UNKNOWN if that optional field is absent."
            ),
            sources_supported=True,
        )
        run.metadata["market_applied"] = bool(_market_country(request.market))
        run.metadata["language_applied"] = False
        return run


def _market_country(market: str | None) -> str | None:
    if not market:
        return None
    parts = market.replace("_", "-").split("-")
    return parts[-1].upper() if len(parts) > 1 and len(parts[-1]) == 2 else None
