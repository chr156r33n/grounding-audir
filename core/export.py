from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import asdict
from typing import Any

from .matching import normalize_url, registrable_domain
from .models import GroundingRequest, GroundingRun

_SECRET_KEY = re.compile(
    r"(^|[_.-])(api[_.-]?key|apikey|authorization|bearer|credentials?|password|secret|"
    r"access[_.-]?token|accesstoken|refresh[_.-]?token|refreshtoken|id[_.-]?token|"
    r"idtoken|token)($|[_.-])",
    re.I,
)
_BEARER_VALUE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")

CSV_COLUMNS = [
    "run_id",
    "timestamp",
    "input_phrase",
    "target",
    "match_mode",
    "market",
    "language",
    "provider_id",
    "provider_type",
    "model",
    "search_performed",
    "generated_query",
    "source_url",
    "normalized_url",
    "registrable_domain",
    "retrieved",
    "cited",
    "target_match",
    "retrieval_position",
    "citation_start",
    "citation_end",
    "provider_status",
    "latency_ms",
]


def redact_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _SECRET_KEY.search(str(key)) else redact_secrets(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_secrets(item) for item in value]
    if isinstance(value, tuple):
        return [redact_secrets(item) for item in value]
    if isinstance(value, str):
        return _BEARER_VALUE.sub("Bearer [REDACTED]", value)
    return value


def export_json(
    request: GroundingRequest,
    runs: list[GroundingRun],
    *,
    include_raw: bool = False,
) -> str:
    payload = {
        "experiment": {
            "run_id": request.run_id,
            "queries": request.queries,
            "targets": [asdict(target) for target in request.targets],
            "market": request.market,
            "language": request.language,
            "selected_providers": [run.provider_id for run in runs],
        },
        "provider_runs": [run.to_dict(include_raw=include_raw) for run in runs],
    }
    return json.dumps(redact_secrets(payload), indent=2, ensure_ascii=False)


def export_csv(request: GroundingRequest, runs: list[GroundingRun]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    target = request.targets[0] if request.targets else None
    for run in runs:
        base = {
            "run_id": run.run_id,
            "timestamp": run.started_at,
            "input_phrase": run.input_phrase,
            "target": target.value if target else "",
            "match_mode": target.match_mode.value if target else "",
            "market": request.market or "",
            "language": request.language or "",
            "provider_id": run.provider_id,
            "provider_type": run.provider_type.value,
            "model": run.model or "",
            "search_performed": run.search_performed.value,
            "provider_status": run.status.value,
            "latency_ms": run.latency_ms if run.latency_ms is not None else "",
        }
        queries = [item.query for item in run.generated_queries] or [""]
        if run.sources:
            for index, source in enumerate(run.sources):
                writer.writerow(
                    {
                        **base,
                        "generated_query": queries[min(index, len(queries) - 1)],
                        "source_url": source.raw_url,
                        "normalized_url": source.normalized_url or "",
                        "registrable_domain": source.registrable_domain or "",
                        "retrieved": source.retrieved.value,
                        "cited": source.cited.value,
                        "target_match": ",".join(source.target_matches),
                        "retrieval_position": source.retrieval_position or "",
                    }
                )
        if run.citations:
            for index, citation in enumerate(run.citations):
                writer.writerow(
                    {
                        **base,
                        "generated_query": queries[min(index, len(queries) - 1)],
                        "source_url": citation.url,
                        "normalized_url": normalize_url(citation.url) or "",
                        "registrable_domain": registrable_domain(citation.url) or "",
                        "retrieved": "unknown",
                        "cited": "yes",
                        "target_match": ",".join(citation.target_matches),
                        "citation_start": (
                            citation.start_index if citation.start_index is not None else ""
                        ),
                        "citation_end": citation.end_index if citation.end_index is not None else "",
                    }
                )
        if not run.sources and not run.citations:
            writer.writerow(
                {
                    **base,
                    "generated_query": queries[0],
                    "retrieved": run.target_retrieved.value,
                    "cited": run.target_cited.value,
                }
            )
    return output.getvalue()
