import { isGroundingRedirectUrl } from "./citations.ts";
import type { Citation, ObservationState, RunRequest } from "./types.ts";

const MAX_RESOLVE_ATTEMPTS = 12;
const RESOLVE_TIMEOUT_MS = 8_000;

export type RedirectResolution = "resolved" | "failed" | "skipped";

export interface RedirectResolveResult {
  resolvedUrl?: string;
  error?: string;
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
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), RESOLVE_TIMEOUT_MS);
  try {
    const response = await fetcher(url, {
      method: "GET",
      redirect: "follow",
      signal: controller.signal,
      headers: {
        "user-agent": "GroundingObservatory/1.0 (+https://www.torquepartnership.com/)",
      },
    });
    const resolvedUrl = response.url;
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
