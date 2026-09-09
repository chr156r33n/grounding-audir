import assert from "node:assert/strict";
import test from "node:test";
import {
  isGroundingRedirectUrl,
  parseHtmlLinkCitations,
  targetMatchesCitation,
} from "../src/citations.ts";

const request = {
  query: "luxury hotel tokyo",
  target: "fourseasons.com",
  matchMode: "root_domain",
  providers: ["gemini"],
};

function targetMatches(_request, candidate) {
  try {
    const candidateUrl = new URL(candidate.includes("://") ? candidate : `https://${candidate}`);
    const targetUrl = new URL("https://fourseasons.com");
    return candidateUrl.hostname.endsWith("fourseasons.com");
  } catch {
    return false;
  }
}

test("parseHtmlLinkCitations reads Gemini grounding redirect anchors", () => {
  const text =
    '<a href="https://vertexaisearch.cloud.google.com/grounding-api-redirect/example" target="_blank" rel="noopener">fourseasons.com</a>';
  const citations = parseHtmlLinkCitations(text, request, targetMatches);
  assert.equal(citations.length, 1);
  assert.match(citations[0].url, /grounding-api-redirect/);
  assert.equal(citations[0].citedText, "fourseasons.com");
  assert.equal(citations[0].targetMatch, "YES");
});

test("isGroundingRedirectUrl detects vertex redirect links", () => {
  assert.equal(
    isGroundingRedirectUrl("https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"),
    true,
  );
});

test("targetMatchesCitation uses anchor text when redirect URL does not match", () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc";
  assert.equal(targetMatchesCitation(request, redirect, targetMatches, "fourseasons.com"), true);
});
