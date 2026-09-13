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
const MIN_QUOTE_WORDS = 20;
const MAX_QUOTE_WORDS = 30;
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

export function selectQuotablePassages(evidence, limit = 15) {
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
    for (const passage of quotableSegments(chunk.text)) {
      if (isLikelyBoilerplate(passage, chunk.kind)) continue;
      const tokens = distinctiveTokens(passage);
      if (new Set(tokens).size < 3) continue;
      passages.push({
        chunk,
        passage,
        supportingText: chunk.text.slice(0, 600),
        tokens,
      });
    }
  }

  const documentFrequency = new Map();
  for (const passage of passages) {
    for (const token of new Set(passage.tokens)) {
      documentFrequency.set(token, (documentFrequency.get(token) || 0) + 1);
    }
  }

  const titleTokens = new Set(distinctiveTokens(evidence.title || ""));
  const scored = passages.map(({ chunk, passage, supportingText, tokens }) => {
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
    if (/\d/.test(passage)) score += 8;
    if (specificNameCount(passage) >= 2) score += 8;
    return { score, passage, supportingText };
  });

  const selected = [];
  const fingerprints = [];
  for (const candidate of scored.sort(
    (a, b) => b.score - a.score || a.passage.localeCompare(b.passage),
  )) {
    const fingerprint = new Set(distinctiveTokens(candidate.passage));
    if (fingerprint.size < 3) continue;
    const overlaps = fingerprints.some((prior) => {
      const intersection = [...fingerprint].filter((token) => prior.has(token));
      return intersection.length / Math.max(1, Math.min(fingerprint.size, prior.size)) > 0.7;
    });
    if (overlaps) continue;
    selected.push(candidate);
    fingerprints.push(fingerprint);
    if (selected.length >= limit) break;
  }
  return selected;
}

export function extractQuoteWindow(text) {
  const matches = [...text.matchAll(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g)];
  if (matches.length < MIN_QUOTE_WORDS) return null;
  if (matches.length <= MAX_QUOTE_WORDS) {
    return text.slice(
      matches[0].index,
      matches[matches.length - 1].index + matches[matches.length - 1][0].length,
    );
  }

  const words = matches.map((match) => match[0]);
  let best = null;
  for (let size = MAX_QUOTE_WORDS; size >= MIN_QUOTE_WORDS; size -= 1) {
    for (let start = 0; start <= words.length - size; start += 1) {
      const window = words.slice(start, start + size);
      let score = 0;
      for (const word of window) {
        const lowered = word.toLowerCase();
        if (!STOP_WORDS.has(lowered) && word.length > 3) score += 2;
        if (GENERIC_TOKENS.has(lowered)) score -= 3;
        if (/^[A-Z]/.test(word) || /\d/.test(word)) score += 1;
      }
      const before = start === 0 ? "" : text.slice(0, matches[start].index).trimEnd();
      const endMatch = matches[start + size - 1];
      const after = text.slice(endMatch.index + endMatch[0].length).trimStart();
      if (!before || /[.!?]["')\]]?$/.test(before)) score += 12;
      if (!after || /^[.!?]["')\]]?/.test(after)) score += 12;
      if (!best || score > best[0]) best = [score, start, size];
    }
  }
  const start = best?.[1] ?? 0;
  const size = best?.[2] ?? MAX_QUOTE_WORDS;
  return text.slice(
    matches[start].index,
    matches[start + size - 1].index + matches[start + size - 1][0].length,
  );
}

export function buildPassageSelectionInstruction(candidates, title, count) {
  return `Select the ${count} most meaningful, page-specific quotations below.
Prefer concrete facts, distinctive names, numbers, products, places, or claims that
are likely to identify this exact page. Reject navigation, calls to action, generic
marketing language, cookie text, and ambiguous statements. Do not rewrite any text.
Return JSON only in the form {"ids":[0,1]} ordered best first.

Page title: ${title || "Unknown"}
Candidates:
${JSON.stringify(candidates.map((item, id) => ({ id, text: item.passage })))}`;
}

export function parsePassageSelection(value, candidateCount) {
  let text = String(value || "").trim();
  text = text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  let ids = [];
  try {
    const parsed = JSON.parse(text);
    ids = Array.isArray(parsed) ? parsed : parsed?.ids;
  } catch {
    const match = text.match(/\[[\d,\s]+\]/);
    if (match) ids = JSON.parse(match[0]);
  }
  if (!Array.isArray(ids)) return [];
  return [...new Set(ids)]
    .map(Number)
    .filter((id) => Number.isInteger(id) && id >= 0 && id < candidateCount);
}

export function buildPromptCandidate(candidate, method) {
  return {
    prompt: `"${candidate.passage}" please retrieve a web page with this exact text`,
    passage: candidate.passage,
    supportingText: candidate.supportingText,
    generationMethod: method,
  };
}

export function promptListText(prompts) {
  return prompts.map((item) => item.prompt).join("\n\n");
}

export function chatbotLinks(prompt) {
  const encoded = encodeURIComponent(prompt);
  return [
    {
      id: "chatgpt",
      name: "Open in ChatGPT",
      url: `https://chatgpt.com/?q=${encoded}`,
    },
    {
      id: "claude",
      name: "Open in Claude",
      url: `https://claude.ai/new?q=${encoded}`,
    },
    {
      id: "gemini",
      name: "Open in Gemini",
      url: `https://gemini.google.com/guided-learning?query=${encoded}`,
    },
  ];
}

export async function generatePrompts(evidence, options) {
  const count = Math.max(3, Math.min(Number(options.count || 5), 8));
  const pool = selectQuotablePassages(evidence, Math.max(12, count * 3));
  if (!pool.length) {
    throw new Error("There was not enough specific page copy to create prompts.");
  }

  const session = options.session || null;
  const onProgress = options.onProgress || null;
  let selectedIds = [];
  if (session && options.rankPassages) {
    try {
      onProgress?.({ stage: "selecting", index: 0, total: 1 });
      const raw = await options.rankPassages(
        session,
        buildPassageSelectionInstruction(pool, evidence.title, count),
      );
      selectedIds = parsePassageSelection(raw, pool.length).slice(0, count);
    } catch {
      selectedIds = [];
    }
  }
  const orderedIds = [
    ...selectedIds,
    ...pool.map((_, index) => index).filter((index) => !selectedIds.includes(index)),
  ].slice(0, count);
  const modelSelected = new Set(selectedIds);
  return orderedIds.map((id) =>
    buildPromptCandidate(
      pool[id],
      modelSelected.has(id) ? "chrome_ai_selection" : "heuristic_selection",
    ),
  );
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

function quotableSegments(text) {
  const parts = sentences(text);
  const passages = [];
  const seen = new Set();
  for (let start = 0; start < parts.length; start += 1) {
    let combined = "";
    for (let end = start; end < parts.length; end += 1) {
      combined = cleanText(`${combined} ${parts[end]}`);
      const wordCount = (
        combined.match(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g) || []
      ).length;
      if (wordCount < MIN_QUOTE_WORDS) continue;
      const passage = extractQuoteWindow(combined);
      if (passage && !seen.has(passage)) {
        seen.add(passage);
        passages.push(passage);
      }
      break;
    }
  }
  return passages;
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
