import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  appendOrMergeCitation,
  isGroundingRedirectUrl,
  parseHtmlLinkCitations,
  targetMatchesCitation,
} from "../src/citations.ts";

const request = {
  query: "luxury hotel tokyo",
  target: "example.com",
  matchMode: "root_domain",
  providers: ["gemini"],
};

function targetMatches(_request, candidate) {
  try {
    const candidateUrl = new URL(candidate.includes("://") ? candidate : `https://${candidate}`);
    const targetUrl = new URL("https://example.com");
    return candidateUrl.hostname.endsWith(targetUrl.hostname);
  } catch {
    return false;
  }
}

test("parseHtmlLinkCitations reads Gemini grounding redirect anchors", () => {
  const text =
    '<a href="https://vertexaisearch.cloud.google.com/grounding-api-redirect/example" target="_blank" rel="noopener">example.com</a>';
  const citations = parseHtmlLinkCitations(text, request, targetMatches);
  assert.equal(citations.length, 1);
  assert.match(citations[0].url, /grounding-api-redirect/);
  assert.equal(citations[0].citedText, "example.com");
  assert.equal(citations[0].targetMatch, true);
});

test("isGroundingRedirectUrl detects vertex redirect links", () => {
  assert.equal(
    isGroundingRedirectUrl("https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"),
    true,
  );
});

test("targetMatchesCitation uses anchor text when redirect URL does not match", () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc";
  assert.equal(targetMatchesCitation(request, redirect, targetMatches, "example.com"), true);
});

test("targetMatchesCitation prefers domain title over unrelated cited prose", () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc";
  const citedText =
    "**est** is a **1-Michelin-starred** fine-dining restaurant located on the 39th floor.";
  assert.equal(
    targetMatchesCitation(request, redirect, targetMatches, "example.com", citedText),
    true,
  );
  assert.equal(
    targetMatchesCitation(request, redirect, targetMatches, citedText, "example.com"),
    true,
  );
  assert.equal(
    targetMatchesCitation(request, redirect, targetMatches, citedText),
    false,
  );
});

test("later HTML citation promotes a duplicate structured redirect to target match", () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc";
  const citations = [
    {
      url: redirect,
      targetMatch: false,
    },
  ];
  appendOrMergeCitation(citations, {
    url: redirect,
    title: "example.com",
    citedText: "example.com",
    targetMatch: true,
  });
  assert.equal(citations.length, 1);
  assert.equal(citations[0].targetMatch, true);
  assert.equal(citations[0].citedText, "example.com");
});

test("Gemini parser scans google_search_result suggestion markup", async () => {
  const source = await readFile(new URL("../src/providers.ts", import.meta.url), "utf8");
  assert.match(
    source,
    /step\.type === "google_search_result"[\s\S]*?result\.search_suggestions[\s\S]*?parseHtmlLinkCitations/,
  );
});
