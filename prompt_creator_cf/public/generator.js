const STOP_WORDS = new Set([
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
]);

const MAX_CHUNKS = 12;

export function evidenceFromContent(content, source = "") {
  const text = String(content || "").trim();
  if (!text) {
    throw new Error("Paste page HTML or visible page copy.");
  }
  if (looksLikeHtml(text)) {
    const parsed = parseHtmlEvidence(text);
    if (!parsed.chunks.length) {
      throw new Error("No useful title, headings, description, or body copy was found.");
    }
    return {
      source: source.trim() || "pasted-content",
      title: parsed.title,
      description: parsed.description,
      chunks: parsed.chunks,
      contentType: "text/html",
      downloadedBytes: text.length,
      inputMethod: "paste",
    };
  }
  const chunks = plainTextChunks(text);
  if (!chunks.length) {
    throw new Error("The pasted copy is too short. Paste several sentences from the page.");
  }
  return {
    source: source.trim() || "pasted-content",
    title: chunks[0].kind === "title" ? chunks[0].text : null,
    description: chunks[0]?.text.slice(0, 240) || null,
    chunks,
    contentType: "text/plain",
    downloadedBytes: text.length,
    inputMethod: "paste",
  };
}

export function selectAnchorPassages(evidence, limit = 6) {
  const kindBonus = {
    meta_description: 35,
    h1: 30,
    h2: 22,
    h3: 14,
    p: 8,
    li: 4,
    title: 0,
  };
  const scored = [];
  for (const chunk of evidence.chunks) {
    for (const sentence of sentences(chunk.text)) {
      const words = sentence.split(/\s+/);
      if (words.length < 6 || sentence.length < 35) continue;
      const specificity = distinctiveTokens(sentence).length;
      let score = chunk.score + (kindBonus[chunk.kind] || 0) + Math.min(specificity * 3, 30);
      if (/\d/.test(sentence)) score += 8;
      if (sentence.length >= 55 && sentence.length <= 260) score += 10;
      scored.push([score, sentence.slice(0, 420)]);
    }
  }

  const selected = [];
  const fingerprints = [];
  for (const [, sentence] of scored.sort((a, b) => b[0] - a[0] || a[1].localeCompare(b[1]))) {
    const fingerprint = new Set(distinctiveTokens(sentence));
    if (!fingerprint.size) continue;
    const overlaps = fingerprints.some((prior) => {
      const intersection = [...fingerprint].filter((token) => prior.has(token));
      return intersection.length / Math.max(1, Math.min(fingerprint.size, prior.size)) > 0.7;
    });
    if (overlaps) continue;
    selected.push(sentence);
    fingerprints.push(fingerprint);
    if (selected.length >= limit) break;
  }
  return selected;
}

export function extractExactPhrase(text, maxWords = 10) {
  const matches = [...text.matchAll(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g)];
  if (!matches.length) return cleanText(text).slice(0, 100);

  const words = matches.map((match) => match[0]);
  let best = null;
  const windowSize = Math.min(maxWords, words.length);
  const minimum = Math.min(5, windowSize);
  for (let size = windowSize; size >= minimum; size -= 1) {
    for (let start = 0; start <= words.length - size; start += 1) {
      const window = words.slice(start, start + size);
      let score = 0;
      for (const word of window) {
        if (!STOP_WORDS.has(word.toLowerCase()) && word.length > 3) score += 2;
        if (/^[A-Z]/.test(word) || /\d/.test(word)) score += 1;
      }
      if (!best || score > best[0]) best = [score, start, size];
    }
    if (best && best[0] >= size) break;
  }
  const start = best?.[1] ?? 0;
  const size = best?.[2] ?? windowSize;
  return text.slice(matches[start].index, matches[start + size - 1].index + matches[start + size - 1][0].length);
}

export function buildGenerationInstruction(anchor, title) {
  const context = title ? `Page title: ${title}\n` : "";
  return (
    "Write one natural, standalone question that a person could ask a chatbot. " +
    "The question must be answerable from the supplied text, must ask for a specific " +
    "fact, and must not mention a page, passage, source, URL, or these instructions. " +
    "Return only the question.\n" +
    `${context}Text: ${anchor}\nQuestion:`
  );
}

export function cleanQuestion(value) {
  let text = cleanText(String(value || ""));
  text = text.replace(/^(?:question|query|prompt)\s*:\s*/i, "").trim();
  text = text.replace(/^["'`]+|["'`]+$/g, "");
  if (!text) return "";
  const first = text.split(/(?<=\?)\s+/)[0];
  const trimmed = first.length > 240 ? first.slice(0, 240).replace(/\s+\S*$/, "") : first;
  return trimmed.endsWith("?") ? trimmed : `${trimmed.replace(/[.!]+$/, "")}?`;
}

export function questionIsGrounded(question, anchor) {
  if (!question || question.length < 18 || question.length > 250) return false;
  const lowered = question.toLowerCase();
  if (["this page", "the passage", "the source", "the url"].some((term) => lowered.includes(term))) {
    return false;
  }
  const questionTokens = new Set(distinctiveTokens(question));
  const anchorTokens = new Set(distinctiveTokens(anchor));
  return [...questionTokens].some((token) => anchorTokens.has(token));
}

export function fallbackQuestion(anchor, title) {
  const phrase = extractExactPhrase(anchor, 8);
  if (title) return `What does ${title.slice(0, 100)} say about ${phrase}?`;
  return `What publicly available information explains ${phrase}?`;
}

export function buildPromptCandidate(anchor, question, method, exactMatch) {
  const phrase = extractExactPhrase(anchor);
  const prompt = exactMatch
    ? `${question} Base your answer on content containing the exact phrase "${phrase}".`
    : question;
  return {
    prompt,
    exactPhrase: phrase,
    sourceExcerpt: anchor,
    generationMethod: method,
  };
}

export async function generatePrompts(evidence, options) {
  const count = Math.max(3, Math.min(Number(options.count || 5), 8));
  const exactMatch = options.exactMatch !== false;
  const anchors = selectAnchorPassages(evidence, count);
  if (!anchors.length) {
    throw new Error("There was not enough specific page copy to create prompts.");
  }

  const candidates = [];
  const seen = new Set();
  const session = options.session || null;
  const onProgress = options.onProgress || null;

  for (let index = 0; index < anchors.length; index += 1) {
    const anchor = anchors[index];
    onProgress?.({ stage: "generating", index, total: anchors.length });

    let question = "";
    let method = "template";
    if (session) {
      try {
        const raw = await options.generateQuestion(session, buildGenerationInstruction(anchor, evidence.title));
        question = cleanQuestion(raw);
        if (questionIsGrounded(question, anchor)) {
          method = "chrome_ai";
        }
      } catch {
        question = "";
      }
    }
    if (!question || !questionIsGrounded(question, anchor)) {
      question = fallbackQuestion(anchor, evidence.title);
      method = session ? "template_fallback" : "template";
    }

    const candidate = buildPromptCandidate(anchor, question, method, exactMatch);
    const key = candidate.prompt.replace(/\W+/g, " ").trim().toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    candidates.push(candidate);
    if (candidates.length >= count) break;
  }
  return candidates;
}

function parseHtmlEvidence(value) {
  const withoutNoise = value.replace(
    /<(script|style|noscript|svg|nav|footer|form|header|aside)\b[\s\S]*?<\/\1>/gi,
    " ",
  );
  const first = (pattern) => cleanText(decode(withoutNoise.match(pattern)?.[1] || "")) || null;
  const all = (pattern) =>
    [...withoutNoise.matchAll(pattern)]
      .map((match) => cleanText(decode(match[1])))
      .filter(Boolean);
  const title = first(/<title\b[^>]*>([\s\S]*?)<\/title>/i);
  const description =
    first(/<meta\b[^>]*(?:name|property)=["'](?:description|og:description)["'][^>]*content=["']([^"']+)["'][^>]*>/i) ||
    first(/<meta\b[^>]*content=["']([^"']+)["'][^>]*(?:name|property)=["'](?:description|og:description)["'][^>]*>/i);
  const headings = [...withoutNoise.matchAll(/<(h[1-3])\b[^>]*>([\s\S]*?)<\/\1>/gi)]
    .map((match) => ({ kind: match[1].toLowerCase(), text: cleanText(decode(match[2])) }))
    .filter((item) => item.text.length > 0)
    .slice(0, 8);
  const paragraphs = all(/<(?:p|li)\b[^>]*>([\s\S]*?)<\/(?:p|li)>/gi)
    .filter((text) => text.length >= 40)
    .slice(0, 10);

  const chunks = [];
  if (title) chunks.push({ kind: "title", text: title.slice(0, 900), score: 100 });
  if (description) chunks.push({ kind: "meta_description", text: description.slice(0, 900), score: 95 });
  for (const heading of headings) {
    const score = heading.kind === "h1" ? 85 : heading.kind === "h2" ? 75 : 65;
    chunks.push({ kind: heading.kind, text: heading.text.slice(0, 900), score });
  }
  for (const paragraph of paragraphs) {
    chunks.push({ kind: "p", text: paragraph.slice(0, 900), score: 40 });
  }
  return { title, description, chunks: dedupeChunks(chunks).slice(0, MAX_CHUNKS) };
}

function plainTextChunks(content) {
  const blocks = content
    .split(/\n\s*\n/)
    .map(cleanText)
    .filter((block) => block.length >= 25);
  if (!blocks.length && cleanText(content).length >= 40) {
    blocks.push(cleanText(content));
  }
  return blocks.slice(0, MAX_CHUNKS).map((block, index) => ({
    kind: index === 0 && block.length <= 120 ? "title" : "p",
    text: block.slice(0, 900),
    score: index === 0 && block.length <= 120 ? 100 : 50,
  }));
}

function dedupeChunks(chunks) {
  const selected = [];
  const seen = new Set();
  for (const chunk of chunks.sort((a, b) => b.score - a.score)) {
    const key = chunk.text.replace(/\W+/g, " ").trim().toLowerCase();
    if (!key || seen.has(key)) continue;
    seen.add(key);
    selected.push(chunk);
  }
  return selected;
}

function distinctiveTokens(text) {
  return [...text.matchAll(/[A-Za-z0-9][A-Za-z0-9'’/-]*/g)]
    .map((match) => match[0].toLowerCase())
    .filter((token) => token.length >= 4 && !STOP_WORDS.has(token));
}

function sentences(text) {
  return cleanText(text)
    .split(/(?<=[.!?])\s+|;\s+/)
    .map((piece) => piece.trim().replace(/^[-–—\s]+|[-–—\s]+$/g, ""))
    .filter(Boolean);
}

function looksLikeHtml(content) {
  const sample = content.trim().slice(0, 500).toLowerCase();
  return (
    sample.startsWith("<!doctype") ||
    sample.startsWith("<html") ||
    sample.includes("<body") ||
    (sample.startsWith("<") && sample.includes(">"))
  );
}

function cleanText(value) {
  return value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function decode(value) {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}
