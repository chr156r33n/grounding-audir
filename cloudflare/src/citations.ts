import type { Citation, RunRequest } from "./types.ts";
import { matchingTargets } from "./targets.ts";

const HTML_LINK = /<a\b[^>]*\bhref=["'](https?:\/\/[^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;
const MARKDOWN_LINK = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g;

export function isGroundingRedirectUrl(url: string) {
  const lowered = url.toLowerCase();
  return (
    lowered.includes("grounding-api-redirect") ||
    lowered.includes("vertexaisearch.cloud.google.com")
  );
}

export function citationTargetHints(...values: Array<string | undefined>) {
  const hints: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (!value) continue;
    const cleaned = value.replace(/\s+/g, " ").trim();
    if (!cleaned) continue;
    const candidates = cleaned.includes("/") ? [cleaned, cleaned.split("/")[0] || ""] : [cleaned];
    for (const candidate of candidates) {
      const normalized = candidate.trim();
      if (!normalized || seen.has(normalized)) continue;
      seen.add(normalized);
      hints.push(normalized.includes("://") ? normalized : `https://${normalized}`);
    }
  }
  return hints;
}

export function citationMatchFields(
  request: RunRequest,
  url: string,
  ...hints: Array<string | undefined>
) {
  const direct = matchingTargets(request, url);
  if (direct.length) {
    return { targetMatch: true, targetMatches: direct };
  }
  if (!isGroundingRedirectUrl(url)) {
    return { targetMatch: false, targetMatches: [] as string[] };
  }
  const matched = new Set<string>();
  for (const hint of hints) {
    for (const candidate of citationTargetHints(hint)) {
      for (const value of matchingTargets(request, candidate)) {
        matched.add(value);
      }
    }
  }
  const targetMatches = [...matched];
  return { targetMatch: targetMatches.length > 0, targetMatches };
}

export function targetMatchesCitation(
  request: RunRequest,
  url: string,
  _targetMatches: (request: RunRequest, candidate: string) => boolean,
  ...hints: Array<string | undefined>
) {
  return citationMatchFields(request, url, ...hints).targetMatch;
}

export function appendOrMergeCitation(citations: Citation[], incoming: Citation) {
  const existing = citations.find((citation) => citation.url === incoming.url);
  if (!existing) {
    citations.push(incoming);
    return;
  }
  existing.title ||= incoming.title;
  existing.citedText ||= incoming.citedText;
  existing.targetMatches = [...new Set([...existing.targetMatches, ...incoming.targetMatches])];
  existing.targetMatch = existing.targetMatches.length > 0;
  existing.resolvedUrl ||= incoming.resolvedUrl;
  existing.redirectResolution ||= incoming.redirectResolution;
  existing.redirectResolutionError ||= incoming.redirectResolutionError;
}

export function parseHtmlLinkCitations(text: string, request: RunRequest): Citation[] {
  const citations: Citation[] = [];
  const seen = new Set<string>();
  for (const match of text.matchAll(HTML_LINK)) {
    const url = match[1].trim();
    const anchorText = match[2].replace(/<[^>]+>/g, "").replace(/\s+/g, " ").trim();
    if (seen.has(url)) continue;
    seen.add(url);
    citations.push({
      url,
      title: anchorText || undefined,
      citedText: anchorText || undefined,
      ...citationMatchFields(request, url, anchorText),
    });
  }
  return citations;
}

export function parseMarkdownLinkCitations(text: string, request: RunRequest): Citation[] {
  const citations: Citation[] = [];
  const seen = new Set<string>();
  for (const match of text.matchAll(MARKDOWN_LINK)) {
    const anchorText = match[1].trim();
    const url = match[2].trim();
    if (seen.has(url)) continue;
    seen.add(url);
    citations.push({
      url,
      title: anchorText || undefined,
      citedText: anchorText || undefined,
      ...citationMatchFields(request, url, anchorText),
    });
  }
  return citations;
}
