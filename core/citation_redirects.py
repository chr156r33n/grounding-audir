from __future__ import annotations

from typing import TYPE_CHECKING
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .enums import MatchMode, ObservationState
from .matching import is_grounding_redirect_url, matching_targets

if TYPE_CHECKING:
    from .models import Citation, GroundingRequest

MAX_RESOLVE_ATTEMPTS = 12
RESOLVE_TIMEOUT_SECONDS = 8.0
USER_AGENT = "GroundingObservatory/1.0 (+https://www.torquepartnership.com/)"


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
    request = Request(
        url,
        method="GET",
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            resolved = response.geturl()
    except HTTPError as exc:
        resolved = exc.geturl()
        if not resolved or resolved == url:
            return None, f"http_{exc.code}"
    except URLError as exc:
        return None, str(exc.reason or exc)
    except TimeoutError:
        return None, "timeout"
    except OSError as exc:
        return None, str(exc)

    if not resolved or resolved == url:
        return None, "redirect_unresolved"
    if is_grounding_redirect_url(resolved):
        return None, "redirect_still_opaque"
    return resolved, None


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
