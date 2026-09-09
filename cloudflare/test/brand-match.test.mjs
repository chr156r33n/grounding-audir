import assert from "node:assert/strict";
import test from "node:test";
import { compileBrandRegex, matchBrand } from "../src/brand-match.ts";

test("brand regex matches generated response case-insensitively", () => {
  const result = matchBrand(
    "The EXAMPLE BRAND hotel overlooks the city.",
    String.raw`\bExample Brand\b`,
  );
  assert.equal(result.state, "YES");
  assert.deepEqual(result.matches, ["EXAMPLE BRAND"]);
});

test("brand regex reports NO for a present response without a match", () => {
  assert.deepEqual(matchBrand("A different hotel is recommended.", "Example Brand"), {
    state: "NO",
    matches: [],
  });
});

test("brand regex reports UNKNOWN when generated response is absent", () => {
  assert.deepEqual(matchBrand(undefined, "Example Brand"), {
    state: "UNKNOWN",
    matches: [],
  });
});

test("brand regex is validated before a run", () => {
  assert.throws(() => compileBrandRegex("("), /Brand regex is invalid/);
});
