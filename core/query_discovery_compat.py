from __future__ import annotations

import importlib
import inspect
from typing import Any

from core.query_discovery_config import QUERY_DISCOVERY_API_VERSION


class QueryDiscoveryCompatibilityError(RuntimeError):
    pass


def _discover_queries_fn():
    from core.query_discovery import discover_queries

    return discover_queries


def _reload_query_discovery_modules() -> None:
    import core.query_discovery
    import core.query_discovery_config

    importlib.reload(core.query_discovery_config)
    importlib.reload(core.query_discovery)


def _filter_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    discover_queries = _discover_queries_fn()
    accepted = inspect.signature(discover_queries).parameters
    return {key: value for key, value in kwargs.items() if key in accepted}


def supports_query_discovery_features(*features: str) -> bool:
    accepted = inspect.signature(_discover_queries_fn()).parameters
    return all(feature in accepted for feature in features)


def call_discover_queries(source_url: str, **kwargs: Any):
    filtered = _filter_kwargs(kwargs)
    needs_reload = bool(kwargs.get("page_content")) and "page_content" not in filtered
    if needs_reload:
        _reload_query_discovery_modules()
        filtered = _filter_kwargs(kwargs)

    if kwargs.get("page_content") and "page_content" not in filtered:
        raise QueryDiscoveryCompatibilityError(
            "Pasted page copy is configured in the UI, but this Streamlit runtime is still "
            "using an older query-discovery module. Open your Streamlit app settings and "
            "choose **Reboot app** (or redeploy from the latest main branch), then try again."
        )

    discover_queries = _discover_queries_fn()
    return discover_queries(source_url, **filtered)


def installed_query_discovery_version() -> int:
    try:
        import core.query_discovery_config as config

        return int(getattr(config, "QUERY_DISCOVERY_API_VERSION", 1))
    except (ImportError, TypeError, ValueError):
        return 1


def query_discovery_runtime_ok(*, require_paste: bool = False) -> str | None:
    if installed_query_discovery_version() < QUERY_DISCOVERY_API_VERSION:
        return (
            "Query discovery modules look outdated in this Streamlit runtime. "
            "Reboot the app from Streamlit Community Cloud settings after pulling latest main."
        )
    if require_paste and not supports_query_discovery_features("page_content"):
        return (
            "Pasted page copy requires a Streamlit app reboot so the updated "
            "query-discovery code is loaded."
        )
    return None
