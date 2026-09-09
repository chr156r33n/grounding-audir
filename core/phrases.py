from __future__ import annotations

import re


def split_input_phrases(value: str) -> list[str]:
    """Split a grounding/search phrase box into distinct queries."""
    if not value or not value.strip():
        return []
    parts = re.split(r"[\n,]+", value)
    phrases: list[str] = []
    seen: set[str] = set()
    for part in parts:
        phrase = re.sub(r"\s+", " ", part).strip()
        if not phrase:
            continue
        key = phrase.casefold()
        if key in seen:
            continue
        seen.add(key)
        phrases.append(phrase)
    return phrases
