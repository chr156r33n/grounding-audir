from __future__ import annotations

from time import perf_counter
from typing import Any

from core.models import GroundingRequest, ProviderCapabilities, ProviderField, utc_now

from core.debug import (
    DebugTrace,
    attach_debug_to_exception,
    build_run_debug_context,
    debug_mode_enabled,
)
from .base import CANONICAL_INSTRUCTION, GroundingProvider
from .microsoft_common import azure_credential, parse_responses_result
from .model_catalog import MICROSOFT_BING_GROUNDING, model_field


class MicrosoftBingProvider(GroundingProvider):
    id = "microsoft_bing"
    name = "Microsoft Grounding with Bing Search"
    default_model = "gpt-4.1-mini"
    timeout_seconds = 120.0
    api_version = "v1"
    fields = (
        ProviderField("project_endpoint", "Foundry project endpoint"),
        model_field(MICROSOFT_BING_GROUNDING, label="Model deployment"),
        ProviderField(
            "connection_name",
            "Bing grounding project connection name",
            required=False,
        ),
        ProviderField(
            "connection_id",
            "Bing grounding project connection resource ID (alternative)",
            required=False,
        ),
        ProviderField(
            "azure_token",
            "Azure access token (optional when DefaultAzureCredential is configured)",
            secret=True,
            required=False,
        ),
        ProviderField("result_count", "Result count", required=False, default="7"),
        ProviderField("freshness", "Freshness (optional)", required=False),
    )
    capabilities = ProviderCapabilities(
        generated_queries=True,
        retrieved_sources=False,
        citations=True,
        market_control=True,
        language_control=True,
        freshness_control=True,
        can_force_search=True,
    )

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors = super().validate_config(config)
        if not config.get("connection_name") and not config.get("connection_id"):
            errors.append("A Bing grounding project connection name or resource ID is required.")
        try:
            count = int(config.get("result_count") or 7)
            if not 1 <= count <= 50:
                errors.append("Bing result count must be between 1 and 50.")
        except (TypeError, ValueError):
            errors.append("Bing result count must be an integer.")
        return errors

    def run(self, request: GroundingRequest, config: dict[str, Any]):
        from azure.ai.projects import AIProjectClient
        from azure.ai.projects.models import (
            BingGroundingSearchConfiguration,
            BingGroundingSearchToolParameters,
            BingGroundingTool,
            PromptAgentDefinition,
        )

        debug = debug_mode_enabled(config, request)
        trace = DebugTrace(self.id, debug)
        started = perf_counter()
        model = config.get("model") or self.default_model
        search_values: dict[str, Any] = {
            "count": max(1, min(int(config.get("result_count") or 7), 50)),
        }
        if request.market:
            search_values["market"] = request.market
        if request.language:
            search_values["set_lang"] = request.language
        if config.get("freshness"):
            search_values["freshness"] = config["freshness"]
        agent_name = f"grounding-bing-{request.run_id}"[:63].rstrip("-")
        response_request = {
            "input": CANONICAL_INSTRUCTION.format(query=request.input_phrase),
            "tool_choice": "required",
            "extra_body": {
                "agent_reference": {
                    "name": agent_name,
                    "type": "agent_reference",
                }
            },
        }
        agent_request = {
            "agent_name": agent_name,
            "model": model,
            "instructions": "Use Bing grounding for current public-web evidence.",
            "search_configuration": search_values,
            "connection": config.get("connection_id")
            or config.get("connection_name"),
        }
        trace.event("request_prepared", agent_request=agent_request)
        cleanup_succeeded = False
        try:
            with AIProjectClient(
                endpoint=config["project_endpoint"],
                credential=azure_credential(config),
            ) as project:
                trace.event("foundry_client_ready")
                project_connection_id = config.get("connection_id")
                if not project_connection_id:
                    trace.event("connection_lookup_started")
                    project_connection_id = project.connections.get(
                        config["connection_name"]
                    ).id
                    trace.event("connection_lookup_completed")
                search_configuration = BingGroundingSearchConfiguration(
                    project_connection_id=project_connection_id,
                    **search_values,
                )
                tool = BingGroundingTool(
                    bing_grounding=BingGroundingSearchToolParameters(
                        search_configurations=[search_configuration]
                    )
                )
                trace.event("agent_create_started")
                agent = project.agents.create_version(
                    agent_name=agent_name,
                    definition=PromptAgentDefinition(
                        model=model,
                        instructions="Use Bing grounding for current public-web evidence.",
                        tools=[tool],
                    ),
                    description="Ephemeral Grounding Source Observatory run",
                )
                trace.event(
                    "agent_create_completed",
                    agent_name=agent.name,
                    agent_version=agent.version,
                )
                response_request["extra_body"]["agent_reference"]["name"] = agent.name
                try:
                    with project.get_openai_client() as client:
                        trace.event("http_request_started")
                        response = client.responses.create(**response_request)
                        trace.event("http_request_completed")
                finally:
                    try:
                        trace.event("agent_delete_started")
                        project.agents.delete_version(
                            agent_name=agent.name,
                            agent_version=agent.version,
                        )
                        cleanup_succeeded = True
                        trace.event("agent_delete_completed")
                    except Exception as cleanup_exc:
                        trace.event(
                            "agent_delete_failed",
                            error_type=type(cleanup_exc).__name__,
                        )
        except Exception as exc:
            trace.event("provider_request_failed", error_type=type(exc).__name__)
            if debug:
                attach_debug_to_exception(
                    exc,
                    {
                        "context": build_run_debug_context(self.id, request, config),
                        "trace": trace.events,
                        "api": "azure.foundry.agents+responses",
                        "operation": "create_version / responses.create / delete_version",
                        "requests": [
                            {"operation": "agents.create_version", "body": agent_request},
                            {"operation": "responses.create", "body": response_request},
                        ],
                    },
                )
            raise
        run = self.parse_response(response, request, model)
        run.latency_ms = round((perf_counter() - started) * 1000)
        run.finished_at = utc_now()
        run.metadata["search_configuration"] = search_values
        run.metadata["ephemeral_agent_cleanup_succeeded"] = cleanup_succeeded
        if debug:
            run.metadata["debug"] = {
                "context": build_run_debug_context(self.id, request, config),
                "trace": trace.events,
                "api": "azure.foundry.agents+responses",
                "operation": "create_version / responses.create / delete_version",
                "requests": [
                    {"operation": "agents.create_version", "body": agent_request},
                    {"operation": "responses.create", "body": response_request},
                ],
            }
        return run

    def parse_response(self, raw_response: Any, request: GroundingRequest, model: str | None = None):
        run = parse_responses_result(
            self,
            raw_response,
            request,
            model,
            (
                "Microsoft Bing Grounding does not expose the raw grounding tool output for this "
                "request. Retrieval presence cannot be determined from citations alone."
            ),
        )
        run.metadata["market_applied"] = bool(request.market)
        run.metadata["language_applied"] = bool(request.language)
        return run
