from __future__ import annotations

import re

from .enums import ObservationState

MAX_PATTERN_LENGTH = 200
MAX_RESPONSE_LENGTH = 200_000
MAX_MATCHES = 10


def compile_brand_regex(pattern: str | None) -> re.Pattern[str] | None:
    value = str(pattern or "").strip()
    if not value:
        return None
    if len(value) > MAX_PATTERN_LENGTH:
        raise ValueError(f"Brand regex must be {MAX_PATTERN_LENGTH} characters or fewer.")
    try:
        return re.compile(value, re.IGNORECASE | re.UNICODE)
    except re.error as exc:
        raise ValueError(f"Brand regex is invalid: {exc}") from exc


def match_brand(
    response_text: str | None,
    pattern: str | None,
) -> tuple[ObservationState, list[str]]:
    regex = compile_brand_regex(pattern)
    if not regex:
        return ObservationState.NOT_APPLICABLE, []
    if not response_text:
        return ObservationState.UNKNOWN, []

    matches: list[str] = []
    seen: set[str] = set()
    for match in regex.finditer(response_text[:MAX_RESPONSE_LENGTH]):
        value = match.group(0)
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            matches.append(value)
        if len(matches) >= MAX_MATCHES:
            break
    return (ObservationState.YES if matches else ObservationState.NO), matches
