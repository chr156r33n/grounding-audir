from __future__ import annotations

from time import perf_counter
from typing import Any

from core.models import GroundingRequest, ProviderCapabilities, ProviderField, utc_now

from core.debug import (
    DebugTrace,
    build_run_debug_context,
    debug_mode_enabled,
    foundry_web_search_request_body,
    record_api_request,
    record_exception_debug,
)
from core.diagnostics import attach_observation_diagnostics
from core.timeouts import request_timeout_seconds
from .base import CANONICAL_INSTRUCTION, GroundingProvider
from .microsoft_common import azure_credential, parse_responses_result
from .model_catalog import MICROSOFT_FOUNDRY_WEB_SEARCH, model_field


class MicrosoftWebProvider(GroundingProvider):
    id = "microsoft_web"
    name = "Microsoft Foundry Web Search"
    default_model = "gpt-5.5"
    timeout_seconds = 120.0
    api_version = "v1"
    fields = (
        ProviderField("project_endpoint", "Foundry project endpoint"),
        model_field(MICROSOFT_FOUNDRY_WEB_SEARCH, label="Model deployment"),
        ProviderField(
            "search_context_size",
            "Search context size",
            required=True,
            default="medium",
            choices=("low", "medium", "high"),
            help="Documented web_search search_context_size values.",
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

        debug = debug_mode_enabled(config, request)
        trace = DebugTrace(self.id, debug)
        started = perf_counter()
        model = config.get("model") or self.default_model
        country = _market_country(request.market)
        tool: dict[str, Any] = {
            "type": "web_search",
            "search_context_size": (config.get("search_context_size") or "medium").lower(),
        }
        if country:
            tool["user_location"] = {"type": "approximate", "country": country}
        request_body = foundry_web_search_request_body(model, request, tool)
        trace.event("request_prepared", request_body=request_body)
        try:
            with AIProjectClient(
                endpoint=config["project_endpoint"],
                credential=azure_credential(config),
            ) as project:
                trace.event("foundry_client_ready")
                with project.get_openai_client() as client:
                    trace.event("http_request_started")
                    response = client.responses.create(**request_body)
                    trace.event("http_request_completed")
        except Exception as exc:
            trace.event("http_request_failed")
            if debug:
                run = self.new_run(request, model)
                run.metadata["debug"] = {
                    "context": build_run_debug_context(self.id, request, config),
                    "trace": trace.events,
                }
                record_exception_debug(run, exc)
            raise
        run = self.parse_response(response, request, model)
        run.latency_ms = round((perf_counter() - started) * 1000)
        run.finished_at = utc_now()
        if debug:
            run.metadata["debug"] = {"context": build_run_debug_context(self.id, request, config)}
            record_api_request(
                run,
                api="azure.foundry.responses",
                operation="responses.create",
                request_body=request_body,
            )
            trace.attach(run)
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
        run.metadata["sources_requested"] = True
        run.metadata["include_fields"] = ["web_search_call.action.sources"]
        return attach_observation_diagnostics(run)


def _market_country(market: str | None) -> str | None:
    if not market:
        return None
    parts = market.replace("_", "-").split("-")
    return parts[-1].upper() if len(parts) > 1 and len(parts[-1]) == 2 else None
