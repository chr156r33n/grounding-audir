import type { Env } from "./types.ts";

const STOP_WORDS = new Set([
  "and", "are", "for", "from", "have", "into", "that", "the", "their", "this",
  "with", "your", "you", "our", "was", "were", "will", "www", "https", "http",
]);

export interface DiscoveryRequest {
  url?: string;
  content?: string;
  count?: number;
}

export async function discoverQueries(input: DiscoveryRequest, _env: Env) {
  const count = Math.max(3, Math.min(Number(input.count || 6), 10));
  const source = input.content?.trim() || (input.url ? await fetchPublicPage(input.url) : "");
  if (source.length < 40) {
    throw new Error("Paste page text/HTML or enter a public URL with enough page content.");
  }
  const evidence = extractEvidence(source);
  const terms = extractTerms(evidence);
  const seeds = [
    evidence.title,
    ...evidence.headings,
    terms.slice(0, 4).join(" "),
    terms.length > 2 ? `${terms[0]} ${terms[2]}` : undefined,
    terms.length > 3 ? `what is ${terms[0]} ${terms[3]}` : undefined,
  ]
    .filter((value): value is string => !!value)
    .map((value) => clean(value))
    .filter((value, index, all) => value.length > 2 && all.indexOf(value) === index)
    .slice(0, count);

  return {
    source: input.content?.trim() ? "paste" : "url",
    url: input.url || null,
    keyTerms: terms,
    candidates: seeds.map((query, index) => ({
      query,
      rationale:
        index === 0 && evidence.title
          ? "Navigational query built from the page title."
          : "Query seeded directly from extracted page vocabulary.",
      generator: "page_terms",
    })),
    evidence,
  };
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

function extractEvidence(value: string) {
  const isHtml = /<(html|body|main|title|h1|h2|p)\b/i.test(value);
  if (!isHtml) {
    const paragraphs = value.split(/\n\s*\n/).map(clean).filter((text) => text.length > 20);
    return {
      title: paragraphs[0]?.length <= 140 ? paragraphs[0] : null,
      description: paragraphs[1]?.slice(0, 280) || null,
      headings: paragraphs.slice(0, 4).filter((text) => text.length <= 180),
      chunks: paragraphs.slice(0, 10).map((text) => text.slice(0, 900)),
    };
  }
  const withoutNoise = value
    .replace(/<(script|style|noscript|svg|nav|footer|form)\b[\s\S]*?<\/\1>/gi, " ");
  const first = (pattern: RegExp) => clean(decode(withoutNoise.match(pattern)?.[1] || "")) || null;
  const all = (pattern: RegExp) =>
    [...withoutNoise.matchAll(pattern)].map((match) => clean(decode(match[1]))).filter(Boolean);
  return {
    title: first(/<title\b[^>]*>([\s\S]*?)<\/title>/i),
    description:
      first(/<meta\b[^>]*(?:name|property)=["'](?:description|og:description)["'][^>]*content=["']([^"']+)["'][^>]*>/i) ||
      null,
    headings: all(/<h[1-3]\b[^>]*>([\s\S]*?)<\/h[1-3]>/gi).slice(0, 8),
    chunks: all(/<(?:p|li)\b[^>]*>([\s\S]*?)<\/(?:p|li)>/gi)
      .filter((text) => text.length >= 40)
      .slice(0, 10),
  };
}

function extractTerms(evidence: ReturnType<typeof extractEvidence>) {
  const scores = new Map<string, number>();
  const add = (text: string | null, weight: number) => {
    if (!text) return;
    const words = clean(text)
      .match(/[\p{L}\p{N}][\p{L}\p{N}'/-]*/gu)
      ?.filter((word) => word.length >= 3 && !STOP_WORDS.has(word.toLowerCase())) || [];
    for (const word of words) scores.set(word.toLowerCase(), Math.max(scores.get(word.toLowerCase()) || 0, weight));
    for (let index = 0; index < words.length - 1; index += 1) {
      const phrase = `${words[index]} ${words[index + 1]}`.toLowerCase();
      scores.set(phrase, Math.max(scores.get(phrase) || 0, weight + 5));
    }
  };
  add(evidence.title, 100);
  add(evidence.description, 85);
  evidence.headings.forEach((heading) => add(heading, 80));
  evidence.chunks.forEach((chunk) => add(chunk, 35));
  const ranked = [...scores.entries()].sort((a, b) => b[1] - a[1] || b[0].length - a[0].length);
  const selected: string[] = [];
  for (const [term] of ranked) {
    if (selected.some((prior) => prior.includes(term) || term.includes(prior))) continue;
    selected.push(term);
    if (selected.length === 20) break;
  }
  return selected;
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
