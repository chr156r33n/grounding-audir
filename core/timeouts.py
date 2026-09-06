from __future__ import annotations

from typing import Any

from providers.base import GroundingProvider

from .models import GroundingRequest

DEFAULT_PROVIDER_TIMEOUT_SECONDS = 90.0
MIN_PROVIDER_TIMEOUT_SECONDS = 30.0
MAX_PROVIDER_TIMEOUT_SECONDS = 180.0
TIMEOUT_CONFIG_KEY = "_timeout_seconds"


def clamp_timeout_seconds(value: Any, *, default: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(MIN_PROVIDER_TIMEOUT_SECONDS, min(MAX_PROVIDER_TIMEOUT_SECONDS, parsed))


def configured_timeout_seconds(
    request: GroundingRequest,
    *,
    default: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
) -> float:
    return clamp_timeout_seconds(
        request.provider_options.get("timeout_seconds", default),
        default=default,
    )


def provider_timeout_seconds(
    request: GroundingRequest,
    provider: GroundingProvider,
    *,
    default: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS,
) -> float:
    configured = configured_timeout_seconds(request, default=default)
    provider_hint = getattr(provider, "timeout_seconds", None)
    if provider_hint is None:
        return configured
    return max(configured, clamp_timeout_seconds(provider_hint, default=provider_hint))


def request_timeout_seconds(config: dict[str, Any], *, default: float = DEFAULT_PROVIDER_TIMEOUT_SECONDS) -> float:
    return clamp_timeout_seconds(config.get(TIMEOUT_CONFIG_KEY, default), default=default)


def inject_timeout_config(config: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    enriched = dict(config)
    enriched[TIMEOUT_CONFIG_KEY] = timeout_seconds
    return enriched
