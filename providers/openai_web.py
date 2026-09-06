from __future__ import annotations

from time import perf_counter
from typing import Any

from core.models import GroundingRequest, ProviderCapabilities, ProviderField, utc_now

from core.debug import (
    DebugTrace,
    build_run_debug_context,
    debug_mode_enabled,
    openai_request_body,
    record_api_request,
    record_exception_debug,
)
from core.diagnostics import attach_observation_diagnostics
from core.timeouts import request_timeout_seconds
from .base import CANONICAL_INSTRUCTION, GroundingProvider
from .microsoft_common import parse_responses_result
from .model_catalog import OPENAI_WEB_SEARCH, model_field


class OpenAIWebProvider(GroundingProvider):
    id = "openai_web"
    name = "OpenAI Web Search"
    default_model = "gpt-5.5"
    timeout_seconds = 120.0
    fields = (
        ProviderField("api_key", "OpenAI API key", secret=True),
        model_field(OPENAI_WEB_SEARCH),
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

        debug = debug_mode_enabled(config, request)
        trace = DebugTrace(self.id, debug)
        started = perf_counter()
        model = config.get("model") or self.default_model
        timeout = request_timeout_seconds(config, default=self.timeout_seconds)
        trace.event("validated_config", model=model, timeout_seconds=timeout)
        tool: dict[str, Any] = {"type": "web_search"}
        country = _market_country(request.market)
        if country:
            tool["user_location"] = {"type": "approximate", "country": country}
        request_body = openai_request_body(model, request, tool)
        trace.event("request_prepared", request_body=request_body)
        try:
            client = OpenAI(api_key=config["api_key"], timeout=max(timeout - 5.0, 10.0))
            trace.event("http_request_started")
            response = client.responses.create(**request_body)
            trace.event("http_request_completed")
        except Exception as exc:
            trace.event("http_request_failed")
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
        run.metadata["http_timeout_seconds"] = max(timeout - 5.0, 10.0)
        if debug:
            run.metadata["debug"] = {
                "context": build_run_debug_context(self.id, request, config),
            }
            record_api_request(
                run,
                api="openai.responses",
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
