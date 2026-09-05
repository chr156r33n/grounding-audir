from __future__ import annotations

from time import perf_counter
from typing import Any

from core.models import GroundingRequest, ProviderCapabilities, ProviderField, utc_now

from .base import CANONICAL_INSTRUCTION, GroundingProvider
from .microsoft_common import azure_credential, parse_responses_result


class MicrosoftWebProvider(GroundingProvider):
    id = "microsoft_web"
    name = "Microsoft Foundry Web Search"
    default_model = "gpt-5-mini"
    api_version = "v1"
    fields = (
        ProviderField("project_endpoint", "Foundry project endpoint"),
        ProviderField("model", "Model deployment", default=default_model),
        ProviderField(
            "azure_token",
            "Azure access token (optional when DefaultAzureCredential is configured)",
            secret=True,
            required=False,
        ),
    )
    capabilities = ProviderCapabilities(
        generated_queries=True,
        retrieved_sources=False,
        citations=True,
        can_force_search=True,
    )

    def run(self, request: GroundingRequest, config: dict[str, Any]):
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import (
            PromptAgentDefinition,
            WebSearchApproximateLocation,
            WebSearchTool,
        )

        started = perf_counter()
        model = config.get("model") or self.default_model
        country = _market_country(request.market)
        tool = (
            WebSearchTool(
                user_location=WebSearchApproximateLocation(country=country)
            )
            if country
            else WebSearchTool()
        )
        agent_name = f"grounding-web-{request.run_id}"[:63].rstrip("-")
        with AIProjectClient(
            endpoint=config["project_endpoint"],
            credential=azure_credential(config),
        ) as project:
            client = project.get_openai_client()
            agent = project.agents.create_version(
                agent_name=agent_name,
                definition=PromptAgentDefinition(
                    model=model,
                    instructions="Use web search for current public-web evidence.",
                    tools=[tool],
                ),
                description="Ephemeral Grounding Source Observatory run",
            )
            cleanup_succeeded = True
            try:
                response = client.responses.create(
                    input=CANONICAL_INSTRUCTION.format(query=request.input_phrase),
                    tool_choice="required",
                    extra_body={
                        "agent_reference": {
                            "name": agent.name,
                            "type": "agent_reference",
                        }
                    },
                )
            finally:
                try:
                    project.agents.delete_version(
                        agent_name=agent.name,
                        agent_version=agent.version,
                    )
                except Exception:
                    cleanup_succeeded = False
        run = self.parse_response(response, request, model)
        run.latency_ms = round((perf_counter() - started) * 1000)
        run.finished_at = utc_now()
        run.metadata["ephemeral_agent_cleanup_succeeded"] = cleanup_succeeded
        return run

    def parse_response(self, raw_response: Any, request: GroundingRequest, model: str | None = None):
        run = parse_responses_result(
            self,
            raw_response,
            request,
            model,
            (
                "Microsoft Foundry Web Search did not expose a complete raw retrieval set in this "
                "response. Retrieval presence cannot be inferred from citations."
            ),
        )
        run.metadata["market_applied"] = bool(_market_country(request.market))
        run.metadata["language_applied"] = False
        return run


def _market_country(market: str | None) -> str | None:
    if not market:
        return None
    parts = market.replace("_", "-").split("-")
    return parts[-1].upper() if len(parts) > 1 and len(parts[-1]) == 2 else None
