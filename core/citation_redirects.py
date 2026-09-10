from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlparse
from urllib.request import Request, urlopen

from .enums import MatchMode, ObservationState
from .matching import is_grounding_redirect_url, matching_targets

if TYPE_CHECKING:
    from .models import Citation, GroundingRequest

MAX_RESOLVE_ATTEMPTS = 12
MAX_REDIRECT_HOPS = 5
RESOLVE_TIMEOUT_SECONDS = 8.0
USER_AGENT = "GroundingObservatory/1.0 (+https://www.torquepartnership.com/)"


def embedded_grounding_target(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if "vertexaisearch.cloud.google.com" not in (parsed.hostname or "").lower():
        return None
    query = parse_qs(parsed.query)
    for key in ("url", "q"):
        values = query.get(key) or []
        for value in values:
            if value.startswith(("http://", "https://")):
                return value
    return None


def _follow_redirect_chain(url: str, *, timeout: float) -> tuple[str | None, str | None]:
    current = url
    for _ in range(MAX_REDIRECT_HOPS):
        if not is_grounding_redirect_url(current):
            return current, None

        advanced = False
        for method in ("HEAD", "GET"):
            request = Request(
                current,
                method=method,
                headers={"User-Agent": USER_AGENT},
            )
            try:
                with urlopen(request, timeout=timeout) as response:
                    resolved = response.geturl()
            except HTTPError as exc:
                location = exc.headers.get("Location") if exc.headers else None
                if exc.code in {301, 302, 303, 307, 308} and location:
                    current = urljoin(current, location)
                    advanced = True
                    break
                resolved = exc.geturl()
                if resolved and resolved != current and not is_grounding_redirect_url(resolved):
                    return resolved, None
                return None, f"http_{exc.code}"
            except URLError as exc:
                return None, str(exc.reason or exc)
            except TimeoutError:
                return None, "timeout"
            except OSError as exc:
                return None, str(exc)

            if resolved and resolved != current and not is_grounding_redirect_url(resolved):
                return resolved, None
        if not advanced:
            break
    if current != url and not is_grounding_redirect_url(current):
        return current, None
    return None, "redirect_unresolved"


def should_resolve_citation_redirects(request: GroundingRequest) -> bool:
    configured = request.provider_options.get("resolve_citation_redirects")
    if configured is not None:
        return bool(configured)
    return any(target.match_mode is MatchMode.URL_PREFIX for target in request.targets)


def resolve_grounding_redirect(
    url: str,
    *,
    timeout: float = RESOLVE_TIMEOUT_SECONDS,
) -> tuple[str | None, str | None]:
    if not is_grounding_redirect_url(url):
        return None, "not_a_grounding_redirect"

    embedded = embedded_grounding_target(url)
    if embedded and not is_grounding_redirect_url(embedded):
        return embedded, None

    return _follow_redirect_chain(url, timeout=timeout)


def enrich_citations_with_redirect_resolution(
    citations: list[Citation],
    request: GroundingRequest,
) -> None:
    if not should_resolve_citation_redirects(request):
        for citation in citations:
            citation.metadata["redirect_resolution"] = "skipped"
        return

    pending: list[str] = []
    seen: set[str] = set()
    for citation in citations:
        if not is_grounding_redirect_url(citation.url) or citation.target_matches:
            continue
        if citation.url in seen:
            continue
        seen.add(citation.url)
        pending.append(citation.url)
        if len(pending) >= MAX_RESOLVE_ATTEMPTS:
            break

    cache: dict[str, tuple[str | None, str | None]] = {
        url: resolve_grounding_redirect(url) for url in pending
    }

    for citation in citations:
        if not is_grounding_redirect_url(citation.url):
            citation.metadata["redirect_resolution"] = "skipped"
            continue
        if citation.target_matches:
            citation.metadata["redirect_resolution"] = "skipped"
            continue
        resolved_url, error = cache.get(citation.url, (None, "not_attempted"))
        if resolved_url:
            citation.metadata["resolved_url"] = resolved_url
            citation.metadata["redirect_resolution"] = "resolved"
            matches = matching_targets(request.targets, resolved_url)
            if matches:
                citation.target_matches = list(
                    dict.fromkeys([*citation.target_matches, *matches])
                )
        else:
            citation.metadata["redirect_resolution"] = "failed"
            if error:
                citation.metadata["redirect_resolution_error"] = error


def gemini_target_cited(
    citations: list[Citation],
    request: GroundingRequest,
) -> ObservationState:
    if any(citation.target_matches for citation in citations):
        return ObservationState.YES
    if not should_resolve_citation_redirects(request):
        return ObservationState.NO

    unresolved_redirects = any(
        is_grounding_redirect_url(citation.url)
        and not citation.target_matches
        and citation.metadata.get("redirect_resolution") == "failed"
        for citation in citations
    )
    if any(target.match_mode is MatchMode.URL_PREFIX for target in request.targets):
        if unresolved_redirects:
            return ObservationState.UNKNOWN
    return ObservationState.NO
