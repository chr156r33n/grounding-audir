from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from typing import Any

from providers.base import GroundingProvider

from .enums import ErrorType, RunStatus
from .models import GroundingRequest, GroundingRun, ProviderError, utc_now

ProgressCallback = Callable[[str, str], None]


def execute_providers(
    request: GroundingRequest,
    jobs: list[tuple[GroundingProvider, dict[str, Any]]],
    *,
    timeout_seconds: float = 45,
    max_retries: int = 2,
    on_progress: ProgressCallback | None = None,
) -> Iterator[GroundingRun]:
    """Run providers concurrently and yield each result on completion or timeout."""
    if not jobs:
        return
    executor = ThreadPoolExecutor(max_workers=len(jobs), thread_name_prefix="grounding-provider")
    future_map: dict[Future[GroundingRun], tuple[GroundingProvider, float]] = {}
    for provider, config in jobs:
        if on_progress:
            on_progress(provider.id, "running")
        future = executor.submit(
            _run_with_retries,
            provider,
            request,
            config,
            max_retries,
        )
        future_map[future] = (provider, time.monotonic() + timeout_seconds)

    try:
        while future_map:
            now = time.monotonic()
            timed_out = [
                future for future, (_, deadline) in future_map.items() if deadline <= now
            ]
            for future in timed_out:
                provider, _ = future_map.pop(future)
                future.cancel()
                run = _failure_run(
                    provider,
                    request,
                    ProviderError(
                        type=ErrorType.TIMEOUT,
                        safe_message=f"Provider exceeded the {timeout_seconds:g}-second timeout.",
                        retryable=True,
                    ),
                    RunStatus.TIMED_OUT,
                )
                run.latency_ms = round(timeout_seconds * 1000)
                if on_progress:
                    on_progress(provider.id, "timed_out")
                yield run
            if not future_map:
                break
            nearest_deadline = min(deadline for _, deadline in future_map.values())
            done, _ = wait(
                future_map,
                timeout=max(0.01, nearest_deadline - time.monotonic()),
                return_when=FIRST_COMPLETED,
            )
            for future in done:
                provider, _ = future_map.pop(future)
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
    while True:
        try:
            run = provider.run(request, config)
            run.metadata["retry_count"] = retries
            return run
        except Exception as exc:
            error = _classify_exception(exc)
            if not error.retryable or retries >= max_retries:
                run = _failure_run(provider, request, error)
                run.metadata["retry_count"] = retries
                run.latency_ms = round((time.monotonic() - started) * 1000)
                return run
            retries += 1
            retry_after = _retry_after(exc)
            time.sleep(retry_after if retry_after is not None else (2 ** (retries - 1)) + random.random())


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
            "The provider request timed out or its connection failed.",
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
    return run
