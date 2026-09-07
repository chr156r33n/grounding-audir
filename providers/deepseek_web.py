from __future__ import annotations

from time import perf_counter
from typing import Any

from core.diagnostics import attach_observation_diagnostics
from core.models import GroundingRequest, ProviderCapabilities, ProviderField, utc_now
from core.timeouts import request_timeout_seconds

from core.debug import (
    DebugTrace,
    attach_debug_to_exception,
    build_run_debug_context,
    debug_mode_enabled,
    deepseek_request_body,
    record_api_request,
)
from .base import GroundingProvider
from .microsoft_common import parse_responses_result
from .model_catalog import DEEPSEEK_WEB_SEARCH, model_field

DEEPSEEK_API_BASE_URL = "https://api.deepseek.com"


class DeepSeekWebProvider(GroundingProvider):
    id = "deepseek_web"
    name = "DeepSeek Web Search"
    default_model = "deepseek-v4-flash"
    timeout_seconds = 120.0
    fields = (
        ProviderField("api_key", "DeepSeek API key", secret=True),
        model_field(DEEPSEEK_WEB_SEARCH),
        ProviderField(
            "base_url",
            "DeepSeek API base URL",
            required=False,
            default=DEEPSEEK_API_BASE_URL,
            help=(
                "OpenAI-compatible API root for DeepSeek. The Responses API web_search tool "
                f"defaults to {DEEPSEEK_API_BASE_URL}."
            ),
        ),
    )
    capabilities = ProviderCapabilities(
        generated_queries=True,
        retrieved_sources=True,
        citations=True,
        market_control=False,
        can_force_search=True,
    )

    def run(self, request: GroundingRequest, config: dict[str, Any]):
        from openai import OpenAI

        debug = debug_mode_enabled(config, request)
        trace = DebugTrace(self.id, debug)
        started = perf_counter()
        model = config.get("model") or self.default_model
        timeout = request_timeout_seconds(config, default=self.timeout_seconds)
        base_url = str(config.get("base_url") or DEEPSEEK_API_BASE_URL).strip().rstrip("/")
        tool: dict[str, Any] = {"type": "web_search"}
        request_body = deepseek_request_body(model, request, tool)
        trace.event(
            "validated_config",
            model=model,
            timeout_seconds=timeout,
            base_url=base_url,
        )
        trace.event("request_prepared", request_body=request_body)
        try:
            client = OpenAI(
                api_key=config["api_key"],
                base_url=base_url,
                timeout=max(timeout - 5.0, 10.0),
            )
            trace.event("http_request_started")
            response = client.responses.create(**request_body)
            trace.event("http_request_completed")
        except Exception as exc:
            trace.event("http_request_failed")
            if debug:
                attach_debug_to_exception(
                    exc,
                    {
                        "context": build_run_debug_context(self.id, request, config),
                        "trace": trace.events,
                        "api": "deepseek.responses",
                        "operation": "responses.create",
                        "request_body": request_body,
                    },
                )
            raise
        run = self.parse_response(response, request, model)
        run.latency_ms = round((perf_counter() - started) * 1000)
        run.finished_at = utc_now()
        run.metadata["http_timeout_seconds"] = max(timeout - 5.0, 10.0)
        run.metadata["base_url"] = base_url
        if debug:
            run.metadata["debug"] = {
                "context": build_run_debug_context(self.id, request, config),
            }
            record_api_request(
                run,
                api="deepseek.responses",
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
                "DeepSeek Web Search was asked to include consulted sources when the Responses "
                "API supports include=[\"web_search_call.action.sources\"]. Target retrieval "
                "remains UNKNOWN if that field is absent from the response."
            ),
            sources_supported=True,
        )
        run.metadata["market_applied"] = False
        run.metadata["language_applied"] = False
        run.metadata["sources_requested"] = True
        run.metadata["include_fields"] = ["web_search_call.action.sources"]
        return attach_observation_diagnostics(run)
