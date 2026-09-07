from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlsplit

from .export import redact_secrets

_FOUNDRY_PROVIDER_IDS = frozenset({"microsoft_web", "microsoft_bing"})
_DEPLOYMENT_NOT_FOUND = re.compile(
    r"deployment|model.?not.?found|does not exist|unknown model",
    re.I,
)
_WEB_SEARCH_UNSUPPORTED = re.compile(
    r"web[_ -]?search|tool|unsupported|not supported|invalid tool",
    re.I,
)


def extract_provider_error_details(exc: Exception) -> dict[str, Any]:
    details: dict[str, Any] = {"exception_type": type(exc).__name__}

    status = getattr(exc, "status_code", None)
    if not isinstance(status, int):
        response = getattr(exc, "response", None)
        status = getattr(response, "status_code", None)
    if isinstance(status, int):
        details["status_code"] = status

    code = getattr(exc, "code", None)
    if code:
        details["provider_code"] = str(code)

    for attr in ("message", "reason"):
        value = getattr(exc, attr, None)
        if isinstance(value, str) and value.strip():
            details.setdefault("message", value.strip()[:500])
            break

    body = getattr(exc, "body", None)
    if body is None:
        response = getattr(exc, "response", None)
        json_fn = getattr(response, "json", None)
        if callable(json_fn):
            try:
                body = json_fn()
            except (TypeError, ValueError):
                body = None

    if isinstance(body, (dict, list)):
        details["response_body"] = _summarize_response_body(body)
    elif isinstance(body, str) and body.strip():
        details["response_body"] = body.strip()[:500]

    if not details.get("message") and str(exc).strip():
        details["message"] = str(exc).strip()[:500]

    return redact_secrets(details)


def invalid_config_message(
    exc: Exception,
    *,
    provider_id: str | None = None,
    config: dict[str, Any] | None = None,
) -> str:
    details = extract_provider_error_details(exc)
    api_message = _api_message(details)
    status = details.get("status_code")

    if api_message:
        base = f"The provider rejected the request (HTTP {status}): {api_message}" if status else (
            f"The provider rejected the request: {api_message}"
        )
    else:
        base = (
            "The provider rejected the request configuration or model."
            + (f" HTTP status: {status}." if status else "")
        )

    hint = configuration_hint(provider_id, config, details)
    return f"{base} {hint}".strip()


def configuration_hint(
    provider_id: str | None,
    config: dict[str, Any] | None,
    details: dict[str, Any] | None = None,
) -> str:
    if provider_id not in _FOUNDRY_PROVIDER_IDS:
        return "Enable debug mode for the full sanitised request and response."

    details = details or {}
    api_message = _api_message(details)
    deployment = str((config or {}).get("model") or "").strip()
    endpoint = str((config or {}).get("project_endpoint") or "").strip()

    hints: list[str] = [
        "For Foundry, the model field must be your exact deployment name from "
        "Models + endpoints → Deployments in the Azure portal or Foundry project "
        "(for example `gpt-4.1-mini` or `my-web-search-deployment`), not just a catalog model ID "
        "unless that string is also the deployment name.",
    ]

    endpoint_errors = validate_foundry_project_endpoint(endpoint)
    if endpoint_errors:
        hints.append(endpoint_errors[0])

    if api_message and _DEPLOYMENT_NOT_FOUND.search(api_message):
        hints.append(
            f"Deployment `{deployment or '(empty)'}` was not found in the configured project."
        )
    elif api_message and _WEB_SEARCH_UNSUPPORTED.search(api_message):
        hints.append(
            "That deployment may exist but not support the Foundry web_search / Bing grounding tool."
        )
    elif not deployment:
        hints.append("Enter a deployment name before running the test.")

    hints.append("Enable debug mode to inspect the sanitised request body and API response.")
    return " ".join(hints)


def validate_foundry_project_endpoint(endpoint: str) -> list[str]:
    value = endpoint.strip()
    if not value:
        return ["Foundry project endpoint is required."]
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ["Foundry project endpoint is not a valid URL."]

    if parsed.scheme not in {"http", "https"}:
        return ["Foundry project endpoint must use https://."]
    if not parsed.netloc:
        return ["Foundry project endpoint must include a hostname."]
    if "/api/projects/" not in parsed.path:
        return [
            "Foundry project endpoint should look like "
            "https://<resource>.services.ai.azure.com/api/projects/<project-name>."
        ]
    project_name = parsed.path.split("/api/projects/", 1)[-1].strip("/")
    if not project_name:
        return ["Foundry project endpoint is missing the project name after /api/projects/."]
    return []


def _api_message(details: dict[str, Any]) -> str | None:
    response_body = details.get("response_body")
    if isinstance(response_body, dict):
        for key in ("message", "error_message", "detail"):
            value = response_body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
        nested = response_body.get("error")
        if isinstance(nested, dict):
            value = nested.get("message") or nested.get("code")
            if isinstance(value, str) and value.strip():
                return value.strip()[:500]
    message = details.get("message")
    return message if isinstance(message, str) and message.strip() else None


def _summarize_response_body(body: Any) -> Any:
    if isinstance(body, list):
        return [_summarize_response_body(item) for item in body[:5]]
    if not isinstance(body, dict):
        return body
    summary: dict[str, Any] = {}
    for key in ("error", "message", "detail", "code", "type", "param"):
        if key in body:
            summary[key] = body[key]
    if "error" in body and isinstance(body["error"], dict):
        summary["error"] = {
            key: body["error"][key]
            for key in ("message", "code", "type", "param")
            if key in body["error"]
        }
    if not summary:
        summary = {key: body[key] for key in list(body.keys())[:6]}
    return redact_secrets(summary)
