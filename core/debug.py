from __future__ import annotations

from time import perf_counter
from typing import Any

from core.export import redact_secrets
from core.models import GroundingRequest, GroundingRun

DEBUG_CONFIG_KEY = "_debug_mode"


def debug_mode_enabled(config: dict[str, Any] | None = None, request: GroundingRequest | None = None) -> bool:
    if config and config.get(DEBUG_CONFIG_KEY):
        return True
    if request and request.provider_options.get("debug_mode"):
        return True
    return False


def inject_debug_config(config: dict[str, Any], enabled: bool) -> dict[str, Any]:
    enriched = dict(config)
    enriched[DEBUG_CONFIG_KEY] = enabled
    return enriched


class DebugTrace:
    def __init__(self, provider_id: str, enabled: bool):
        self.provider_id = provider_id
        self.enabled = enabled
        self.events: list[dict[str, Any]] = []
        self._started = perf_counter()

    def event(self, stage: str, **details: Any) -> None:
        if not self.enabled:
            return
        self.events.append(
            {
                "stage": stage,
                "elapsed_ms": round((perf_counter() - self._started) * 1000),
                **redact_secrets(details),
            }
        )

    def attach(self, run: GroundingRun) -> GroundingRun:
        if not self.enabled:
            return run
        run.metadata.setdefault("debug", {})
        run.metadata["debug"]["trace"] = self.events
        return run


def build_run_debug_context(
    provider_id: str,
    request: GroundingRequest,
    config: dict[str, Any],
) -> dict[str, Any]:
    return redact_secrets(
        {
            "provider_id": provider_id,
            "input_phrase": request.input_phrase,
            "targets": [target.value for target in request.targets],
            "market": request.market,
            "language": request.language,
            "provider_options": request.provider_options,
            "config": {
                key: value
                for key, value in config.items()
                if not str(key).startswith("_")
            },
        }
    )


def record_api_request(
    run: GroundingRun,
    *,
    api: str,
    operation: str,
    request_body: dict[str, Any] | None = None,
    notes: str | None = None,
) -> None:
    if "debug" not in run.metadata:
        return
    run.metadata["debug"]["api"] = api
    run.metadata["debug"]["operation"] = operation
    if notes:
        run.metadata["debug"]["notes"] = notes
    if request_body is not None:
        run.metadata["debug"]["request_body"] = redact_secrets(request_body)


def record_exception_debug(run: GroundingRun, exc: Exception) -> None:
    if "debug" not in run.metadata:
        return
    run.metadata["debug"]["exception"] = redact_secrets(
        {
            "type": type(exc).__name__,
            "message": str(exc),
            "status_code": getattr(exc, "status_code", None)
            or getattr(getattr(exc, "response", None), "status_code", None),
            "code": getattr(exc, "code", None),
        }
    )


def openai_request_body(model: str, request: GroundingRequest, tool: dict[str, Any]) -> dict[str, Any]:
    from providers.base import CANONICAL_INSTRUCTION

    return {
        "model": model,
        "input": CANONICAL_INSTRUCTION.format(query=request.input_phrase),
        "tools": [tool],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
    }


def gemini_request_body(model: str, request: GroundingRequest) -> dict[str, Any]:
    from providers.base import CANONICAL_INSTRUCTION

    return {
        "model": model,
        "input": CANONICAL_INSTRUCTION.format(query=request.input_phrase),
        "tools": [{"type": "google_search", "search_types": ["web_search"]}],
    }


def foundry_web_search_request_body(
    model: str,
    request: GroundingRequest,
    tool: dict[str, Any],
) -> dict[str, Any]:
    from providers.base import CANONICAL_INSTRUCTION

    return {
        "model": model,
        "input": CANONICAL_INSTRUCTION.format(query=request.input_phrase),
        "tools": [tool],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
    }


def summarize_raw_response(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"type": type(raw).__name__}
    output = raw.get("output") or raw.get("steps") or []
    summary = {
        "id": raw.get("id"),
        "status": raw.get("status"),
        "model": raw.get("model"),
        "usage": raw.get("usage"),
        "incomplete_details": raw.get("incomplete_details"),
        "service_tier": raw.get("service_tier"),
    }
    if isinstance(output, list):
        summary["output_types"] = [item.get("type") for item in output if isinstance(item, dict)]
        summary["output_count"] = len(output)
    if raw.get("webResults") is not None:
        summary["web_results_count"] = len(raw.get("webResults") or [])
    return redact_secrets(summary)
