import { isGroundingRedirectUrl } from "./citations.ts";
import type { Citation, ObservationState, RunRequest } from "./types.ts";

const MAX_RESOLVE_ATTEMPTS = 12;
const MAX_REDIRECT_HOPS = 5;
const RESOLVE_TIMEOUT_MS = 8_000;
const USER_AGENT = "GroundingObservatory/1.0 (+https://www.torquepartnership.com/)";

export type RedirectResolution = "resolved" | "failed" | "skipped";

export interface RedirectResolveResult {
  resolvedUrl?: string;
  error?: string;
}

export function embeddedGroundingTarget(url: string) {
  try {
    const parsed = new URL(url);
    if (!parsed.hostname.toLowerCase().includes("vertexaisearch.cloud.google.com")) {
      return undefined;
    }
    for (const key of ["url", "q"]) {
      const value = parsed.searchParams.get(key);
      if (value && /^https?:\/\//i.test(value)) return value;
    }
  } catch {
    // Ignore malformed URLs.
  }
  return undefined;
}

function resolveLocation(current: string, location: string) {
  try {
    return new URL(location, current).href;
  } catch {
    return undefined;
  }
}

async function followRedirectChain(
  url: string,
  fetcher: typeof fetch,
  signal: AbortSignal,
) {
  let current = url;
  for (let hop = 0; hop < MAX_REDIRECT_HOPS; hop += 1) {
    if (!isGroundingRedirectUrl(current)) return current;

    let advanced = false;
    for (const method of ["HEAD", "GET"] as const) {
      const response = await fetcher(current, {
        method,
        redirect: "manual",
        signal,
        headers: { "user-agent": USER_AGENT },
      });
      if (response.status >= 300 && response.status < 400) {
        const location = response.headers.get("location");
        const next = location ? resolveLocation(current, location) : undefined;
        if (!next) continue;
        current = next;
        advanced = true;
        break;
      }
      if (
        response.status >= 200 &&
        response.status < 300 &&
        response.url &&
        response.url !== current &&
        !isGroundingRedirectUrl(response.url)
      ) {
        return response.url;
      }
    }
    if (!advanced) break;
  }
  return isGroundingRedirectUrl(current) ? undefined : current;
}

export function shouldResolveCitationRedirects(request: RunRequest) {
  return request.resolveCitationRedirects ?? request.matchMode === "url_prefix";
}

export async function resolveGroundingRedirect(
  url: string,
  fetcher: typeof fetch = fetch,
): Promise<RedirectResolveResult> {
  if (!isGroundingRedirectUrl(url)) {
    return { error: "not_a_grounding_redirect" };
  }

  const embedded = embeddedGroundingTarget(url);
  if (embedded && !isGroundingRedirectUrl(embedded)) {
    return { resolvedUrl: embedded };
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), RESOLVE_TIMEOUT_MS);
  try {
    const resolvedUrl = await followRedirectChain(url, fetcher, controller.signal);
    if (!resolvedUrl || resolvedUrl === url) {
      return { error: "redirect_unresolved" };
    }
    if (isGroundingRedirectUrl(resolvedUrl)) {
      return { error: "redirect_still_opaque" };
    }
    return { resolvedUrl };
  } catch (error) {
    return {
      error: error instanceof Error ? error.message : "redirect_failed",
    };
  } finally {
    clearTimeout(timeout);
  }
}

export async function enrichCitationsWithRedirectResolution(
  citations: Citation[],
  request: RunRequest,
  targetMatches: (request: RunRequest, candidate: string) => boolean,
  fetcher: typeof fetch = fetch,
) {
  if (!shouldResolveCitationRedirects(request)) {
    for (const citation of citations) {
      citation.redirectResolution = "skipped";
    }
    return;
  }

  const pending = [
    ...new Set(
      citations
        .filter((citation) => isGroundingRedirectUrl(citation.url) && !citation.targetMatch)
        .map((citation) => citation.url),
    ),
  ].slice(0, MAX_RESOLVE_ATTEMPTS);

  const cache = new Map<string, RedirectResolveResult>();
  await Promise.all(
    pending.map(async (url) => {
      cache.set(url, await resolveGroundingRedirect(url, fetcher));
    }),
  );

  for (const citation of citations) {
    if (!isGroundingRedirectUrl(citation.url)) {
      citation.redirectResolution = "skipped";
      continue;
    }
    if (citation.targetMatch) {
      citation.redirectResolution = "skipped";
      continue;
    }
    const result = cache.get(citation.url);
    if (!result) {
      citation.redirectResolution = "failed";
      citation.redirectResolutionError = "not_attempted";
      continue;
    }
    if (result.resolvedUrl) {
      citation.resolvedUrl = result.resolvedUrl;
      citation.redirectResolution = "resolved";
      if (targetMatches(request, result.resolvedUrl)) {
        citation.targetMatch = true;
      }
    } else {
      citation.redirectResolution = "failed";
      citation.redirectResolutionError = result.error;
    }
  }
}

export function geminiTargetCited(
  citations: Citation[],
  request: RunRequest,
): ObservationState {
  if (citations.some((citation) => citation.targetMatch)) return "YES";
  if (!shouldResolveCitationRedirects(request)) return "NO";

  const unresolvedRedirects = citations.some(
    (citation) =>
      isGroundingRedirectUrl(citation.url) &&
      !citation.targetMatch &&
      citation.redirectResolution === "failed",
  );
  if (request.matchMode === "url_prefix" && unresolvedRedirects) return "UNKNOWN";
  return "NO";
}
