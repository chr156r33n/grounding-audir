import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  appendOrMergeCitation,
  citationMatchFields,
  isGroundingRedirectUrl,
  parseHtmlLinkCitations,
} from "../src/citations.ts";
import { normalizeTargets } from "../src/targets.ts";

const request = {
  query: "luxury hotel tokyo",
  targets: [{ value: "example.com", matchMode: "root_domain", category: "owned" }],
  providers: ["gemini"],
};

test("parseHtmlLinkCitations reads Gemini grounding redirect anchors", () => {
  const text =
    '<a href="https://vertexaisearch.cloud.google.com/grounding-api-redirect/example" target="_blank" rel="noopener">example.com</a>';
  const citations = parseHtmlLinkCitations(text, request);
  assert.equal(citations.length, 1);
  assert.match(citations[0].url, /grounding-api-redirect/);
  assert.equal(citations[0].citedText, "example.com");
  assert.equal(citations[0].targetMatch, true);
  assert.deepEqual(citations[0].targetMatches, ["example.com"]);
});

test("isGroundingRedirectUrl detects vertex redirect links", () => {
  assert.equal(
    isGroundingRedirectUrl("https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc"),
    true,
  );
});

test("citationMatchFields uses anchor text when redirect URL does not match", () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc";
  const fields = citationMatchFields(request, redirect, "example.com");
  assert.equal(fields.targetMatch, true);
  assert.deepEqual(fields.targetMatches, ["example.com"]);
});

test("citationMatchFields prefers domain title over unrelated cited prose", () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc";
  const citedText =
    "**est** is a **1-Michelin-starred** fine-dining restaurant located on the 39th floor.";
  assert.equal(citationMatchFields(request, redirect, "example.com", citedText).targetMatch, true);
  assert.equal(citationMatchFields(request, redirect, citedText, "example.com").targetMatch, true);
  assert.equal(citationMatchFields(request, redirect, citedText).targetMatch, false);
});

test("later HTML citation promotes a duplicate structured redirect to target match", () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc";
  const citations = [
    {
      url: redirect,
      targetMatch: false,
      targetMatches: [],
    },
  ];
  appendOrMergeCitation(citations, {
    url: redirect,
    title: "example.com",
    citedText: "example.com",
    targetMatch: true,
    targetMatches: ["example.com"],
  });
  assert.equal(citations.length, 1);
  assert.equal(citations[0].targetMatch, true);
  assert.equal(citations[0].citedText, "example.com");
});

test("normalizeTargets deduplicates and validates categories", () => {
  const targets = normalizeTargets([
    { value: "Example.com", matchMode: "root_domain", category: "owned" },
    { value: "example.com", matchMode: "root_domain", category: "competition" },
  ]);
  assert.equal(targets.length, 1);
  assert.equal(targets[0].category, "owned");
});

test("Gemini parser scans google_search_result suggestion markup", async () => {
  const source = await readFile(new URL("../src/providers.ts", import.meta.url), "utf8");
  assert.match(
    source,
    /step\.type === "google_search_result"[\s\S]*?result\.search_suggestions[\s\S]*?parseHtmlLinkCitations/,
  );
});
