import type { Citation, RunRequest } from "./types.ts";

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

export function targetMatchesCitation(
  request: RunRequest,
  url: string,
  targetMatches: (request: RunRequest, candidate: string) => boolean,
  ...hints: Array<string | undefined>
) {
  if (targetMatches(request, url)) return true;
  if (!isGroundingRedirectUrl(url)) return false;
  for (const hint of hints) {
    for (const candidate of citationTargetHints(hint)) {
      if (targetMatches(request, candidate)) return true;
    }
  }
  return false;
}

export function appendOrMergeCitation(citations: Citation[], incoming: Citation) {
  const existing = citations.find((citation) => citation.url === incoming.url);
  if (!existing) {
    citations.push(incoming);
    return;
  }
  existing.title ||= incoming.title;
  existing.citedText ||= incoming.citedText;
  existing.targetMatch = existing.targetMatch || incoming.targetMatch;
}

export function parseHtmlLinkCitations(
  text: string,
  request: RunRequest,
  targetMatches: (request: RunRequest, candidate: string) => boolean,
): Citation[] {
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
      targetMatch: targetMatchesCitation(request, url, targetMatches, anchorText),
    });
  }
  return citations;
}

export function parseMarkdownLinkCitations(
  text: string,
  request: RunRequest,
  targetMatches: (request: RunRequest, candidate: string) => boolean,
): Citation[] {
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
      targetMatch: targetMatchesCitation(request, url, targetMatches, anchorText),
    });
  }
  return citations;
}
