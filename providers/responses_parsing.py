from __future__ import annotations

import re
from typing import Any

from core.enums import ObservationState
from core.models import Citation, GeneratedQuery, GroundingRequest

from .base import GroundingProvider

URL_FIELD_KEYS = ("url", "link", "href", "source_url", "uri", "source")
CITATION_ANNOTATION_TYPES = frozenset(
    {
        "url_citation",
        "citation",
        "web_search_result_location",
        "file_citation",
    }
)
SOURCE_CONTAINER_KEYS = (
    "sources",
    "results",
    "pages",
    "items",
    "web_results",
    "search_results",
)
RESPONSES_INCLUDE_FIELDS = (
    "web_search_call.action.sources",
    "web_search_call.results",
)
_MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")
_HTML_LINK = re.compile(
    r'<a\b[^>]*\bhref=["\'](https?://[^"\']+)["\'][^>]*>(.*?)</a>',
    re.I | re.S,
)
_WS_CALL_ID_SUFFIX = re.compile(r"(?:^|[,\s;]+)ws_call_id=[^\s,;]+", re.I)


def extract_url(record: Any) -> str | None:
    if isinstance(record, str) and record.strip().lower().startswith(("http://", "https://")):
        return record.strip()
    if not isinstance(record, dict):
        return None
    for key in URL_FIELD_KEYS:
        value = record.get(key)
        if isinstance(value, str) and value.strip().lower().startswith(("http://", "https://")):
            return value.strip()
    nested = record.get("page") or record.get("result") or record.get("document")
    if isinstance(nested, dict):
        return extract_url(nested)
    return None


def extract_query_text(value: Any) -> str | None:
    if isinstance(value, str):
        return normalize_generated_query(value)
    if isinstance(value, (int, float, bool)):
        return normalize_generated_query(str(value))
    if isinstance(value, dict):
        for key in ("query", "search_query", "text", "q"):
            nested = value.get(key)
            if nested is None:
                continue
            text = extract_query_text(nested)
            if text:
                return text
    return None


def normalize_generated_query(value: str) -> str | None:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text or text.lower() == "[object object]":
        return None
    text = _WS_CALL_ID_SUFFIX.sub("", text).strip(" ,;")
    if not text or len(text) > 300:
        return None
    return text


def extract_title(record: dict[str, Any]) -> str | None:
    for key in ("title", "name", "page_title", "site_name"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def iter_source_records(container: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if isinstance(container, list):
        for item in container:
            if isinstance(item, dict):
                records.append(item)
            elif isinstance(item, str) and extract_url(item):
                records.append({"url": extract_url(item)})
    elif isinstance(container, dict):
        for key in SOURCE_CONTAINER_KEYS:
            nested = container.get(key)
            if isinstance(nested, list):
                records.extend(iter_source_records(nested))
        if extract_url(container):
            records.append(container)
    return records


def collect_search_sources(item: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    observed_fields: list[str] = []
    records: list[dict[str, Any]] = []
    action = item.get("action")
    if isinstance(action, dict):
        for key in SOURCE_CONTAINER_KEYS:
            if key in action:
                observed_fields.append(f"action.{key}")
                records.extend(iter_source_records(action.get(key)))
        if extract_url(action):
            observed_fields.append("action")
            origin = (
                "open_page"
                if str(action.get("type") or "").lower() == "open_page"
                else "action"
            )
            records.append({**action, "source_origin": origin})
    for key in ("results", "sources"):
        if key in item:
            observed_fields.append(key)
            records.extend(iter_source_records(item.get(key)))
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        url = extract_url(record)
        if not url or url in seen:
            continue
        seen.add(url)
        deduped.append(record)
    return deduped, observed_fields


def slice_cited_text(text: str, start: Any, end: Any) -> str | None:
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    try:
        return text.encode("utf-8")[start:end].decode("utf-8")
    except UnicodeDecodeError:
        try:
            return text[start:end]
        except IndexError:
            return None


def parse_structured_annotations(
    provider: GroundingProvider,
    request: GroundingRequest,
    *,
    text: str,
    annotations: list[Any],
    output_index: int,
    content_index: int,
) -> tuple[list[Citation], list[dict[str, Any]]]:
    citations: list[Citation] = []
    anchor_references: list[dict[str, Any]] = []
    for annotation in annotations:
        if not isinstance(annotation, dict):
            continue
        annotation_type = str(annotation.get("type") or "")
        if annotation_type and annotation_type not in CITATION_ANNOTATION_TYPES:
            continue
        start = annotation.get("start_index")
        end = annotation.get("end_index")
        cited_text = slice_cited_text(text, start, end)
        title = annotation.get("title") or annotation.get("name")
        url = extract_url(annotation)
        if url:
            citations.append(
                provider.build_citation(
                    request,
                    url,
                    title=title if isinstance(title, str) else None,
                    start_index=start if isinstance(start, int) else None,
                    end_index=end if isinstance(end, int) else None,
                    cited_text=cited_text,
                    metadata={
                        **{
                            key: value
                            for key, value in annotation.items()
                            if key
                            not in {
                                "type",
                                "url",
                                "link",
                                "href",
                                "title",
                                "start_index",
                                "end_index",
                            }
                        },
                        "output_index": output_index,
                        "content_index": content_index,
                        "annotation_type": annotation_type or None,
                        "citation_origin": "structured_annotation",
                    },
                )
            )
            continue
        if cited_text or title:
            anchor_references.append(
                {
                    "title": title,
                    "cited_text": cited_text,
                    "start_index": start,
                    "end_index": end,
                    "annotation_type": annotation_type or None,
                    "output_index": output_index,
                    "content_index": content_index,
                    "note": "Provider returned anchor text without a URL; target matching requires a URL.",
                }
            )
    return citations, anchor_references


def parse_markdown_link_citations(
    provider: GroundingProvider,
    request: GroundingRequest,
    text: str,
) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[str] = set()
    for match in _MARKDOWN_LINK.finditer(text):
        anchor_text, url = match.group(1).strip(), match.group(2).strip()
        if url in seen:
            continue
        seen.add(url)
        citations.append(
            provider.build_citation(
                request,
                url,
                title=anchor_text or None,
                start_index=match.start(),
                end_index=match.end(),
                cited_text=anchor_text or None,
                metadata={"citation_origin": "markdown_link"},
            )
        )
    return citations


def parse_html_link_citations(
    provider: GroundingProvider,
    request: GroundingRequest,
    text: str,
) -> list[Citation]:
    citations: list[Citation] = []
    seen: set[str] = set()
    for match in _HTML_LINK.finditer(text):
        url = match.group(1).strip()
        anchor_text = re.sub(r"<[^>]+>", "", match.group(2))
        anchor_text = re.sub(r"\s+", " ", anchor_text).strip()
        if url in seen:
            continue
        seen.add(url)
        citations.append(
            provider.build_citation(
                request,
                url,
                title=anchor_text or None,
                start_index=match.start(),
                end_index=match.end(),
                cited_text=anchor_text or None,
                metadata={"citation_origin": "html_link"},
            )
        )
    return citations
