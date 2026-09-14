import socket

import pytest

from core.query_discovery import (
    BROWSER_USER_AGENT,
    TRANSPARENT_USER_AGENT,
    PageEvidence,
    QueryDiscoveryError,
    _EvidenceParser,
    _redact_url,
    build_fetch_headers,
    build_page_evidence_from_content,
    discover_queries,
    extract_snippet_window,
    select_page_snippets,
    select_useful_chunks,
    validate_public_url,
)
from core.query_discovery_config import DEFAULT_FETCH_PROFILE


HTML = """
<!doctype html>
<html lang="en">
  <head>
    <title>Calder House Observatory Suites</title>
    <meta name="description" content="Distinctive observatory hotel suites with private terraces and resident astronomer experiences in the historic Ashbourne district for curious travellers seeking memorable night-sky stays.">
    <script>secretNavigationNoise()</script>
  </head>
  <body>
    <nav><p>This navigation copy must be ignored even though it is long enough to look like useful content for a page snippet suggestion.</p></nav>
    <main>
      <h1>Calder House Observatory Suites in Ashbourne</h1>
      <p>The Calder House Meridian Suite includes a hand-carved walnut desk, room 417, and a private terrace overlooking the Ashbourne Observatory, with bespoke brass lighting designed by Eleanor Voss.</p>
      <p>The rooftop telescope session begins at 9:15pm every Thursday and is limited to twelve registered guests, who receive a printed celestial map and guidance from the resident astronomer.</p>
      <p>The archive displays three notebooks written by expedition leader Mara Bell during the 1927 Kestrel survey, alongside the original silver navigation instrument used on the journey.</p>
    </main>
  </body>
</html>
"""


def test_dom_parser_selects_high_signal_chunks():
    parser = _EvidenceParser()
    parser.feed(HTML)
    chunks = select_useful_chunks(parser)

    assert parser.title == "Calder House Observatory Suites"
    assert parser.language == "en"
    assert any(chunk.kind == "h1" for chunk in chunks)
    assert any("room 417" in chunk.text for chunk in chunks)
    assert all("navigation copy" not in chunk.text for chunk in chunks)
    assert all("secretNavigationNoise" not in chunk.text for chunk in chunks)


def test_select_page_snippets_returns_unchanged_20_to_30_word_passages():
    evidence = build_page_evidence_from_content(
        HTML,
        source_url="https://example.com/calder-house",
    )
    snippets = select_page_snippets(evidence, limit=5)

    assert len(snippets) >= 3
    for item in snippets:
        assert item.evidence and item.query in item.evidence
        assert 20 <= len(item.query.split()) <= 30
        assert item.generators == ("page_snippet",)
        assert "retrieve a web page" not in item.query


def test_extract_snippet_window_preserves_exact_text():
    source = (
        "The Calder House Meridian Suite includes a hand-carved walnut desk, room 417, "
        "and a private terrace overlooking the Ashbourne Observatory, with bespoke brass "
        "lighting designed by Eleanor Voss."
    )
    snippet = extract_snippet_window(source)
    assert snippet is not None
    assert snippet in source


def test_discover_queries_uses_paste_without_fetch_or_generator(monkeypatch):
    def fail_fetch(*args, **kwargs):
        raise AssertionError("fetch should be skipped when pasted content is supplied")

    monkeypatch.setattr("core.query_discovery.fetch_page_evidence", fail_fetch)
    result = discover_queries(
        "https://example.com/calder-house",
        openai_config={"api_key": "unused"},
        gemini_config={"api_key": "unused"},
        page_content=HTML,
    )

    assert result.evidence is not None
    assert result.evidence.input_source == "paste"
    assert result.candidates
    assert result.generators == []
    assert all(item.generators == ("page_snippet",) for item in result.candidates)


def test_short_page_returns_actionable_error():
    evidence = PageEvidence(
        requested_url="pasted-content",
        final_url="pasted-content",
        chunks=[],
    )
    assert select_page_snippets(evidence) == []


def test_url_validation_rejects_private_addresses(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    with pytest.raises(QueryDiscoveryError, match="non-public"):
        validate_public_url("https://localhost/private")


def test_url_validation_accepts_public_addresses(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))
        ],
    )
    assert validate_public_url("https://example.com/page") == ["93.184.216.34"]


def test_sensitive_url_query_values_are_redacted():
    redacted = _redact_url(
        "https://example.com/page?id=42&access_token=secret&signature=signed"
    )
    assert "id=42" in redacted
    assert "secret" not in redacted
    assert "signed" not in redacted


def test_fetch_headers_support_both_profiles():
    browser = build_fetch_headers(
        fetch_profile=DEFAULT_FETCH_PROFILE,
        accept_language="en-GB",
    )
    transparent = build_fetch_headers(fetch_profile="transparent")
    assert browser["User-Agent"] == BROWSER_USER_AGENT
    assert browser["Accept-Language"].startswith("en-GB")
    assert transparent["User-Agent"] == TRANSPARENT_USER_AGENT


def test_build_page_evidence_from_plain_text():
    pasted = (
        "Calder House Observatory Suites\n\n"
        "The rooftop telescope session begins at 9:15pm every Thursday and is limited "
        "to twelve registered guests, who receive a printed celestial map and guidance "
        "from the resident astronomer."
    )
    evidence = build_page_evidence_from_content(
        pasted,
        source_url="https://example.com/calder-house",
    )
    assert evidence.input_source == "paste"
    assert evidence.content_type == "text/plain"
    assert any("telescope session" in chunk.text for chunk in evidence.chunks)
