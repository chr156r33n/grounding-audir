import assert from "node:assert/strict";
import test from "node:test";
import {
  computePropertyResults,
  normalizeTargets,
  parseRunTargets,
  validateRunTargets,
} from "../src/targets.ts";

test("parseRunTargets accepts legacy single target payload", () => {
  const targets = parseRunTargets({
    target: "example.com",
    matchMode: "root_domain",
    brandRegex: "\\bExample\\b",
  });
  assert.equal(targets.length, 1);
  assert.equal(targets[0].value, "example.com");
  assert.equal(targets[0].category, "owned");
});

test("validateRunTargets enforces five property limit", () => {
  const targets = normalizeTargets(
    Array.from({ length: 6 }, (_, index) => ({
      value: `example${index}.com`,
      matchMode: "root_domain",
      category: "owned",
    })),
  );
  assert.throws(() => validateRunTargets(targets), /At most 5 properties/);
});

test("computePropertyResults tracks each monitored property", () => {
  const request = {
    query: "hotels",
    targets: [
      { value: "owned.example", matchMode: "root_domain", category: "owned" },
      { value: "rival.example", matchMode: "root_domain", category: "competition" },
    ],
    providers: ["openai_web"],
  };
  const run = {
    sources: [{ url: "https://owned.example", targetMatches: ["owned.example"] }],
    citations: [{ url: "https://owned.example", targetMatches: ["owned.example"] }],
    responseText: "Owned brand mentioned",
  };
  const results = computePropertyResults(run, request, {
    retrievalComplete: true,
    citationComplete: true,
  });
  assert.equal(results.length, 2);
  assert.equal(results[0].retrieved, "YES");
  assert.equal(results[0].cited, "YES");
  assert.equal(results[1].retrieved, "NO");
  assert.equal(results[1].cited, "NO");
});
