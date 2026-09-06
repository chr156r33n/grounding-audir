from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from core.diagnostics import attach_observation_diagnostics
from providers.base import GroundingProvider

from core.debug import (
    DebugTrace,
    build_run_debug_context,
    debug_mode_enabled,
    inject_debug_config,
    record_exception_debug,
    summarize_raw_response,
)
from .enums import ErrorType, RunStatus
from .models import GroundingRequest, GroundingRun, ProviderError, utc_now
from .timeouts import (
    configured_timeout_seconds,
    inject_timeout_config,
    provider_timeout_seconds,
    request_timeout_seconds,
)

ProgressCallback = Callable[[str, str], None]
MIN_RETRY_BUDGET_SECONDS = 5.0


def execute_providers(
    request: GroundingRequest,
    jobs: list[tuple[GroundingProvider, dict[str, Any]]],
    *,
    timeout_seconds: float | None = None,
    max_retries: int = 2,
    on_progress: ProgressCallback | None = None,
) -> Iterator[GroundingRun]:
    """Run providers concurrently and yield each result on completion or timeout."""
    if not jobs:
        return
    default_timeout = (
        timeout_seconds
        if timeout_seconds is not None
        else configured_timeout_seconds(request)
    )
    executor = ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="grounding-provider")
    future_map: dict[Future[GroundingRun], tuple[GroundingProvider, float, float, dict[str, Any]]] = {}
    for provider, config in jobs:
        if on_progress:
            on_progress(provider.id, "running")
        effective_timeout = provider_timeout_seconds(
            request,
            provider,
            default=default_timeout,
        )
        enriched_config = inject_timeout_config(
            inject_debug_config(config, debug_mode_enabled(config, request)),
            effective_timeout,
        )
        deadline = time.monotonic() + effective_timeout
        future = executor.submit(
            _run_with_retries,
            provider,
            request,
            enriched_config,
            max_retries,
            deadline,
        )
        future_map[future] = (provider, deadline, effective_timeout, enriched_config)

    try:
        while future_map:
            now = time.monotonic()
            timed_out = [
                future for future, (_, deadline, _, _) in future_map.items() if deadline <= now
            ]
            for future in timed_out:
                provider, _, effective_timeout, config = future_map.pop(future)
                future.cancel()
                debug = debug_mode_enabled(config, request)
                run = _timeout_run(
                    provider,
                    request,
                    effective_timeout,
                    debug_trace=[
                        {
                            "stage": "application_deadline",
                            "elapsed_ms": round(effective_timeout * 1000),
                            "note": "Provider worker did not return before the application deadline.",
                        }
                    ]
                    if debug
                    else None,
                    debug_context=build_run_debug_context(provider.id, request, config)
                    if debug
                    else None,
                )
                if on_progress:
                    on_progress(provider.id, "timed_out")
                yield run
            if not future_map:
                break
            nearest_deadline = min(deadline for _, deadline, _, _ in future_map.values())
            done, _ = wait(
                future_map,
                timeout=max(0.01, nearest_deadline - time.monotonic()),
                return_when=FIRST_COMPLETED,
            )
            for future in done:
                provider, _, _, _ = future_map.pop(future)
                try:
                    run = future.result()
                except Exception as exc:  # Defensive: wrapper should normally convert this.
                    run = _failure_run(provider, request, _classify_exception(exc))
                if on_progress:
                    on_progress(provider.id, run.status.value)
                yield run
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _run_with_retries(
    provider: GroundingProvider,
    request: GroundingRequest,
    config: dict[str, Any],
    max_retries: int,
    deadline: float,
) -> GroundingRun:
    started = time.monotonic()
    validation_errors = provider.validate_config(config)
    if validation_errors:
        run = _failure_run(
            provider,
            request,
            ProviderError(
                type=ErrorType.INVALID_CONFIG,
                safe_message=" ".join(validation_errors),
                retryable=False,
            ),
        )
        run.latency_ms = 0
        return run

    retries = 0
    debug = debug_mode_enabled(config, request)
    trace = DebugTrace(provider.id, debug)
    trace.event(
        "execution_started",
        timeout_seconds=request_timeout_seconds(config),
        max_retries=max_retries,
    )
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return _timeout_run(
                provider,
                request,
                request_timeout_seconds(config),
                elapsed_ms=round((time.monotonic() - started) * 1000),
                retry_count=retries,
                debug_trace=trace.events if debug else None,
                debug_context=build_run_debug_context(provider.id, request, config)
                if debug
                else None,
            )

        try:
            trace.event("provider_run_started", attempt=retries + 1)
            run = provider.run(request, config)
            run.metadata["retry_count"] = retries
            run.metadata["timeout_seconds"] = request_timeout_seconds(config)
            if debug:
                run.metadata.setdefault("debug", {})
                run.metadata["debug"]["context"] = build_run_debug_context(
                    provider.id,
                    request,
                    config,
                )
                existing_trace = run.metadata["debug"].get("trace") or []
                run.metadata["debug"]["trace"] = existing_trace + trace.events
                if run.raw_response is not None:
                    run.metadata["debug"]["response_summary"] = summarize_raw_response(
                        run.raw_response
                    )
            trace.event("provider_run_completed", status=run.status.value)
            return run
        except Exception as exc:
            trace.event("provider_run_failed", attempt=retries + 1, error_type=type(exc).__name__)
            error = _classify_exception(exc)
            if not error.retryable or retries >= max_retries:
                run = _failure_run(provider, request, error)
                run.metadata["retry_count"] = retries
                run.metadata["timeout_seconds"] = request_timeout_seconds(config)
                run.latency_ms = round((time.monotonic() - started) * 1000)
                if debug:
                    run.metadata["debug"] = {
                        "context": build_run_debug_context(provider.id, request, config),
                        "trace": trace.events,
                    }
                    record_exception_debug(run, exc)
                return run
            if remaining < MIN_RETRY_BUDGET_SECONDS:
                run = _timeout_run(
                    provider,
                    request,
                    request_timeout_seconds(config),
                    elapsed_ms=round((time.monotonic() - started) * 1000),
                    retry_count=retries,
                    detail=(
                        "The provider returned a retryable error, but the remaining timeout "
                        "budget was too small for another attempt."
                    ),
                    debug_trace=trace.events if debug else None,
                    debug_context=build_run_debug_context(provider.id, request, config)
                    if debug
                    else None,
                )
                return run
            retries += 1
            retry_after = _retry_after(exc)
            sleep_for = retry_after if retry_after is not None else (2 ** (retries - 1)) + random.random()
            sleep_for = min(sleep_for, max(0.0, remaining - MIN_RETRY_BUDGET_SECONDS))
            if sleep_for > 0:
                time.sleep(sleep_for)


def _timeout_run(
    provider: GroundingProvider,
    request: GroundingRequest,
    timeout_seconds: float,
    *,
    elapsed_ms: int | None = None,
    retry_count: int = 0,
    detail: str | None = None,
    debug_trace: list[dict[str, Any]] | None = None,
    debug_context: dict[str, Any] | None = None,
) -> GroundingRun:
    message = (
        f"Provider exceeded the {timeout_seconds:g}-second timeout. "
        "Web search requests can be slow — especially when the model searches the web "
        "and the API returns consulted sources. Increase the per-provider timeout and "
        "try again, or run fewer providers concurrently."
    )
    if detail:
        message = f"{message} {detail}"
    run = _failure_run(
        provider,
        request,
        ProviderError(
            type=ErrorType.TIMEOUT,
            safe_message=message,
            retryable=True,
        ),
        RunStatus.TIMED_OUT,
    )
    run.latency_ms = elapsed_ms if elapsed_ms is not None else round(timeout_seconds * 1000)
    run.metadata.update(
        {
            "retry_count": retry_count,
            "timeout_seconds": timeout_seconds,
            "timeout_reason": "application_deadline",
        }
    )
    if debug_trace is not None:
        run.metadata["debug"] = {
            "context": debug_context or build_run_debug_context(provider.id, request, {}),
            "trace": debug_trace,
        }
    return attach_observation_diagnostics(run)


def _classify_exception(exc: Exception) -> ProviderError:
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if not isinstance(status, int):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    name = type(exc).__name__.lower()
    if status in {401, 403} or "authentication" in name or "credential" in name:
        error_type, message, retryable = (
            ErrorType.AUTH_ERROR,
            "Authentication failed. Check this provider's credentials and access.",
            False,
        )
    elif status == 429 or "ratelimit" in name:
        error_type, message, retryable = (
            ErrorType.RATE_LIMITED,
            "The provider rate limit was reached.",
            True,
        )
    elif status and status >= 500:
        error_type, message, retryable = (
            ErrorType.PROVIDER_ERROR,
            "The provider returned a temporary server error.",
            True,
        )
    elif "timeout" in name or "connection" in name:
        error_type, message, retryable = (
            ErrorType.TIMEOUT,
            "The provider HTTP request timed out or its connection failed before the application deadline.",
            True,
        )
    elif status in {400, 404, 422}:
        error_type, message, retryable = (
            ErrorType.INVALID_CONFIG,
            "The provider rejected the request configuration or model.",
            False,
        )
    else:
        error_type, message, retryable = (
            ErrorType.UNKNOWN_ERROR,
            "The provider request failed. Enable local debugging for technical diagnostics.",
            False,
        )
    return ProviderError(
        type=error_type,
        status_code=status if isinstance(status, int) else None,
        provider_code=str(getattr(exc, "code", "")) or None,
        safe_message=message,
        retryable=retryable,
    )


def _retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", {}) or {}
    try:
        value = float(headers.get("retry-after"))
        return min(max(value, 0), 30)
    except (TypeError, ValueError):
        return None


def _failure_run(
    provider: GroundingProvider,
    request: GroundingRequest,
    error: ProviderError,
    status: RunStatus = RunStatus.FAILED,
) -> GroundingRun:
    run = provider.new_run(request)
    run.status = status
    run.error = error
    run.finished_at = utc_now()
    return attach_observation_diagnostics(run)
