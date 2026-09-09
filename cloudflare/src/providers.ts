import type {
  Citation,
  Env,
  GeneratedQuery,
  ProviderId,
  ProviderRun,
  RunRequest,
  Source,
} from "./types.ts";
import {
  parseHtmlLinkCitations,
  parseMarkdownLinkCitations,
  targetMatchesCitation,
} from "./citations.ts";
import { getDomain } from "tldts";

const NAMES: Record<ProviderId, string> = {
  openai_web: "OpenAI Web Search",
  deepseek_web: "DeepSeek Web Search",
  gemini: "Gemini + Google Search",
  microsoft_web: "Microsoft Foundry Web Search",
  microsoft_web_iq: "Microsoft Web IQ",
};

const INSTRUCTION = (query: string) =>
  `Answer this query using current public-web evidence. Search the web before answering. Query: ${query}`;

export function configuredProviders(env: Env) {
  return [
    providerConfig("openai_web", !!env.OPENAI_API_KEY, env.OPENAI_MODEL),
    providerConfig("deepseek_web", !!env.DEEPSEEK_API_KEY, env.DEEPSEEK_MODEL),
    providerConfig("gemini", !!env.GEMINI_API_KEY, env.GEMINI_MODEL),
    providerConfig(
      "microsoft_web",
      !!(env.AZURE_ACCESS_TOKEN && env.FOUNDRY_PROJECT_ENDPOINT),
      env.FOUNDRY_MODEL,
    ),
    providerConfig("microsoft_web_iq", !!env.WEBIQ_API_KEY, "web-search"),
  ];
}

function providerConfig(id: ProviderId, configured: boolean, model: string) {
  return { id, name: NAMES[id], configured, model };
}

export async function runProvider(
  id: ProviderId,
  request: RunRequest,
  env: Env,
): Promise<ProviderRun> {
  const started = Date.now();
  try {
    let raw: unknown;
    let model: string;
    if (id === "openai_web") {
      model = env.OPENAI_MODEL;
      raw = await responsesFetch(
        "https://api.openai.com/v1/responses",
        env.OPENAI_API_KEY,
        model,
        request,
      );
    } else if (id === "deepseek_web") {
      model = env.DEEPSEEK_MODEL;
      raw = await responsesFetch(
        `${env.DEEPSEEK_BASE_URL.replace(/\/$/, "")}/responses`,
        env.DEEPSEEK_API_KEY,
        model,
        request,
      );
    } else if (id === "microsoft_web") {
      model = env.FOUNDRY_MODEL;
      raw = await responsesFetch(
        `${required(env.FOUNDRY_PROJECT_ENDPOINT, "FOUNDRY_PROJECT_ENDPOINT").replace(/\/$/, "")}/openai/v1/responses`,
        env.AZURE_ACCESS_TOKEN,
        model,
        request,
        {
          type: "web_search",
          search_context_size: env.FOUNDRY_SEARCH_CONTEXT_SIZE || "medium",
          ...locationTool(request.market),
        },
      );
    } else if (id === "gemini") {
      model = env.GEMINI_MODEL;
      raw = await geminiFetch(request, env);
      return parseGemini(raw, request, model, Date.now() - started);
    } else {
      model = "web-search";
      raw = await webIqFetch(request, env);
      return parseWebIq(raw, request, model, Date.now() - started);
    }
    return parseResponses(id, raw, request, model, Date.now() - started);
  } catch (error) {
    return {
      providerId: id,
      providerName: NAMES[id],
      model: modelFor(id, env),
      status: "failed",
      latencyMs: Date.now() - started,
      searchPerformed: "UNKNOWN",
      targetRetrieved: "UNKNOWN",
      targetCited: id === "microsoft_web_iq" ? "N/A" : "UNKNOWN",
      generatedQueries: [],
      sources: [],
      citations: [],
      error: safeError(error),
      metadata: {},
    };
  }
}

async function responsesFetch(
  url: string,
  token: string | undefined,
  model: string,
  request: RunRequest,
  tool: Record<string, unknown> = {
    type: "web_search",
    ...locationTool(request.market),
  },
) {
  return fetchJson(url, token, {
    model,
    input: INSTRUCTION(request.query),
    tools: [tool],
    tool_choice: "required",
    include: ["web_search_call.action.sources", "web_search_call.results"],
  });
}

async function geminiFetch(request: RunRequest, env: Env) {
  const url = new URL(env.GEMINI_API_URL);
  url.searchParams.set("key", required(env.GEMINI_API_KEY, "GEMINI_API_KEY"));
  return fetchJson(
    url.toString(),
    undefined,
    {
      model: env.GEMINI_MODEL,
      input: INSTRUCTION(request.query),
      tools: [{ type: "google_search", search_types: ["web_search"] }],
    },
    false,
  );
}

async function webIqFetch(request: RunRequest, env: Env) {
  const locale = marketLocale(request);
  const key = required(env.WEBIQ_API_KEY, "WEBIQ_API_KEY");
  const response = await fetch(env.WEBIQ_API_URL, {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-apikey": key,
    },
    body: JSON.stringify({
      query: request.query,
      maxResults: Number(env.WEBIQ_MAX_RESULTS || 10),
      language: locale.language,
      region: locale.region,
      contentFormat: "passage",
    }),
  });
  return readResponse(response);
}

async function fetchJson(
  url: string,
  token: string | undefined,
  body: unknown,
  bearer = true,
) {
  const headers: Record<string, string> = { "content-type": "application/json" };
  if (token) headers.authorization = `${bearer ? "Bearer " : ""}${token}`;
  const response = await fetch(url, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  return readResponse(response);
}

async function readResponse(response: Response) {
  const text = await response.text();
  let payload: unknown = text;
  try {
    payload = JSON.parse(text);
  } catch {
    // Preserve the body in the surfaced error.
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
}

function parseResponses(
  id: ProviderId,
  raw: unknown,
  request: RunRequest,
  model: string,
  latencyMs: number,
): ProviderRun {
  const payload = isRecord(raw) ? raw : {};
  const output = Array.isArray(payload.output) ? payload.output : [];
  const generatedQueries: GeneratedQuery[] = [];
  const sources: Source[] = [];
  const citations: Citation[] = [];
  const textParts: string[] = [];
  let searchCalls = 0;
  let sourcesObservable = false;
  let anchorReferences = 0;
  const seenQueries = new Set<string>();

  for (const item of output) {
    if (!isRecord(item)) continue;
    const type = String(item.type || "");
    if (type === "web_search_call" || type === "bing_grounding_call") {
      searchCalls += 1;
      const action = isRecord(item.action) ? item.action : {};
      const callStatus = stringValue(item.status);
      const actionType = stringValue(action.type);
      const argumentRecords = parseArgumentRecords(item.arguments);
      for (const query of [
        ...extractQueryRecords(action),
        ...extractQueryRecords(argumentRecords),
      ]) {
        const key = query.toLowerCase();
        if (seenQueries.has(key)) continue;
        seenQueries.add(key);
        generatedQueries.push({ query, actionType, callStatus });
      }
      for (const record of collectSearchSourceRecords(item)) {
        appendSource(sources, request, record, callStatus, actionType);
        sourcesObservable = true;
      }
    }
    if (type !== "message" || !Array.isArray(item.content)) continue;
    for (const content of item.content) {
      if (!isRecord(content) || !["output_text", "text"].includes(String(content.type))) continue;
      const text = stringValue(content.text) || "";
      textParts.push(text);
      if (Array.isArray(content.annotations)) {
        for (const annotation of content.annotations) {
          if (!isRecord(annotation)) continue;
          const url = recordUrl(annotation);
          if (!url) {
            if (
              typeof annotation.title === "string" ||
              typeof annotation.name === "string" ||
              sliceText(text, annotation.start_index, annotation.end_index)
            ) {
              anchorReferences += 1;
            }
            continue;
          }
          citations.push({
            url,
            title: stringValue(annotation.title || annotation.name),
            citedText: sliceText(text, annotation.start_index, annotation.end_index),
            targetMatch: targetMatchesCitation(
              request,
              url,
              targetMatches,
              sliceText(text, annotation.start_index, annotation.end_index) ||
                stringValue(annotation.title || annotation.name),
            )
              ? "YES"
              : "NO",
          });
        }
      }
    }
  }
  const responseText = textParts.join("\n") || stringValue(payload.output_text);
  if (!citations.length && responseText) {
    citations.push(...parseMarkdownLinkCitations(responseText, request, targetMatches));
  }
  for (const source of sources) {
    if (citations.some((citation) => citation.url === source.url)) source.cited = "YES";
  }
  return {
    providerId: id,
    providerName: NAMES[id],
    model,
    status: "complete",
    latencyMs,
    searchPerformed: searchCalls ? "YES" : output.length ? "NO" : "UNKNOWN",
    targetRetrieved: sources.length
      ? sources.some((source) => source.targetMatch)
        ? "YES"
        : "NO"
      : sourcesObservable
        ? "NO"
        : "UNKNOWN",
    targetCited: citations.some((citation) => citation.targetMatch)
      ? "YES"
      : anchorReferences
        ? "UNKNOWN"
        : "NO",
    generatedQueries,
    sources,
    citations,
    responseText,
    metadata: {
      responseId: payload.id,
      actualModel: payload.model,
      usage: payload.usage,
      sourcesObservable,
      anchorReferencesWithoutUrl: anchorReferences,
      openedPageCount: sources.filter((source) => source.sourceOrigin === "open_page").length,
      sourceListCount: sources.filter((source) => source.sourceOrigin === "source_list").length,
    },
    ...(request.debug ? { rawResponse: raw } : {}),
  };
}

function parseGemini(
  raw: unknown,
  request: RunRequest,
  model: string,
  latencyMs: number,
): ProviderRun {
  const payload = isRecord(raw) ? raw : {};
  const steps = Array.isArray(payload.steps) ? payload.steps : [];
  const generatedQueries: GeneratedQuery[] = [];
  const citations: Citation[] = [];
  const seenCitationUrls = new Set<string>();
  const textParts: string[] = [];
  let searchCalls = 0;

  const pushCitation = (citation: Citation) => {
    if (seenCitationUrls.has(citation.url)) return;
    seenCitationUrls.add(citation.url);
    citations.push(citation);
  };

  for (const step of steps) {
    if (!isRecord(step)) continue;
    if (step.type === "google_search_call") {
      searchCalls += 1;
      const args = isRecord(step.arguments) ? step.arguments : {};
      if (Array.isArray(args.queries)) {
        for (const query of args.queries) {
          const normalized = extractQueryText(query);
          if (normalized) generatedQueries.push({ query: normalized, actionType: "search" });
        }
      }
    }
    if (step.type !== "model_output" || !Array.isArray(step.content)) continue;
    for (const content of step.content) {
      if (!isRecord(content) || typeof content.text !== "string") continue;
      textParts.push(content.text);
      if (!Array.isArray(content.annotations)) continue;
      for (const annotation of content.annotations) {
        if (!isRecord(annotation)) continue;
        const url = recordUrl(annotation);
        if (!url) continue;
        const citedText = sliceText(content.text, annotation.start_index, annotation.end_index);
        const title = stringValue(annotation.title);
        pushCitation({
          url,
          title,
          citedText,
          targetMatch: targetMatchesCitation(request, url, targetMatches, citedText || title)
            ? "YES"
            : "NO",
        });
      }
    }
  }
  const responseText = textParts.join("\n") || stringValue(payload.output_text);
  if (responseText) {
    for (const citation of parseHtmlLinkCitations(responseText, request, targetMatches)) {
      pushCitation(citation);
    }
    if (!citations.length) {
      for (const citation of parseMarkdownLinkCitations(responseText, request, targetMatches)) {
        pushCitation(citation);
      }
    }
  }
  return {
    providerId: "gemini",
    providerName: NAMES.gemini,
    model,
    status: "complete",
    latencyMs,
    searchPerformed: searchCalls ? "YES" : steps.length ? "NO" : "UNKNOWN",
    targetRetrieved: "UNKNOWN",
    targetCited: citations.some((citation) => citation.targetMatch) ? "YES" : "NO",
    generatedQueries,
    sources: [],
    citations,
    responseText,
    metadata: { interactionId: payload.id, actualModel: payload.model, usage: payload.usage },
    ...(request.debug ? { rawResponse: raw } : {}),
  };
}

function parseWebIq(
  raw: unknown,
  request: RunRequest,
  model: string,
  latencyMs: number,
): ProviderRun {
  const payload = isRecord(raw) ? raw : {};
  const items = Array.isArray(payload.webResults)
    ? payload.webResults
    : Array.isArray(payload.web_results)
      ? payload.web_results
      : [];
  const sources = items.flatMap((item, index): Source[] => {
    if (!isRecord(item)) return [];
    const url = recordUrl(item);
    if (!url) return [];
    return [{
      url,
      title: stringValue(item.title),
      snippet: stringValue(item.content)?.slice(0, 240),
      position: index + 1,
      targetMatch: targetMatches(request, url),
      cited: "N/A",
    }];
  });
  return {
    providerId: "microsoft_web_iq",
    providerName: NAMES.microsoft_web_iq,
    model,
    status: "complete",
    latencyMs,
    searchPerformed: items.length ? "YES" : "NO",
    targetRetrieved: sources.some((source) => source.targetMatch) ? "YES" : "NO",
    targetCited: "N/A",
    generatedQueries: [{ query: request.query, actionType: "input" }],
    sources,
    citations: [],
    metadata: { resultCount: sources.length },
    ...(request.debug ? { rawResponse: raw } : {}),
  };
}

function targetMatches(request: RunRequest, candidate: string) {
  try {
    const candidateUrl = new URL(candidate.includes("://") ? candidate : `https://${candidate}`);
    const targetUrl = new URL(
      request.target.includes("://") ? request.target : `https://${request.target}`,
    );
    if (request.matchMode === "exact_hostname") {
      return candidateUrl.hostname.toLowerCase() === targetUrl.hostname.toLowerCase();
    }
    if (request.matchMode === "url_prefix") {
      return (
        candidateUrl.origin === targetUrl.origin &&
        (candidateUrl.pathname === targetUrl.pathname ||
          candidateUrl.pathname.startsWith(`${targetUrl.pathname.replace(/\/$/, "")}/`))
      );
    }
    return rootDomain(candidateUrl.hostname) === rootDomain(targetUrl.hostname);
  } catch {
    return false;
  }
}

function recordUrl(record: Record<string, unknown>) {
  for (const key of ["url", "link", "href", "source_url", "uri", "source"]) {
    if (typeof record[key] === "string" && /^https?:\/\//i.test(record[key])) {
      return record[key] as string;
    }
  }
  return undefined;
}

function locationTool(market?: string) {
  if (!market) return {};
  const country = market.replace("_", "-").split("-").at(-1);
  return country?.length === 2
    ? { user_location: { type: "approximate", country: country.toUpperCase() } }
    : {};
}

function parseArgumentRecords(value: unknown): Record<string, unknown> {
  if (isRecord(value)) return value;
  if (typeof value !== "string") return {};
  try {
    const parsed = JSON.parse(value);
    return isRecord(parsed) ? parsed : {};
  } catch {
    return {};
  }
}

function extractQueryText(value: unknown): string | undefined {
  if (typeof value === "string") return normalizeGeneratedQuery(value);
  if (typeof value === "number" || typeof value === "boolean") {
    return normalizeGeneratedQuery(String(value));
  }
  if (isRecord(value)) {
    for (const key of ["query", "search_query", "text", "q"]) {
      if (!(key in value)) continue;
      const text = extractQueryText(value[key]);
      if (text) return text;
    }
  }
  return undefined;
}

function extractQueryRecords(value: unknown): string[] {
  const results: string[] = [];
  const push = (text?: string) => {
    if (text && !results.includes(text)) results.push(text);
  };

  if (typeof value === "string") {
    push(normalizeGeneratedQuery(value));
    return results;
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      for (const text of extractQueryRecords(item)) push(text);
    }
    return results;
  }
  if (!isRecord(value)) return results;

  for (const [key, item] of Object.entries(value)) {
    const normalizedKey = key.toLowerCase();
    if (normalizedKey === "query" || normalizedKey === "search_query") {
      push(extractQueryText(item));
      if (typeof item === "string") push(normalizeGeneratedQuery(item));
    } else if (
      (normalizedKey === "queries" || normalizedKey === "search_queries") &&
      Array.isArray(item)
    ) {
      for (const nested of item) {
        push(extractQueryText(nested));
        if (!extractQueryText(nested)) {
          for (const text of extractQueryRecords(nested)) push(text);
        }
      }
    } else if (isRecord(item) || Array.isArray(item)) {
      for (const text of extractQueryRecords(item)) push(text);
    }
  }
  return results;
}

function collectSearchSourceRecords(item: Record<string, unknown>) {
  const action = isRecord(item.action) ? item.action : {};
  const records: Array<Record<string, unknown>> = [];
  for (const key of ["sources", "results", "pages", "items"]) {
    if (!(key in action)) continue;
    for (const record of recordsList(action[key])) {
      records.push({ ...record, sourceOrigin: "source_list" });
    }
  }
  const actionUrl = recordUrl(action);
  if (actionUrl) {
    records.push({
      ...action,
      url: actionUrl,
      sourceOrigin: String(action.type || "").toLowerCase() === "open_page" ? "open_page" : "action",
    });
  }
  for (const key of ["results", "sources"]) {
    if (!(key in item)) continue;
    for (const record of recordsList(item[key])) {
      records.push({ ...record, sourceOrigin: "source_list" });
    }
  }
  return records;
}

function appendSource(
  sources: Source[],
  request: RunRequest,
  record: Record<string, unknown>,
  callStatus?: string,
  actionType?: string,
) {
  const url = recordUrl(record);
  if (!url || sources.some((source) => source.url === url)) return;
  const origin = record.sourceOrigin === "open_page"
    ? "open_page"
    : record.sourceOrigin === "action"
      ? "action"
      : "source_list";
  sources.push({
    url,
    title: stringValue(record.title || record.name),
    snippet: stringValue(record.snippet || record.description),
    position: sources.length + 1,
    targetMatch: targetMatches(request, url),
    cited: "NO",
    sourceOrigin: origin,
    callStatus,
    actionType,
  });
}

function recordsList(value: unknown): Record<string, unknown>[] {
  if (Array.isArray(value)) return value.filter(isRecord);
  if (isRecord(value)) {
    return Object.values(value).flatMap((item) => (Array.isArray(item) ? item.filter(isRecord) : []));
  }
  return [];
}

function normalizeGeneratedQuery(value: string) {
  const text = value.replace(/\s+/g, " ").trim().replace(/(?:^|[,\s;]+)ws_call_id=[^\s,;]+/gi, "").trim(" ,;");
  if (!text || text.toLowerCase() === "[object object]" || text.length > 300) return undefined;
  return text;
}

function marketLocale(request: RunRequest) {
  const parts = request.market?.replace("_", "-").split("-") || [];
  return {
    language: request.language || parts[0] || undefined,
    region: parts.at(-1)?.length === 2 ? parts.at(-1)?.toUpperCase() : undefined,
  };
}

function rootDomain(hostname: string) {
  const normalized = hostname.toLowerCase().replace(/\.$/, "");
  return getDomain(normalized, { allowPrivateDomains: true }) || normalized;
}

function modelFor(id: ProviderId, env: Env) {
  if (id === "openai_web") return env.OPENAI_MODEL;
  if (id === "deepseek_web") return env.DEEPSEEK_MODEL;
  if (id === "gemini") return env.GEMINI_MODEL;
  if (id === "microsoft_web") return env.FOUNDRY_MODEL;
  return "web-search";
}

function required(value: string | undefined, name: string) {
  if (!value?.trim()) throw new Error(`${name} is not configured on this Worker.`);
  return value.trim();
}

function safeError(error: unknown) {
  return error instanceof Error ? error.message : "The provider request failed.";
}

function stringValue(value: unknown) {
  return typeof value === "string" && value ? value : undefined;
}

function sliceText(text: string, start: unknown, end: unknown) {
  return typeof start === "number" && typeof end === "number" ? text.slice(start, end) : undefined;
}

function isRecord(value: unknown): value is Record<string, any> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}
