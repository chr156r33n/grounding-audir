from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from .enums import ErrorType, MatchMode, ObservationState, ProviderType, RunStatus


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Target:
    value: str
    match_mode: MatchMode = MatchMode.ROOT_DOMAIN


@dataclass
class GroundingRequest:
    run_id: str
    input_phrase: str
    targets: list[Target]
    market: str | None = None
    language: str | None = None
    provider_options: dict[str, Any] = field(default_factory=dict)
    queries: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.queries:
            self.queries = [self.input_phrase]


@dataclass
class GeneratedQuery:
    query: str
    sequence: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ObservedSource:
    raw_url: str
    normalized_url: str | None = None
    hostname: str | None = None
    registrable_domain: str | None = None
    title: str | None = None
    snippet: str | None = None
    content: str | None = None
    retrieval_position: int | None = None
    retrieved: ObservationState = ObservationState.UNKNOWN
    cited: ObservationState = ObservationState.NO
    target_matches: list[str] = field(default_factory=list)
    provider_source_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Citation:
    url: str
    title: str | None = None
    start_index: int | None = None
    end_index: int | None = None
    cited_text: str | None = None
    target_matches: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class GroundingContent:
    text: str | None = None
    source_url: str | None = None
    source_index: int | None = None
    response_segment: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProviderError:
    type: ErrorType
    safe_message: str
    status_code: int | None = None
    provider_code: str | None = None
    retryable: bool = False


@dataclass(frozen=True)
class ProviderCapabilities:
    generated_queries: bool = False
    retrieved_sources: bool = False
    grounding_content: bool = False
    citations: bool = False
    response_text: bool = True
    market_control: bool = False
    language_control: bool = False
    freshness_control: bool = False
    can_force_search: bool = False


@dataclass(frozen=True)
class ProviderField:
    key: str
    label: str
    secret: bool = False
    required: bool = True
    default: str = ""
    help: str | None = None


@dataclass
class GroundingRun:
    run_id: str
    provider_id: str
    provider_name: str
    provider_type: ProviderType
    input_phrase: str
    model: str | None = None
    api_version: str | None = None
    started_at: str = field(default_factory=utc_now)
    finished_at: str | None = None
    latency_ms: int | None = None
    search_performed: ObservationState = ObservationState.UNKNOWN
    generated_queries: list[GeneratedQuery] = field(default_factory=list)
    sources: list[ObservedSource] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    grounding_content: list[GroundingContent] = field(default_factory=list)
    target_retrieved: ObservationState = ObservationState.UNKNOWN
    target_cited: ObservationState = ObservationState.UNKNOWN
    response_text: str | None = None
    status: RunStatus = RunStatus.PENDING
    error: ProviderError | None = None
    raw_response: dict[str, Any] | list[Any] | str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, include_raw: bool = True) -> dict[str, Any]:
        value = asdict(self)
        if not include_raw:
            value.pop("raw_response", None)
        return value
