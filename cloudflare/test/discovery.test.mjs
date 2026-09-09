import assert from "node:assert/strict";
import test from "node:test";
import { mergeCandidates, parseDiscoveryResponse, parseQueryCandidates } from "../src/discovery.ts";

test("parseDiscoveryResponse reads queries and distinctive terms", () => {
  const parsed = parseDiscoveryResponse(
    JSON.stringify({
      distinctive_terms: ["Four Seasons Tokyo Otemachi", "Michelin-starred dining Tokyo"],
      queries: [
        {
          query: "luxury hotel Otemachi Tokyo Imperial Palace views",
          rationale: "Matches the hotel location and positioning copy",
          evidence: "luxury hotel in central Tokyo's Otemachi district",
        },
      ],
    }),
    "openai",
  );
  assert.equal(parsed.queries.length, 1);
  assert.match(parsed.queries[0].query, /Otemachi/);
  assert.equal(parsed.distinctiveTerms[0], "Four Seasons Tokyo Otemachi");
});

test("parseQueryCandidates rejects address lookup queries", () => {
  const candidates = parseQueryCandidates(
    JSON.stringify({
      queries: [
        {
          query: "Four Seasons Hotel Tokyo at Otemachi 1-2-1 Otemachi phone number",
        },
        {
          query: "Four Seasons Tokyo Michelin restaurant est hotel",
        },
      ],
    }),
    "gemini",
  );
  assert.equal(candidates.length, 1);
  assert.match(candidates[0].query, /Michelin/);
});

test("mergeCandidates interleaves generator results without page term seeds", () => {
  const merged = mergeCandidates(
    [
      {
        providerId: "openai",
        providerName: "OpenAI",
        model: "gpt-test",
        status: "complete",
        latencyMs: 10,
        distinctiveTerms: [],
        queries: [
          { query: "Four Seasons Tokyo luxury hotel Otemachi", generators: ["openai"] },
          { query: "Michelin dining Four Seasons Tokyo", generators: ["openai"] },
        ],
      },
      {
        providerId: "gemini",
        providerName: "Gemini",
        model: "gemini-test",
        status: "complete",
        latencyMs: 12,
        distinctiveTerms: [],
        queries: [{ query: "Otemachi spa wellness hotel Tokyo", generators: ["gemini"] }],
      },
    ],
    3,
  );
  assert.deepEqual(
    merged.map((item) => item.query),
    [
      "Four Seasons Tokyo luxury hotel Otemachi",
      "Otemachi spa wellness hotel Tokyo",
      "Michelin dining Four Seasons Tokyo",
    ],
  );
});
