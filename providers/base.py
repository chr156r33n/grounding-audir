from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import asdict, is_dataclass
from typing import Any
from urllib.parse import urlsplit

from core.diagnostics import attach_observation_diagnostics
from core.enums import ObservationState, ProviderType, RunStatus
from core.matching import matching_targets, normalize_url, registrable_domain
from core.models import (
    Citation,
    GroundingRequest,
    GroundingRun,
    ObservedSource,
    ProviderCapabilities,
    ProviderField,
)

CANONICAL_INSTRUCTION = """Use web search to answer the following query.
Ground the response using current public web sources.
Use the web/search tool for this request rather than relying only on model memory.

Query:
{query}"""


def as_plain_data(value: Any) -> dict[str, Any] | list[Any] | str | None:
    if value is None or isinstance(value, (dict, list, str)):
        return value
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    try:
        return json.loads(json.dumps(value, default=str))
    except (TypeError, ValueError):
        return str(value)


class GroundingProvider(ABC):
    id: str
    name: str
    provider_type = ProviderType.GROUNDING
    default_model: str
    api_version: str | None = None
    fields: tuple[ProviderField, ...] = ()
    capabilities = ProviderCapabilities()

    def validate_config(self, config: dict[str, Any]) -> list[str]:
        errors = [
            f"{item.label} is required."
            for item in self.fields
            if item.required and not str(config.get(item.key, "")).strip()
        ]
        for item in self.fields:
            if not item.choices:
                continue
            value = str(config.get(item.key, "")).strip()
            if value and value not in item.choices:
                errors.append(
                    f"{item.label} must be one of the documented options: "
                    f"{', '.join(item.choices)}."
                )
        return errors

    @abstractmethod
    def run(self, request: GroundingRequest, config: dict[str, Any]) -> GroundingRun:
        raise NotImplementedError

    @abstractmethod
    def parse_response(
        self,
        raw_response: Any,
        request: GroundingRequest,
        model: str | None = None,
    ) -> GroundingRun:
        raise NotImplementedError

    def new_run(self, request: GroundingRequest, model: str | None = None) -> GroundingRun:
        return GroundingRun(
            run_id=request.run_id,
            provider_id=self.id,
            provider_name=self.name,
            provider_type=self.provider_type,
            input_phrase=request.input_phrase,
            model=model or self.default_model,
            api_version=self.api_version,
            status=RunStatus.COMPLETE,
        )

    def build_source(
        self,
        request: GroundingRequest,
        url: str,
        *,
        title: str | None = None,
        snippet: str | None = None,
        content: str | None = None,
        position: int | None = None,
        retrieved: ObservationState = ObservationState.YES,
        cited: ObservationState = ObservationState.NO,
        metadata: dict[str, Any] | None = None,
    ) -> ObservedSource:
        normalized = normalize_url(url)
        return ObservedSource(
            raw_url=url,
            normalized_url=normalized,
            hostname=urlsplit(normalized or url).hostname if normalized else None,
            registrable_domain=registrable_domain(url),
            title=title,
            snippet=snippet,
            content=content,
            retrieval_position=position,
            retrieved=retrieved,
            cited=cited,
            target_matches=matching_targets(request.targets, url),
            metadata=metadata or {},
        )

    def build_citation(
        self,
        request: GroundingRequest,
        url: str,
        *,
        title: str | None = None,
        start_index: int | None = None,
        end_index: int | None = None,
        cited_text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Citation:
        return Citation(
            url=url,
            title=title,
            start_index=start_index,
            end_index=end_index,
            cited_text=cited_text,
            target_matches=matching_targets(request.targets, url),
            metadata=metadata or {},
        )

    def finish_states(
        self,
        run: GroundingRun,
        *,
        retrieval_complete: bool = False,
        citation_complete: bool = True,
    ) -> GroundingRun:
        run.target_retrieved = (
            ObservationState.YES
            if any(source.target_matches for source in run.sources)
            else ObservationState.NO
            if retrieval_complete
            else ObservationState.UNKNOWN
        )
        run.target_cited = (
            ObservationState.YES
            if any(citation.target_matches for citation in run.citations)
            else ObservationState.NO
            if citation_complete
            else ObservationState.UNKNOWN
        )
        return attach_observation_diagnostics(run)
