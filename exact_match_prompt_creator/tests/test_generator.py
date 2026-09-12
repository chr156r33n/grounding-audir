import socket

import pytest

from exact_match_prompt_creator.generator import (
    PromptCreatorError,
    evidence_from_content,
    extract_exact_phrase,
    generate_prompts,
    select_anchor_passages,
    validate_public_url,
)


HTML = """
<!doctype html>
<html>
  <head>
    <title>Harbour Hotel Hong Kong</title>
    <meta name="description"
          content="Luxury rooms and harbour-view dining in Central Hong Kong.">
    <script>ignoreThisInstruction()</script>
  </head>
  <body>
    <nav><p>This navigation sentence is deliberately long and must be ignored.</p></nav>
    <main>
      <h1>Family stays beside Victoria Harbour</h1>
      <p>Guests can book connecting family suites with private balconies overlooking
      Victoria Harbour and the Central skyline.</p>
      <p>The rooftop pool opens from 7am until 9pm and includes a shallow children's
      area beside the garden terrace.</p>
      <h2>Cantonese dining and afternoon tea</h2>
      <p>The harbour-view restaurant serves traditional Cantonese tasting menus and
      afternoon tea every Friday, Saturday, and Sunday.</p>
    </main>
  </body>
</html>
"""


def test_html_evidence_excludes_scripts_and_navigation():
    evidence = evidence_from_content(HTML, source="https://example.com/hotel")

    assert evidence.title == "Harbour Hotel Hong Kong"
    assert evidence.content_type == "text/html"
    assert any("rooftop pool" in chunk.text for chunk in evidence.chunks)
    assert all("navigation sentence" not in chunk.text for chunk in evidence.chunks)
    assert all("ignoreThisInstruction" not in chunk.text for chunk in evidence.chunks)


def test_anchor_selection_prefers_specific_page_facts():
    evidence = evidence_from_content(HTML)
    anchors = select_anchor_passages(evidence, limit=4)

    assert len(anchors) >= 3
    assert any("7am until 9pm" in anchor for anchor in anchors)
    assert any("Cantonese" in anchor for anchor in anchors)


def test_exact_match_prompts_include_verbatim_phrase():
    evidence = evidence_from_content(HTML)

    def fake_generator(instructions):
        assert all("Return only the question" in item for item in instructions)
        return [
            "When is the rooftop pool open?",
            "What kind of dining is available?",
            "Which family accommodation can guests book?",
            "Where can guests have afternoon tea?",
        ][: len(instructions)]

    prompts = generate_prompts(
        evidence,
        count=4,
        generator=fake_generator,
        exact_match=True,
    )

    assert len(prompts) >= 3
    assert all(candidate.exact_phrase in candidate.source_excerpt for candidate in prompts)
    assert all(
        f'exact phrase "{candidate.exact_phrase}"' in candidate.prompt
        for candidate in prompts
    )


def test_ungrounded_model_output_uses_safe_fallback():
    evidence = evidence_from_content(HTML)
    prompts = generate_prompts(
        evidence,
        count=3,
        generator=lambda instructions: ["Tell me a joke."] * len(instructions),
        exact_match=False,
    )

    assert prompts
    assert all(item.generation_method == "template_fallback" for item in prompts)
    assert all(item.prompt.endswith("?") for item in prompts)


def test_extract_exact_phrase_is_verbatim_and_bounded():
    text = (
        "Guests can book connecting family suites with private balconies "
        "overlooking Victoria Harbour."
    )
    phrase = extract_exact_phrase(text)

    assert phrase in text
    assert 5 <= len(phrase.split()) <= 10


def test_url_validation_rejects_private_addresses(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )

    with pytest.raises(PromptCreatorError, match="non-public"):
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
