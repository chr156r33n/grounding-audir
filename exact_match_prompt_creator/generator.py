from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_CONTENT_BYTES = 1_500_000
MAX_REDIRECTS = 5
FETCH_TIMEOUT_SECONDS = 15.0
MAX_CHUNKS = 12

_STOP_WORDS = frozenset(
    {
        "about",
        "after",
        "again",
        "also",
        "and",
        "are",
        "because",
        "been",
        "before",
        "being",
        "between",
        "both",
        "but",
        "can",
        "does",
        "for",
        "from",
        "had",
        "has",
        "have",
        "into",
        "its",
        "more",
        "most",
        "not",
        "only",
        "other",
        "our",
        "out",
        "over",
        "page",
        "say",
        "says",
        "source",
        "than",
        "that",
        "the",
        "their",
        "there",
        "these",
        "they",
        "this",
        "through",
        "under",
        "use",
        "using",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "while",
        "who",
        "will",
        "with",
        "would",
        "you",
        "your",
    }
)


class PromptCreatorError(ValueError):
    """An error that is safe to show in the Streamlit UI."""


@dataclass(frozen=True)
class EvidenceChunk:
    kind: str
    text: str
    score: int


@dataclass
class PageEvidence:
    source: str
    title: str | None = None
    description: str | None = None
    chunks: list[EvidenceChunk] = field(default_factory=list)
    content_type: str = "text/plain"
    downloaded_bytes: int = 0
    input_method: str = "paste"


@dataclass(frozen=True)
class PromptCandidate:
    prompt: str
    exact_phrase: str
    source_excerpt: str
    generation_method: str


BatchGenerator = Callable[[list[str]], list[str]]


def evidence_from_content(content: str, *, source: str = "") -> PageEvidence:
    text = content.strip()
    if not text:
        raise PromptCreatorError("Paste page HTML or visible page copy.")
    size = len(text.encode("utf-8"))
    if size > MAX_CONTENT_BYTES:
        raise PromptCreatorError(
            f"The pasted content exceeds the {MAX_CONTENT_BYTES:,}-byte limit."
        )

    if _looks_like_html(text):
        parser = _EvidenceParser()
        try:
            parser.feed(text)
            parser.close()
        except Exception as exc:
            raise PromptCreatorError("The pasted HTML could not be parsed.") from exc
        chunks = _select_chunks(parser)
        if not chunks:
            raise PromptCreatorError(
                "No useful title, headings, description, or body copy was found."
            )
        return PageEvidence(
            source=source.strip() or "pasted-content",
            title=parser.title,
            description=parser.description,
            chunks=chunks,
            content_type="text/html",
            downloaded_bytes=size,
            input_method="paste",
        )

    chunks = _plain_text_chunks(text)
    if not chunks:
        raise PromptCreatorError(
            "The pasted copy is too short. Paste several sentences from the page."
        )
    return PageEvidence(
        source=source.strip() or "pasted-content",
        title=chunks[0].text if chunks[0].kind == "title" else None,
        description=chunks[0].text[:240],
        chunks=chunks,
        downloaded_bytes=size,
        input_method="paste",
    )


def fetch_page_evidence(url: str) -> PageEvidence:
    current_url = _normalise_url(url)
    opener = build_opener(_NoRedirect())
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
    }

    for redirect_count in range(MAX_REDIRECTS + 1):
        validate_public_url(current_url)
        request = Request(current_url, headers=headers, method="GET")
        try:
            response = opener.open(request, timeout=FETCH_TIMEOUT_SECONDS)
        except HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                location = exc.headers.get("Location")
                if not location:
                    raise PromptCreatorError(
                        f"The URL returned redirect status {exc.code} without a destination."
                    ) from exc
                if redirect_count >= MAX_REDIRECTS:
                    raise PromptCreatorError(
                        f"The page exceeded the {MAX_REDIRECTS}-redirect limit."
                    ) from exc
                current_url = _normalise_url(urljoin(current_url, location))
                continue
            raise PromptCreatorError(
                f"The page returned HTTP {exc.code}. Paste its visible copy instead."
            ) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise PromptCreatorError(
                f"The page could not be downloaded ({type(exc).__name__})."
            ) from exc

        with response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                raise PromptCreatorError(
                    f"Expected an HTML page, but the server returned {content_type}."
                )
            body = response.read(MAX_CONTENT_BYTES + 1)
            if len(body) > MAX_CONTENT_BYTES:
                raise PromptCreatorError(
                    f"The page exceeds the {MAX_CONTENT_BYTES:,}-byte download limit."
                )
            charset = response.headers.get_content_charset() or "utf-8"
            try:
                html = body.decode(charset, errors="replace")
            except LookupError:
                html = body.decode("utf-8", errors="replace")

        evidence = evidence_from_content(html, source=current_url)
        evidence.input_method = "url"
        evidence.downloaded_bytes = len(body)
        return evidence

    raise PromptCreatorError(f"The page exceeded the {MAX_REDIRECTS}-redirect limit.")


def validate_public_url(url: str) -> list[str]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise PromptCreatorError("Only public HTTP(S) URLs are supported.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise PromptCreatorError("Enter a public URL with a valid hostname.")
    try:
        records = socket.getaddrinfo(
            parsed.hostname,
            parsed.port or (443 if parsed.scheme == "https" else 80),
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise PromptCreatorError("The URL hostname could not be resolved.") from exc
    addresses = sorted({record[4][0] for record in records})
    if not addresses:
        raise PromptCreatorError("The URL hostname did not resolve to an address.")
    for address in addresses:
        try:
            public_address = ipaddress.ip_address(address)
        except ValueError as exc:
            raise PromptCreatorError("The URL resolved to an invalid address.") from exc
        if not public_address.is_global:
            raise PromptCreatorError(
                "Private, loopback, link-local, and other non-public URLs are not allowed."
            )
    return addresses


def generate_prompts(
    evidence: PageEvidence,
    *,
    count: int,
    generator: BatchGenerator,
    exact_match: bool = True,
) -> list[PromptCandidate]:
    requested_count = max(3, min(int(count), 8))
    anchors = select_anchor_passages(evidence, limit=requested_count)
    if not anchors:
        raise PromptCreatorError("There was not enough specific page copy to create prompts.")

    instructions = [
        _generation_instruction(anchor, evidence.title) for anchor in anchors
    ]
    try:
        generated = generator(instructions)
    except Exception as exc:
        raise PromptCreatorError(
            "The local model could not generate prompts. Check the model download and retry."
        ) from exc

    candidates: list[PromptCandidate] = []
    seen: set[str] = set()
    for index, anchor in enumerate(anchors):
        raw = generated[index] if index < len(generated) else ""
        question = _clean_question(raw)
        method = "local_llm"
        if not _question_is_grounded(question, anchor):
            question = _fallback_question(anchor, evidence.title)
            method = "template_fallback"
        phrase = extract_exact_phrase(anchor)
        prompt = (
            f'{question} Base your answer on content containing the exact phrase "{phrase}".'
            if exact_match
            else question
        )
        key = re.sub(r"\W+", " ", prompt).strip().casefold()
        if key in seen:
            continue
        seen.add(key)
        candidates.append(
            PromptCandidate(
                prompt=prompt,
                exact_phrase=phrase,
                source_excerpt=anchor,
                generation_method=method,
            )
        )
        if len(candidates) >= requested_count:
            break
    return candidates


def select_anchor_passages(evidence: PageEvidence, *, limit: int = 6) -> list[str]:
    scored: list[tuple[int, str]] = []
    kind_bonus = {
        "meta_description": 35,
        "h1": 30,
        "h2": 22,
        "h3": 14,
        "p": 8,
        "li": 4,
        "title": 0,
    }
    for chunk in evidence.chunks:
        for sentence in _sentences(chunk.text):
            words = sentence.split()
            if len(words) < 6 or len(sentence) < 35:
                continue
            specificity = len(_distinctive_tokens(sentence))
            score = chunk.score + kind_bonus.get(chunk.kind, 0) + min(specificity * 3, 30)
            if re.search(r"\d", sentence):
                score += 8
            if 55 <= len(sentence) <= 260:
                score += 10
            scored.append((score, sentence[:420]))

    selected: list[str] = []
    fingerprints: list[set[str]] = []
    for _, sentence in sorted(scored, key=lambda item: (-item[0], item[1])):
        fingerprint = set(_distinctive_tokens(sentence))
        if not fingerprint:
            continue
        if any(
            len(fingerprint & prior) / max(1, min(len(fingerprint), len(prior))) > 0.7
            for prior in fingerprints
        ):
            continue
        selected.append(sentence)
        fingerprints.append(fingerprint)
        if len(selected) >= limit:
            break
    return selected


def extract_exact_phrase(text: str, *, max_words: int = 10) -> str:
    matches = list(re.finditer(r"[A-Za-z0-9][A-Za-z0-9'’&/-]*", text))
    words = [match.group(0) for match in matches]
    if not matches:
        return _clean_text(text)[:100]
    best: tuple[int, int, int] | None = None
    window_size = min(max_words, len(words))
    minimum = min(5, window_size)
    for size in range(window_size, minimum - 1, -1):
        for start in range(0, len(words) - size + 1):
            window = words[start : start + size]
            score = sum(
                2 if word.casefold() not in _STOP_WORDS and len(word) > 3 else 0
                for word in window
            )
            score += sum(1 for word in window if word[:1].isupper() or any(c.isdigit() for c in word))
            if best is None or score > best[0]:
                best = (score, start, size)
        if best and best[0] >= size:
            break
    _, start, size = best or (0, 0, window_size)
    return text[matches[start].start() : matches[start + size - 1].end()]


def _generation_instruction(anchor: str, title: str | None) -> str:
    context = f"Page title: {title}\n" if title else ""
    return (
        "Write one natural, standalone question that a person could ask a chatbot. "
        "The question must be answerable from the supplied text, must ask for a specific "
        "fact, and must not mention a page, passage, source, URL, or these instructions. "
        "Return only the question.\n"
        f"{context}Text: {anchor}\nQuestion:"
    )


def _clean_question(value: str) -> str:
    text = _clean_text(str(value or ""))
    text = re.sub(r"^(?:question|query|prompt)\s*:\s*", "", text, flags=re.I)
    text = text.strip(" \"'`")
    if not text:
        return ""
    first = re.split(r"(?<=\?)\s+", text, maxsplit=1)[0]
    if len(first) > 240:
        first = first[:240].rsplit(" ", 1)[0]
    if not first.endswith("?"):
        first = f"{first.rstrip('.!')}?"
    return first


def _question_is_grounded(question: str, anchor: str) -> bool:
    if not question or len(question) < 18 or len(question) > 250:
        return False
    lowered = question.casefold()
    if any(term in lowered for term in ("this page", "the passage", "the source", "the url")):
        return False
    question_tokens = set(_distinctive_tokens(question))
    anchor_tokens = set(_distinctive_tokens(anchor))
    return bool(question_tokens & anchor_tokens)


def _fallback_question(anchor: str, title: str | None) -> str:
    phrase = extract_exact_phrase(anchor, max_words=8)
    if title:
        return f"What does {title[:100]} say about {phrase}?"
    return f"What publicly available information explains {phrase}?"


def _distinctive_tokens(text: str) -> list[str]:
    return [
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9][A-Za-z0-9'’/-]*", text)
        if len(token) >= 4 and token.casefold() not in _STOP_WORDS
    ]


def _sentences(text: str) -> Iterable[str]:
    clean = _clean_text(text)
    pieces = re.split(r"(?<=[.!?])\s+|;\s+", clean)
    return [piece.strip(" -–—") for piece in pieces if piece.strip(" -–—")]


def _select_chunks(parser: "_EvidenceParser") -> list[EvidenceChunk]:
    chunks: list[EvidenceChunk] = []
    if parser.title:
        chunks.append(EvidenceChunk("title", parser.title, 100))
    if parser.description:
        chunks.append(EvidenceChunk("meta_description", parser.description, 95))
    scores = {"h1": 90, "h2": 80, "h3": 70, "p": 50, "li": 35}
    for kind, raw_text in parser.blocks:
        text = _clean_text(raw_text)
        minimum = 12 if kind.startswith("h") else 35
        if len(text) >= minimum:
            chunks.append(EvidenceChunk(kind, text[:900], scores.get(kind, 30)))

    selected: list[EvidenceChunk] = []
    seen: set[str] = set()
    for chunk in sorted(chunks, key=lambda item: item.score, reverse=True):
        key = re.sub(r"\W+", " ", chunk.text).strip().casefold()
        if not key or key in seen:
            continue
        seen.add(key)
        selected.append(chunk)
        if len(selected) >= MAX_CHUNKS:
            break
    return selected


def _plain_text_chunks(content: str) -> list[EvidenceChunk]:
    blocks = [_clean_text(block) for block in re.split(r"\n\s*\n", content)]
    blocks = [block for block in blocks if len(block) >= 25]
    if not blocks and len(_clean_text(content)) >= 40:
        blocks = [_clean_text(content)]
    return [
        EvidenceChunk(
            "title" if index == 0 and len(block) <= 120 else "p",
            block[:900],
            100 if index == 0 and len(block) <= 120 else 50,
        )
        for index, block in enumerate(blocks[:MAX_CHUNKS])
    ]


def _normalise_url(value: str) -> str:
    text = value.strip()
    if not text:
        raise PromptCreatorError("Enter a public page URL or paste page copy.")
    if "://" not in text:
        text = f"https://{text}"
    parsed = urlsplit(text)
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, parsed.path or "/", parsed.query, "")
    )


def _looks_like_html(content: str) -> bool:
    sample = content.lstrip()[:500].casefold()
    return (
        sample.startswith("<!doctype")
        or sample.startswith("<html")
        or "<body" in sample
        or (sample.startswith("<") and ">" in sample[:120])
    )


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _EvidenceParser(HTMLParser):
    _BLOCK_TAGS = {"h1", "h2", "h3", "p", "li"}
    _SKIP_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "template",
        "nav",
        "footer",
        "form",
    }
    _VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.description: str | None = None
        self.blocks: list[tuple[str, str]] = []
        self._capture_tag: str | None = None
        self._capture_depth = 0
        self._buffer: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.casefold()
        attributes = {key.casefold(): value for key, value in attrs}
        if tag == "meta":
            name = (attributes.get("name") or attributes.get("property") or "").casefold()
            if name in {"description", "og:description", "twitter:description"}:
                content = _clean_text(attributes.get("content") or "")
                if content and not self.description:
                    self.description = content
            if name in {"og:title", "twitter:title"} and not self.title:
                content = _clean_text(attributes.get("content") or "")
                if content:
                    self.title = content
        if tag in self._VOID_TAGS:
            return
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if self._capture_tag:
            self._capture_depth += 1
        elif tag == "title" or tag in self._BLOCK_TAGS:
            self._capture_tag = tag
            self._capture_depth = 1
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth or not self._capture_tag:
            return
        self._capture_depth -= 1
        if self._capture_depth > 0:
            return
        text = _clean_text(" ".join(self._buffer))
        if self._capture_tag == "title" and text:
            self.title = text
        elif self._capture_tag in self._BLOCK_TAGS and text:
            self.blocks.append((self._capture_tag, text))
        self._capture_tag = None
        self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._capture_tag and not self._skip_depth:
            self._buffer.append(data)
