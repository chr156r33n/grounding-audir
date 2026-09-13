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

const MAX_CHUNKS = 40;
const BOILERPLATE_PATTERN =
  /\b(?:accept (?:all )?cookies?|cookie (?:policy|settings?)|privacy policy|terms (?:and|&) conditions|sign (?:in|up)|log in|register|subscribe|newsletter|skip to content|read more|learn more|view all|see all|contact us|follow us|share (?:this|on)|add to (?:cart|basket)|open menu|close menu|search|home|back to top|all rights reserved)\b/i;
const GENERIC_TOKENS = new Set([
  "account",
  "basket",
  "blog",
  "contact",
  "cookie",
  "copyright",
  "explore",
  "follow",
  "help",
  "home",
  "learn",
  "login",
  "menu",
  "more",
  "newsletter",
  "privacy",
  "read",
  "register",
  "search",
  "share",
  "shop",
  "signin",
  "signup",
  "social",
  "subscribe",
  "terms",
]);

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
  const passages = [];
  for (const chunk of evidence.chunks) {
    for (const sentence of sentences(chunk.text)) {
      const words = sentence.split(/\s+/);
      if (
        words.length < 6 ||
        sentence.length < 35 ||
        isLikelyBoilerplate(sentence, chunk.kind)
      ) {
        continue;
      }
      const tokens = distinctiveTokens(sentence);
      if (new Set(tokens).size < 3) continue;
      passages.push({ chunk, sentence: sentence.slice(0, 420), tokens });
    }
  }

  const documentFrequency = new Map();
  for (const passage of passages) {
    for (const token of new Set(passage.tokens)) {
      documentFrequency.set(token, (documentFrequency.get(token) || 0) + 1);
    }
  }

  const titleTokens = new Set(distinctiveTokens(evidence.title || ""));
  const scored = passages.map(({ chunk, sentence, tokens }) => {
    const uniqueTokens = new Set(tokens);
    const rarity = [...uniqueTokens].reduce(
      (total, token) => total + 1 / (documentFrequency.get(token) || 1),
      0,
    );
    const genericCount = [...uniqueTokens].filter((token) =>
      GENERIC_TOKENS.has(token),
    ).length;
    const titleOverlap = [...uniqueTokens].filter((token) =>
      titleTokens.has(token),
    ).length;
    let score =
      chunk.score +
      (kindBonus[chunk.kind] || 0) +
      Math.min(rarity * 5, 35) +
      Math.min(titleOverlap * 4, 12) -
      genericCount * 5;
    if (/\d/.test(sentence)) score += 8;
    if (specificNameCount(sentence) >= 2) score += 8;
    if (sentence.length >= 55 && sentence.length <= 260) score += 10;
    return [score, sentence];
  });

  const selected = [];
  const fingerprints = [];
  for (const [, sentence] of scored.sort((a, b) => b[0] - a[0] || a[1].localeCompare(b[1]))) {
    const fingerprint = new Set(distinctiveTokens(sentence));
    if (fingerprint.size < 3) continue;
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
        const lowered = word.toLowerCase();
        if (!STOP_WORDS.has(lowered) && word.length > 3) score += 2;
        if (GENERIC_TOKENS.has(lowered)) score -= 3;
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
    "fact that is distinctive to this page, and must not ask about generic navigation, " +
    "site features, cookies, or calls to action. Do not mention a page, passage, source, " +
    "URL, or these instructions. " +
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
  if (
    ["this page", "the page", "the passage", "the source", "the url"].some((term) =>
      lowered.includes(term),
    )
  ) {
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
  if (typeof DOMParser !== "undefined") {
    return parseHtmlWithDom(value);
  }

  const withoutNoise = stripHtmlBoilerplate(value);
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
  const blocks = [];
  for (const section of content.split(/\n\s*\n/)) {
    const lines = section.split(/\n/).map(cleanText).filter(Boolean);
    if (lines.length <= 1) {
      if (lines[0]) blocks.push(lines[0]);
      continue;
    }
    let buffer = "";
    for (const line of lines) {
      if (!buffer && line.length < 25) continue;
      buffer = cleanText(`${buffer} ${line}`);
      if (/[.!?]$/.test(line) || buffer.length >= 300) {
        blocks.push(buffer);
        buffer = "";
      }
    }
    if (buffer.length >= 25) blocks.push(buffer);
  }
  const filtered = blocks.filter(
    (block) =>
      block.length >= 25 &&
      !isLikelyBoilerplate(block, block.length <= 120 ? "title" : "p"),
  );
  if (!filtered.length && cleanText(content).length >= 40) {
    filtered.push(cleanText(content));
  }
  return filtered.slice(0, MAX_CHUNKS).map((block, index) => ({
    kind: index === 0 && block.length <= 120 ? "title" : "p",
    text: block.slice(0, 900),
    score: index === 0 && block.length <= 120 ? 100 : 50,
  }));
}

function parseHtmlWithDom(value) {
  const document = new DOMParser().parseFromString(value, "text/html");
  document
    .querySelectorAll(
      [
        "script",
        "style",
        "noscript",
        "svg",
        "nav",
        "footer",
        "form",
        "header",
        "aside",
        "dialog",
        "[hidden]",
        '[aria-hidden="true"]',
        '[role="navigation"]',
        '[role="banner"]',
        '[role="contentinfo"]',
        '[role="dialog"]',
        '[class*="breadcrumb" i]',
        '[class*="cookie" i]',
        '[class*="consent" i]',
        '[class*="footer" i]',
        '[class*="header" i]',
        '[class*="menu" i]',
        '[class*="modal" i]',
        '[class*="nav-" i]',
        '[class*="navigation" i]',
        '[class*="newsletter" i]',
        '[class*="sidebar" i]',
        '[class*="social" i]',
        '[id*="breadcrumb" i]',
        '[id*="cookie" i]',
        '[id*="consent" i]',
        '[id*="footer" i]',
        '[id*="menu" i]',
        '[id*="navigation" i]',
      ].join(","),
    )
    .forEach((element) => element.remove());

  const cleanNode = (element) => cleanText(element?.textContent || "");
  const title = cleanNode(document.querySelector("title")) || null;
  const description =
    document.querySelector(
      'meta[name="description" i], meta[property="og:description" i]',
    )?.getAttribute("content")?.trim() || null;
  const main =
    document.querySelector("main, article, [role=main]") ||
    document.body ||
    document.documentElement;
  const chunks = [];
  if (title) chunks.push({ kind: "title", text: title.slice(0, 900), score: 100 });
  if (description && !isLikelyBoilerplate(description, "meta_description")) {
    chunks.push({
      kind: "meta_description",
      text: description.slice(0, 900),
      score: 95,
    });
  }
  main.querySelectorAll("h1, h2, h3, p, li").forEach((element) => {
    const kind = element.tagName.toLowerCase();
    const text = cleanNode(element);
    const minimum = kind.startsWith("h") ? 12 : 40;
    if (text.length < minimum || isLikelyBoilerplate(text, kind)) return;
    const score =
      kind === "h1" ? 85 : kind === "h2" ? 75 : kind === "h3" ? 65 : kind === "li" ? 35 : 40;
    chunks.push({ kind, text: text.slice(0, 900), score });
  });
  return {
    title,
    description,
    chunks: dedupeChunks(chunks).slice(0, MAX_CHUNKS),
  };
}

function stripHtmlBoilerplate(value) {
  let stripped = value.replace(
    /<(script|style|noscript|svg|nav|footer|form|header|aside|dialog)\b[\s\S]*?<\/\1>/gi,
    " ",
  );
  const noisyContainer =
    /<(div|section|ul)\b[^>]*(?:class|id)=["'][^"']*(?:breadcrumb|cookie|consent|footer|menu|modal|nav(?:igation)?|newsletter|sidebar|social)[^"']*["'][^>]*>[\s\S]*?<\/\1>/gi;
  for (let pass = 0; pass < 3; pass += 1) {
    stripped = stripped.replace(noisyContainer, " ");
  }
  return stripped;
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

function isLikelyBoilerplate(text, kind = "p") {
  const cleaned = cleanText(text);
  const words = cleaned.match(/[A-Za-z0-9][A-Za-z0-9'’/-]*/g) || [];
  if (!words.length) return true;
  const loweredWords = words.map((word) => word.toLowerCase());
  const genericCount = loweredWords.filter((word) => GENERIC_TOKENS.has(word)).length;
  const distinctiveCount = new Set(distinctiveTokens(cleaned)).size;

  if (BOILERPLATE_PATTERN.test(cleaned) && words.length <= 28) return true;
  if ((cleaned.match(/[|›»]/g) || []).length >= 3) return true;
  if (genericCount / words.length >= 0.35) return true;
  if (kind === "li" && words.length <= 8 && distinctiveCount < 3) return true;
  if (
    /^(?:welcome|discover|explore|find out|click here|get started|we use cookies)\b/i.test(
      cleaned,
    ) &&
    distinctiveCount < 5
  ) {
    return true;
  }
  return false;
}

function specificNameCount(text) {
  const words = text.match(/\b[A-Z][A-Za-z0-9'’&/-]{2,}\b/g) || [];
  return words.slice(1).filter((word) => !STOP_WORDS.has(word.toLowerCase())).length;
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
