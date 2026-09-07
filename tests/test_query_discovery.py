import socket

import pytest

from core.query_discovery import (
    GeneratorResult,
    QueryCandidate,
    QueryDiscoveryError,
    _EvidenceParser,
    _redact_url,
    build_query_prompt,
    merge_candidates,
    parse_query_candidates,
    select_useful_chunks,
    validate_public_url,
)
from core.query_discovery import PageEvidence


HTML = """
<!doctype html>
<html lang="en">
  <head>
    <title>Harbour Hotel Hong Kong | Example Hospitality</title>
    <meta name="description" content="Luxury rooms and harbour-view dining in Central Hong Kong.">
    <link rel="canonical" href="https://example.com/hong-kong/harbour-hotel">
    <script>secretNavigationNoise()</script>
  </head>
  <body>
    <nav><p>This navigation copy must be ignored even though it is long enough.</p></nav>
    <main>
      <h1>Harbour Hotel in Central Hong Kong</h1>
      <p>Stay beside Victoria Harbour with family suites, a rooftop pool, and restaurants near Central.</p>
      <h2>Harbour-view dining and family stays</h2>
      <p>Guests can reserve Cantonese dining, afternoon tea, and connecting rooms for family holidays.</p>
    </main>
  </body>
</html>
"""


def test_dom_parser_selects_high_signal_chunks():
    parser = _EvidenceParser()
    parser.feed(HTML)
    chunks = select_useful_chunks(parser)

    assert parser.title == "Harbour Hotel Hong Kong | Example Hospitality"
    assert parser.description == "Luxury rooms and harbour-view dining in Central Hong Kong."
    assert parser.language == "en"
    assert chunks[0].kind == "title"
    assert any(chunk.kind == "h1" for chunk in chunks)
    assert any("rooftop pool" in chunk.text for chunk in chunks)
    assert all("navigation copy" not in chunk.text for chunk in chunks)
    assert all("secretNavigationNoise" not in chunk.text for chunk in chunks)


def test_prompt_uses_selected_dom_evidence():
    parser = _EvidenceParser()
    parser.feed(HTML)
    evidence = PageEvidence(
        requested_url="https://example.com/hotel",
        final_url="https://example.com/hotel",
        title=parser.title,
        description=parser.description,
        language=parser.language,
        chunks=select_useful_chunks(parser),
    )

    prompt = build_query_prompt(evidence, 6)
    assert "Generate exactly 6 distinct queries" in prompt
    assert "Harbour Hotel in Central Hong Kong" in prompt
    assert "Do not include the URL itself as the query" in prompt


def test_query_parser_accepts_fenced_json():
    candidates = parse_query_candidates(
        """```json
        {"queries":[
          {"query":"family hotels near Central Hong Kong","rationale":"Family suites","evidence":"connecting rooms"},
          {"query":"harbour view afternoon tea Hong Kong","rationale":"Dining intent","evidence":"afternoon tea"}
        ]}
        ```""",
        "gemini",
        6,
    )

    assert [candidate.query for candidate in candidates] == [
        "family hotels near Central Hong Kong",
        "harbour view afternoon tea Hong Kong",
    ]
    assert candidates[0].generators == ("gemini",)


def test_candidate_merge_round_robins_and_deduplicates():
    results = [
        GeneratorResult(
            "gemini",
            "Gemini",
            "gemini-test",
            "complete",
            10,
            queries=[
                QueryCandidate("Harbour hotel Hong Kong", generators=("gemini",)),
                QueryCandidate("Family suites Central", generators=("gemini",)),
            ],
        ),
        GeneratorResult(
            "openai",
            "OpenAI",
            "gpt-test",
            "complete",
            12,
            queries=[
                QueryCandidate("Harbour hotel Hong Kong", generators=("openai",)),
                QueryCandidate("Rooftop pool hotels Hong Kong", generators=("openai",)),
            ],
        ),
    ]

    merged = merge_candidates(results, 3)
    assert len(merged) == 3
    assert merged[0].generators == ("gemini", "openai")
    assert merged[1].query == "Family suites Central"
    assert merged[2].query == "Rooftop pool hotels Hong Kong"


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
