import socket

import pytest

from core.query_discovery import (
    BROWSER_USER_AGENT,
    GeneratorResult,
    QueryCandidate,
    QueryDiscoveryError,
    TRANSPARENT_USER_AGENT,
    _EvidenceParser,
    _redact_url,
    build_fetch_headers,
    build_page_evidence_from_content,
    build_query_prompt,
    build_term_seeded_queries,
    discover_queries,
    extract_key_terms,
    merge_candidates,
    parse_query_candidates,
    query_uses_page_terms,
    select_useful_chunks,
    validate_public_url,
)
from core.query_discovery_config import FETCH_PROFILES, DEFAULT_FETCH_PROFILE
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
    evidence.key_terms = extract_key_terms(evidence)

    prompt = build_query_prompt(evidence, 6)
    assert "Generate exactly 6 distinct queries" in prompt
    assert "Harbour Hotel in Central Hong Kong" in prompt
    assert "<KEY_TERMS>" in prompt
    assert "harbour hotel" in prompt.lower()
    assert "Every query you return MUST incorporate at least one KEY_TERM" in prompt
    assert "Do not include the URL itself as the query" in prompt


def test_extract_key_terms_from_page_evidence():
    evidence = build_page_evidence_from_content(HTML, source_url="https://example.com/hotel")
    terms = extract_key_terms(evidence)
    assert "harbour hotel" in terms
    assert any("rooftop pool" in term for term in terms)
    assert "the" not in terms


def test_term_seeded_queries_use_page_vocabulary():
    evidence = build_page_evidence_from_content(HTML, source_url="https://example.com/hotel")
    evidence.key_terms = extract_key_terms(evidence)
    seeded = build_term_seeded_queries(evidence, evidence.key_terms, limit=6)
    assert seeded
    assert all(query_uses_page_terms(item.query, evidence.key_terms) for item in seeded)
    assert all("page_terms" in item.generators for item in seeded)


def test_merge_candidates_prefers_term_seeded_seed():
    seed = [
        QueryCandidate("Harbour hotel Hong Kong", generators=("page_terms",)),
        QueryCandidate("Family suites Central", generators=("page_terms",)),
    ]
    results = [
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
    merged = merge_candidates(results, 3, seed=seed)
    assert merged[0].generators == ("page_terms", "openai")
    assert merged[1].query == "Family suites Central"
    assert merged[2].query == "Rooftop pool hotels Hong Kong"


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


def test_browser_fetch_headers_use_mainstream_user_agent():
    headers = build_fetch_headers(fetch_profile=DEFAULT_FETCH_PROFILE, accept_language="en-GB")
    assert headers["User-Agent"] == BROWSER_USER_AGENT
    assert "Chrome" in headers["User-Agent"]
    assert headers["Accept-Language"].startswith("en-GB")


def test_transparent_fetch_headers_keep_identifiable_bot():
    headers = build_fetch_headers(fetch_profile="transparent")
    assert headers["User-Agent"] == TRANSPARENT_USER_AGENT


def test_build_page_evidence_from_pasted_html():
    evidence = build_page_evidence_from_content(HTML, source_url="https://example.com/hotel")
    assert evidence.input_source == "paste"
    assert evidence.title == "Harbour Hotel Hong Kong | Example Hospitality"
    assert evidence.chunks
    assert evidence.http_status is None


def test_build_page_evidence_from_plain_text():
    pasted = (
        "Harbour Hotel in Central Hong Kong\n\n"
        "Stay beside Victoria Harbour with family suites, a rooftop pool, and restaurants near Central.\n\n"
        "Guests can reserve Cantonese dining, afternoon tea, and connecting rooms for family holidays."
    )
    evidence = build_page_evidence_from_content(pasted, source_url="https://example.com/hotel")
    assert evidence.input_source == "paste"
    assert evidence.content_type == "text/plain"
    assert any("rooftop pool" in chunk.text for chunk in evidence.chunks)


def test_discover_queries_uses_paste_without_fetch(monkeypatch):
    def fail_fetch(*args, **kwargs):
        raise AssertionError("fetch should be skipped when pasted content is supplied")

    monkeypatch.setattr("core.query_discovery.fetch_page_evidence", fail_fetch)
    monkeypatch.setattr(
        "core.query_discovery._generate_openai",
        lambda prompt, config, debug: GeneratorResult(
            "openai",
            "OpenAI",
            "gpt-test",
            "complete",
            1,
            queries=[QueryCandidate("family hotels Central Hong Kong", generators=("openai",))],
        ),
    )
    monkeypatch.setattr("core.query_discovery._generate_gemini", lambda *args, **kwargs: GeneratorResult(
        "gemini", "Gemini", "gemini-test", "complete", 1, queries=[]
    ))

    result = discover_queries(
        "https://example.com/hotel",
        openai_config={"api_key": "secret", "model": "gpt-5.5"},
        page_content=HTML,
    )
    assert result.evidence is not None
    assert result.evidence.input_source == "paste"
    assert result.evidence.key_terms
    assert result.candidates
