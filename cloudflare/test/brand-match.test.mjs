import assert from "node:assert/strict";
import test from "node:test";
import { compileBrandRegex, matchBrand } from "../src/brand-match.ts";

test("brand regex matches generated response case-insensitively", () => {
  const result = matchBrand(
    "The FOUR SEASONS hotel overlooks the Imperial Palace.",
    String.raw`\bFour Seasons\b`,
  );
  assert.equal(result.state, "YES");
  assert.deepEqual(result.matches, ["FOUR SEASONS"]);
});

test("brand regex reports NO for a present response without a match", () => {
  assert.deepEqual(matchBrand("A different hotel is recommended.", "Four Seasons"), {
    state: "NO",
    matches: [],
  });
});

test("brand regex reports UNKNOWN when generated response is absent", () => {
  assert.deepEqual(matchBrand(undefined, "Four Seasons"), {
    state: "UNKNOWN",
    matches: [],
  });
});

test("brand regex is validated before a run", () => {
  assert.throws(() => compileBrandRegex("("), /Brand regex is invalid/);
});
