import assert from "node:assert/strict";
import test from "node:test";
import { mergeCandidates, parseQueryCandidates } from "../src/discovery.ts";

test("parseQueryCandidates reads JSON query objects", () => {
  const candidates = parseQueryCandidates(
    JSON.stringify({
      queries: [
        {
          query: "Four Seasons Hong Kong luxury hotel",
          rationale: "Branded navigational query",
          evidence: "Four Seasons Hong Kong",
        },
      ],
    }),
    "openai",
  );
  assert.equal(candidates.length, 1);
  assert.equal(candidates[0].query, "Four Seasons Hong Kong luxury hotel");
  assert.equal(candidates[0].generators[0], "openai");
});

test("mergeCandidates interleaves generator and page term seeds", () => {
  const merged = mergeCandidates(
    [
      {
        providerId: "openai",
        providerName: "OpenAI",
        model: "gpt-test",
        status: "complete",
        latencyMs: 10,
        queries: [
          {
            query: "Harbour hotel Hong Kong",
            generators: ["openai"],
          },
          {
            query: "Rooftop pool hotels Hong Kong",
            generators: ["openai"],
          },
        ],
      },
    ],
    3,
    [
      {
        query: "Harbour hotel Hong Kong",
        rationale: "seed",
        generators: ["page_terms"],
      },
      {
        query: "Family suites Central",
        generators: ["page_terms"],
      },
    ],
  );
  assert.equal(merged.length, 3);
  assert.deepEqual(merged[0].generators, ["page_terms", "openai"]);
  assert.equal(merged[1].query, "Family suites Central");
});
