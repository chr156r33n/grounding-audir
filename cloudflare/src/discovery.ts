const MIN_WORDS = 20;
const MAX_WORDS = 30;
const WORD_PATTERN = /[A-Za-z0-9][A-Za-z0-9'’&/-]*/g;
const STOP_WORDS = new Set([
  "about", "after", "also", "and", "are", "because", "been", "before", "being",
  "between", "both", "but", "can", "does", "for", "from", "has", "have", "into",
  "more", "most", "not", "only", "other", "over", "page", "say", "says", "than",
  "that", "the", "their", "there", "these", "they", "this", "through", "under",
  "using", "was", "were", "what", "when", "where", "which", "while", "who",
  "will", "with", "would", "you", "your",
]);
const GENERIC = new Set([
  "account", "basket", "blog", "contact", "cookie", "copyright", "explore",
  "follow", "help", "home", "learn", "login", "menu", "newsletter", "privacy",
  "read", "register", "search", "share", "shop", "signin", "signup", "social",
  "subscribe", "terms",
]);
const BOILERPLATE =
  /\b(?:accept (?:all )?cookies?|cookie (?:policy|settings?)|privacy policy|terms (?:and|&) conditions|sign (?:in|up)|log in|register|subscribe|newsletter|skip to content|read more|learn more|view all|contact us|follow us|share (?:this|on)|add to (?:cart|basket)|open menu|close menu|back to top|all rights reserved)\b/i;

export interface DiscoveryRequest {
  url?: string;
  content?: string;
  count?: number;
  debug?: boolean;
}

interface PageChunk {
  kind: string;
  text: string;
  score: number;
}

interface PageEvidence {
  url: string | null;
  title: string | null;
  description: string | null;
  language: string | null;
  domChunks: PageChunk[];
}

interface SnippetCandidate {
  query: string;
  rationale: string;
  evidence: string;
  generators: string[];
}

interface RankedPassage {
  passage: string;
  chunk: PageChunk;
  tokens: string[];
  rank?: number;
}

export async function discoverQueries(input: DiscoveryRequest) {
  const count = Math.max(3, Math.min(Number(input.count || 6), 10));
  const pasted = input.content?.trim() || "";
  const source = pasted || (input.url ? await fetchPublicPage(input.url) : "");
  if (source.length < 40) {
    throw new Error("Paste page text/HTML or enter a public URL with enough page content.");
  }

  const evidence = extractEvidence(source, input.url || null);
  const candidates = selectPageSnippets(evidence, count);
  return {
    source: pasted ? "paste" : "url",
    url: input.url || null,
    keyTerms: [],
    candidates: candidates.map((item) => ({
      query: item.query,
      rationale: item.rationale,
      evidence: item.evidence,
      generator: item.generators.join(", "),
    })),
    generators: [],
    evidence: publicEvidence(evidence),
    error: candidates.length
      ? undefined
      : "This page did not contain enough specific 20–30 word passages. Paste more visible page copy and try again.",
  };
}

export function selectPageSnippets(
  evidence: PageEvidence,
  limit = 6,
): SnippetCandidate[] {
  const kindBonus: Record<string, number> = {
    meta_description: 35,
    h1: 30,
    h2: 22,
    h3: 14,
    p: 8,
    li: 4,
  };
  const raw: RankedPassage[] = [];
  for (const chunk of evidence.domChunks) {
    for (const passage of quotableSegments(chunk.text)) {
      if (isBoilerplate(passage, chunk.kind)) continue;
      const tokens = distinctiveTokens(passage);
      if (new Set(tokens).size < 3) continue;
      raw.push({ passage, chunk, tokens });
    }
  }

  const frequency = new Map<string, number>();
  for (const item of raw) {
    for (const token of new Set(item.tokens)) {
      frequency.set(token, (frequency.get(token) || 0) + 1);
    }
  }
  const titleTokens = new Set(distinctiveTokens(evidence.title || ""));
  const ranked = raw
    .map((item) => {
      const tokens = new Set(item.tokens);
      const rarity = [...tokens].reduce(
        (sum, token) => sum + 1 / (frequency.get(token) || 1),
        0,
      );
      const titleOverlap = [...tokens].filter((token) => titleTokens.has(token)).length;
      const genericCount = [...tokens].filter((token) => GENERIC.has(token)).length;
      let rank =
        item.chunk.score +
        (kindBonus[item.chunk.kind] || 0) +
        Math.min(rarity * 5, 35) +
        Math.min(titleOverlap * 4, 12) -
        genericCount * 5;
      if (/\d/.test(item.passage)) rank += 8;
      if (specificNameCount(item.passage) >= 2) rank += 8;
      return { ...item, rank };
    })
    .sort((a, b) => (b.rank || 0) - (a.rank || 0) || a.passage.localeCompare(b.passage));

  const selected: SnippetCandidate[] = [];
  const fingerprints: Set<string>[] = [];
  for (const item of ranked) {
    const fingerprint = new Set(item.tokens);
    const duplicate = fingerprints.some((prior) => {
      const overlap = [...fingerprint].filter((token) => prior.has(token)).length;
      return overlap / Math.max(1, Math.min(fingerprint.size, prior.size)) > 0.7;
    });
    if (duplicate) continue;
    selected.push({
      query: item.passage,
      rationale: `Exact ${words(item.passage).length}-word page snippet.`,
      evidence: item.chunk.text.slice(0, 600),
      generators: ["page_snippet"],
    });
    fingerprints.push(fingerprint);
    if (selected.length >= limit) break;
  }
  return selected;
}

export function extractSnippetWindow(text: string) {
  const matches = [...text.matchAll(WORD_PATTERN)];
  if (matches.length < MIN_WORDS) return null;
  if (matches.length <= MAX_WORDS) {
    const last = matches.at(-1)!;
    return text.slice(matches[0].index, last.index! + last[0].length);
  }

  let best: { score: number; start: number; size: number } | null = null;
  for (let size = MAX_WORDS; size >= MIN_WORDS; size -= 1) {
    for (let start = 0; start <= matches.length - size; start += 1) {
      let score = 0;
      for (const match of matches.slice(start, start + size)) {
        const word = match[0];
        const lower = word.toLowerCase();
        if (!STOP_WORDS.has(lower) && word.length > 3) score += 2;
        if (GENERIC.has(lower)) score -= 3;
        if (/^[A-Z]/.test(word) || /\d/.test(word)) score += 1;
      }
      const first = matches[start];
      const last = matches[start + size - 1];
      const before = text.slice(0, first.index).trimEnd();
      const after = text.slice(last.index! + last[0].length).trimStart();
      if (!before || /[.!?]["')\]]?$/.test(before)) score += 12;
      if (!after || /^[.!?]["')\]]?/.test(after)) score += 12;
      if (!best || score > best.score) best = { score, start, size };
    }
  }
  if (!best) return null;
  const first = matches[best.start];
  const last = matches[best.start + best.size - 1];
  return text.slice(first.index, last.index! + last[0].length);
}

function quotableSegments(text: string) {
  const parts = clean(text).split(/(?<=[.!?])\s+|;\s+/).filter(Boolean);
  const passages: string[] = [];
  for (let start = 0; start < parts.length; start += 1) {
    let combined = "";
    for (let end = start; end < parts.length; end += 1) {
      combined = clean(`${combined} ${parts[end]}`);
      if (words(combined).length < MIN_WORDS) continue;
      const passage = extractSnippetWindow(combined);
      if (passage && !passages.includes(passage)) passages.push(passage);
      break;
    }
  }
  return passages;
}

function isBoilerplate(text: string, kind: string) {
  const found = words(text);
  const genericCount = found.filter((word) => GENERIC.has(word.toLowerCase())).length;
  if (BOILERPLATE.test(text) && found.length <= 28) return true;
  if ((text.match(/[|›»]/g) || []).length >= 3) return true;
  if (genericCount / Math.max(1, found.length) >= 0.35) return true;
  return kind === "li" && found.length <= 8;
}

function words(text: string) {
  return text.match(WORD_PATTERN) || [];
}

function distinctiveTokens(text: string) {
  return words(text)
    .map((word) => word.toLowerCase())
    .filter((word) => word.length >= 4 && !STOP_WORDS.has(word));
}

function specificNameCount(text: string) {
  const names = text.match(/\b[A-Z][A-Za-z0-9'’&/-]{2,}\b/g) || [];
  return names.slice(1).filter((word) => !STOP_WORDS.has(word.toLowerCase())).length;
}

async function fetchPublicPage(value: string) {
  let url: URL;
  try {
    url = new URL(value.includes("://") ? value : `https://${value}`);
  } catch {
    throw new Error("Enter a valid public HTTP(S) URL.");
  }
  validateUrl(url);
  for (let redirect = 0; redirect <= 5; redirect += 1) {
    const response = await fetch(url, {
      headers: {
        "user-agent":
          "Mozilla/5.0 (compatible; GroundingSourceObservatory/1.0; +https://github.com/chr156r33n/grounding-audir)",
        accept: "text/html,application/xhtml+xml",
      },
      redirect: "manual",
    });
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get("location");
      if (!location) throw new Error("The page returned a redirect without a destination.");
      url = new URL(location, url);
      validateUrl(url);
      continue;
    }
    if (!response.ok) throw new Error(`Page fetch failed with HTTP ${response.status}.`);
    const type = response.headers.get("content-type") || "";
    if (!type.includes("text/html")) throw new Error("The URL did not return HTML.");
    const text = await response.text();
    if (text.length > 1_500_000) throw new Error("The page exceeds the 1.5 MB limit.");
    return text;
  }
  throw new Error("The page exceeded the five-redirect limit.");
}

function validateUrl(url: URL) {
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Only HTTP(S) URLs are allowed.");
  const host = url.hostname.toLowerCase();
  if (
    host === "localhost" ||
    host.endsWith(".local") ||
    /^127\./.test(host) ||
    /^10\./.test(host) ||
    /^192\.168\./.test(host) ||
    /^169\.254\./.test(host) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(host) ||
    host === "::1"
  ) {
    throw new Error("Private and local URLs are not allowed.");
  }
}

function extractEvidence(value: string, url: string | null): PageEvidence {
  const isHtml = /<(html|body|main|title|h1|h2|p)\b/i.test(value);
  if (!isHtml) {
    const paragraphs = value.split(/\n\s*\n/).map(clean).filter((text) => text.length > 20);
    const domChunks = paragraphs.slice(0, 10).map((text, index) => ({
      kind: index === 0 && text.length <= 140 ? "title" : "p",
      text: text.slice(0, 900),
      score: index === 0 ? 100 : 50,
    }));
    return {
      url,
      title: paragraphs[0]?.length <= 140 ? paragraphs[0] : null,
      description: paragraphs[1]?.slice(0, 280) || null,
      language: null,
      domChunks,
    };
  }

  const withoutNoise = value.replace(
    /<(script|style|noscript|svg|nav|footer|form|header|aside)\b[\s\S]*?<\/\1>/gi,
    " ",
  );
  const first = (pattern: RegExp) => clean(decode(withoutNoise.match(pattern)?.[1] || "")) || null;
  const all = (pattern: RegExp) =>
    [...withoutNoise.matchAll(pattern)].map((match) => clean(decode(match[1]))).filter(Boolean);
  const language = withoutNoise.match(/<html\b[^>]*\blang=["']([^"']+)["']/i)?.[1] || null;
  const title = first(/<title\b[^>]*>([\s\S]*?)<\/title>/i);
  const description =
    first(/<meta\b[^>]*(?:name|property)=["'](?:description|og:description)["'][^>]*content=["']([^"']+)["'][^>]*>/i) ||
    first(/<meta\b[^>]*content=["']([^"']+)["'][^>]*(?:name|property)=["'](?:description|og:description)["'][^>]*>/i);
  const headings = [...withoutNoise.matchAll(/<(h[1-3])\b[^>]*>([\s\S]*?)<\/\1>/gi)]
    .map((match) => ({ kind: match[1].toLowerCase(), text: clean(decode(match[2])) }))
    .filter((item) => item.text.length > 0)
    .slice(0, 8);
  const paragraphs = all(/<(?:p|li)\b[^>]*>([\s\S]*?)<\/(?:p|li)>/gi)
    .filter((text) => text.length >= 40)
    .slice(0, 10);

  const domChunks: PageChunk[] = [];
  if (title) domChunks.push({ kind: "title", text: title.slice(0, 900), score: 100 });
  if (description) domChunks.push({ kind: "meta_description", text: description.slice(0, 900), score: 95 });
  for (const heading of headings) {
    domChunks.push({
      kind: heading.kind,
      text: heading.text.slice(0, 900),
      score: heading.kind === "h1" ? 85 : heading.kind === "h2" ? 75 : 65,
    });
  }
  for (const paragraph of paragraphs) {
    domChunks.push({ kind: "p", text: paragraph.slice(0, 900), score: 40 });
  }
  return { url, title, description, language, domChunks };
}

function publicEvidence(evidence: PageEvidence) {
  return {
    title: evidence.title,
    description: evidence.description,
    language: evidence.language,
    chunkCount: evidence.domChunks.length,
  };
}

function clean(value: string) {
  return value.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim();
}

function decode(value: string) {
  return value
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'");
}
