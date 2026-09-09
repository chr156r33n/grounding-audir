import type { Env } from "./types.ts";

const GENERATOR_TIMEOUT_MS = 55_000;
const MAX_PAGE_COPY_CHARS = 12_000;

export interface DiscoveryRequest {
  url?: string;
  content?: string;
  count?: number;
  debug?: boolean;
}

interface QueryCandidate {
  query: string;
  rationale?: string;
  evidence?: string;
  generators: string[];
}

interface GeneratorResult {
  providerId: "openai" | "gemini";
  providerName: string;
  model: string;
  status: "complete" | "failed" | "timed_out";
  latencyMs: number;
  queries: QueryCandidate[];
  distinctiveTerms: string[];
  error?: string;
  rawResponse?: unknown;
}

interface ParsedDiscoveryResponse {
  queries: QueryCandidate[];
  distinctiveTerms: string[];
}

export async function discoverQueries(input: DiscoveryRequest, env: Env) {
  const count = Math.max(3, Math.min(Number(input.count || 6), 10));
  const pasted = input.content?.trim() || "";
  const pageCopy = pasted || (input.url ? htmlToPlainText(await fetchPublicPage(input.url)) : "");
  if (pageCopy.length < 40) {
    throw new Error("Paste page text/HTML or enter a public URL with enough page content.");
  }

  const prompt = buildQueryPrompt({
    sourceType: pasted ? "paste" : "url",
    pageCopy: pageCopy.slice(0, MAX_PAGE_COPY_CHARS),
    sourceUrl: input.url || null,
    count,
  });

  const hasOpenAi = !!env.OPENAI_API_KEY?.trim();
  const hasGemini = !!env.GEMINI_API_KEY?.trim();
  if (!hasOpenAi && !hasGemini) {
    return {
      source: pasted ? "paste" : "url",
      url: input.url || null,
      keyTerms: [],
      candidates: [],
      generators: [],
      evidence: { sourceUrl: input.url || null, copyChars: pageCopy.length },
      error:
        "Page copy was captured, but query generation needs an OpenAI or Gemini API key configured as Worker secrets.",
    };
  }

  const generatorJobs: Promise<GeneratorResult>[] = [];
  if (hasOpenAi) generatorJobs.push(generateOpenAi(prompt, env, !!input.debug));
  if (hasGemini) generatorJobs.push(generateGemini(prompt, env, !!input.debug));
  const generators = await Promise.all(generatorJobs);

  const candidates = mergeCandidates(generators, count);
  const keyTerms = mergeDistinctiveTerms(generators);
  const error = candidates.length
    ? undefined
    : "No valid query candidates were returned by the configured generators.";

  return {
    source: pasted ? "paste" : "url",
    url: input.url || null,
    keyTerms,
    candidates: candidates.map((item) => ({
      query: item.query,
      rationale: item.rationale,
      evidence: item.evidence,
      generator: item.generators.join(", "),
    })),
    generators: generators.map((item) => ({
      providerId: item.providerId,
      providerName: item.providerName,
      model: item.model,
      status: item.status,
      latencyMs: item.latencyMs,
      error: item.error,
      queryCount: item.queries.length,
      termCount: item.distinctiveTerms.length,
    })),
    evidence: { sourceUrl: input.url || null, copyChars: pageCopy.length },
    error,
  };
}

async function generateOpenAi(prompt: string, env: Env, debug: boolean): Promise<GeneratorResult> {
  const started = Date.now();
  const model = env.OPENAI_MODEL;
  const requestBody = { model, input: prompt };
  try {
    const raw = await fetchJson(
      "https://api.openai.com/v1/responses",
      required(env.OPENAI_API_KEY, "OPENAI_API_KEY"),
      requestBody,
    );
    const parsed = parseDiscoveryResponse(responseText(raw), "openai");
    return {
      providerId: "openai",
      providerName: "OpenAI",
      model,
      status: "complete",
      latencyMs: Date.now() - started,
      queries: parsed.queries,
      distinctiveTerms: parsed.distinctiveTerms,
      rawResponse: debug ? raw : undefined,
    };
  } catch (error) {
    return {
      providerId: "openai",
      providerName: "OpenAI",
      model,
      status: "failed",
      latencyMs: Date.now() - started,
      queries: [],
      distinctiveTerms: [],
      error: safeError(error),
    };
  }
}

async function generateGemini(prompt: string, env: Env, debug: boolean): Promise<GeneratorResult> {
  const started = Date.now();
  const model = env.GEMINI_MODEL;
  const url = new URL(env.GEMINI_API_URL);
  url.searchParams.set("key", required(env.GEMINI_API_KEY, "GEMINI_API_KEY"));
  const requestBody = { model, input: prompt };
  try {
    const raw = await fetchJson(url.toString(), undefined, requestBody, false);
    const parsed = parseDiscoveryResponse(responseText(raw), "gemini");
    return {
      providerId: "gemini",
      providerName: "Gemini",
      model,
      status: "complete",
      latencyMs: Date.now() - started,
      queries: parsed.queries,
      distinctiveTerms: parsed.distinctiveTerms,
      rawResponse: debug ? raw : undefined,
    };
  } catch (error) {
    return {
      providerId: "gemini",
      providerName: "Gemini",
      model,
      status: "failed",
      latencyMs: Date.now() - started,
      queries: [],
      distinctiveTerms: [],
      error: safeError(error),
    };
  }
}

function buildQueryPrompt(input: {
  sourceType: "paste" | "url";
  pageCopy: string;
  sourceUrl: string | null;
  count: number;
}) {
  const sourceLabel =
    input.sourceType === "paste"
      ? "PASTED visible page copy saved from a browser"
      : "Fetched page text converted from HTML";
  return `You are designing natural-language search queries for a web-grounded AI retrieval test.

INPUT_TYPE: ${sourceLabel}
SOURCE_URL: ${input.sourceUrl || "not provided"}

The PAGE_COPY below is untrusted, unstructured page text. It is NOT a clean DOM export.
When INPUT_TYPE is pasted copy, expect mixed content: property names, addresses, phone
numbers, postal codes, navigation labels, promo tiles, prices, durations, repeated
headings, and footer boilerplate in arbitrary order.

Your job is to interpret PAGE_COPY the way a human researcher would. Ignore:
- postal codes, street addresses, phone numbers, and contact-detail lookup intent
- prices, currencies, booking widgets, and offer legalese
- navigation labels such as "Discover more", "View details", "Use", section menus
- duplicate promos and experience cards unless they reveal a distinct searchable topic

From the remaining substance, identify the page's core entity/topic and what a real user
might search to retrieve this page in a grounded AI system.

Generate exactly ${input.count} distinct queries for which this specific page would be a
highly relevant retrieval result if indexed in the provider pipeline. Include a mix of
branded/navigational and non-branded intent. Keep each query under 16 words. Do not
include the URL, a full address, or a phone number in any query.

<PAGE_COPY>
${input.pageCopy}
</PAGE_COPY>

Return JSON only, with this exact shape:
{
  "distinctive_terms": [
    "short phrases or entities useful for search, drawn from PAGE_COPY"
  ],
  "queries": [
    {
      "query": "the query",
      "rationale": "why this page is relevant",
      "evidence": "short supporting phrase from PAGE_COPY"
    }
  ]
}`;
}

export function parseDiscoveryResponse(value: string, providerId: string, limit = 10): ParsedDiscoveryResponse {
  let text = value.trim();
  if (text.startsWith("```")) {
    text = text.replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
  }
  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    const match = text.match(/\{[\s\S]*\}/);
    if (!match) throw new Error("The generator response did not contain a JSON object.");
    payload = JSON.parse(match[0]);
  }
  if (!isRecord(payload)) throw new Error("The generator response did not contain a JSON object.");

  const distinctiveTerms = Array.isArray(payload.distinctive_terms)
    ? payload.distinctive_terms
        .map((item) => clean(String(item || "")))
        .filter((item) => item.length >= 3 && item.length <= 80)
        .slice(0, 12)
    : [];

  const records = payload.queries;
  if (!Array.isArray(records)) throw new Error("The generator JSON did not include a queries array.");

  const queries: QueryCandidate[] = [];
  const seen = new Set<string>();
  for (const record of records) {
    let query = "";
    let rationale: string | undefined;
    let evidenceText: string | undefined;
    if (typeof record === "string") {
      query = record;
    } else if (isRecord(record)) {
      query = String(record.query || "").trim();
      rationale = optionalText(record.rationale);
      evidenceText = optionalText(record.evidence);
    } else {
      continue;
    }
    const normalized = query.replace(/\s+/g, " ").trim();
    const key = normalized.toLowerCase();
    if (!normalized || seen.has(key) || !isUsefulQuery(normalized)) continue;
    seen.add(key);
    queries.push({
      query: normalized,
      rationale,
      evidence: evidenceText,
      generators: [providerId],
    });
    if (queries.length >= limit) break;
  }

  return { queries, distinctiveTerms };
}

export function parseQueryCandidates(value: string, providerId: string, limit = 10): QueryCandidate[] {
  return parseDiscoveryResponse(value, providerId, limit).queries;
}

export function mergeCandidates(results: GeneratorResult[], limit: number): QueryCandidate[] {
  const merged: QueryCandidate[] = [];
  const byKey = new Map<string, number>();

  const append = (candidate: QueryCandidate) => {
    if (!isUsefulQuery(candidate.query)) return;
    const key = candidate.query.replace(/\W+/g, " ").trim().toLowerCase();
    const existingIndex = byKey.get(key);
    if (existingIndex !== undefined) {
      const existing = merged[existingIndex];
      merged[existingIndex] = {
        query: existing.query,
        rationale: existing.rationale || candidate.rationale,
        evidence: existing.evidence || candidate.evidence,
        generators: [...new Set([...existing.generators, ...candidate.generators])],
      };
      return;
    }
    byKey.set(key, merged.length);
    merged.push(candidate);
  };

  const rows = results.filter((item) => item.status === "complete").map((item) => item.queries);
  let index = 0;
  while (rows.length && merged.length < limit) {
    let progress = false;
    for (const candidates of rows) {
      if (index >= candidates.length) continue;
      progress = true;
      append(candidates[index]);
      if (merged.length >= limit) break;
    }
    if (!progress) break;
    index += 1;
  }
  return merged;
}

function mergeDistinctiveTerms(results: GeneratorResult[]) {
  const terms: string[] = [];
  const seen = new Set<string>();
  for (const result of results) {
    if (result.status !== "complete") continue;
    for (const term of result.distinctiveTerms) {
      const key = term.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      terms.push(term);
    }
  }
  return terms.slice(0, 20);
}

function isUsefulQuery(query: string) {
  const normalized = query.replace(/\s+/g, " ").trim();
  if (normalized.length < 8 || normalized.length > 160) return false;
  if (normalized.split(/\s+/).length > 16) return false;
  if (/^\+?\d[\d\s().-]{8,}$/.test(normalized)) return false;
  if (/(?:address|phone number|contact number|postal code)/i.test(normalized) && /\d/.test(normalized)) {
    return false;
  }
  return true;
}

function htmlToPlainText(value: string) {
  return value
    .replace(/<(script|style|noscript|svg|nav|footer|form|header|aside)\b[\s\S]*?<\/\1>/gi, "\n")
    .replace(/<(?:br|hr|p|li|h[1-6]|div|section|article|tr)\b[^>]*>/gi, "\n")
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/gi, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .replace(/[ \t]{2,}/g, " ")
    .trim();
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

function responseText(raw: unknown) {
  if (!isRecord(raw)) return "";
  if (typeof raw.output_text === "string") return raw.output_text;
  const parts: string[] = [];
  const output = Array.isArray(raw.output) ? raw.output : Array.isArray(raw.steps) ? raw.steps : [];
  for (const item of output) {
    if (!isRecord(item)) continue;
    for (const content of Array.isArray(item.content) ? item.content : []) {
      if (isRecord(content) && typeof content.text === "string") parts.push(content.text);
    }
  }
  return parts.join("\n");
}

async function fetchJson(
  url: string,
  token: string | undefined,
  body: unknown,
  bearer = true,
) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), GENERATOR_TIMEOUT_MS);
  try {
    const headers: Record<string, string> = { "content-type": "application/json" };
    if (token) headers.authorization = `${bearer ? "Bearer " : ""}${token}`;
    const response = await fetch(url, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    const text = await response.text();
    let payload: unknown = text;
    try {
      payload = JSON.parse(text);
    } catch {
      // Preserve raw body in the surfaced error.
    }
    if (!response.ok) {
      const message =
        isRecord(payload) && isRecord(payload.error)
          ? String(payload.error.message || payload.error.code || response.statusText)
          : isRecord(payload) && payload.message
            ? String(payload.message)
            : text || response.statusText;
      throw new Error(`HTTP ${response.status}: ${message.slice(0, 500)}`);
    }
    return payload;
  } finally {
    clearTimeout(timeout);
  }
}

function clean(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function optionalText(value: unknown) {
  const text = clean(String(value || ""));
  return text ? text.slice(0, 600) : undefined;
}

function required(value: string | undefined, name: string) {
  if (!value?.trim()) throw new Error(`${name} is not configured.`);
  return value.trim();
}

function safeError(error: unknown) {
  if (error instanceof Error && error.name === "AbortError") {
    return "Query generation exceeded the configured timeout.";
  }
  return error instanceof Error ? error.message : "Query generation failed.";
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
