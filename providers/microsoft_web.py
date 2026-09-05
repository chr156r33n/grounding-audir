from __future__ import annotations

from time import perf_counter
from typing import Any

from core.models import GroundingRequest, ProviderCapabilities, ProviderField, utc_now

from .base import CANONICAL_INSTRUCTION, GroundingProvider
from .microsoft_common import azure_credential, parse_responses_result


class MicrosoftWebProvider(GroundingProvider):
    id = "microsoft_web"
    name = "Microsoft Foundry Web Search"
    default_model = "gpt-4.1-mini"
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

        started = perf_counter()
        model = config.get("model") or self.default_model
        with AIProjectClient(
            endpoint=config["project_endpoint"],
            credential=azure_credential(config),
        ) as project:
            client = project.get_openai_client()
            response = client.responses.create(
                model=model,
                input=CANONICAL_INSTRUCTION.format(query=request.input_phrase),
                tools=[{"type": "web_search"}],
                tool_choice="required",
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
                "Microsoft Foundry Web Search did not expose a complete raw retrieval set in this "
                "response. Retrieval presence cannot be inferred from citations."
            ),
        )
        run.metadata["market_applied"] = False
        run.metadata["language_applied"] = False
        return run
