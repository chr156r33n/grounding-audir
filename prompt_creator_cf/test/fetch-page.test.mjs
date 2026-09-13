import assert from "node:assert/strict";
import test from "node:test";
import { validateUrl } from "../src/fetch-page.ts";

test("validateUrl rejects localhost", () => {
  assert.throws(() => validateUrl(new URL("https://localhost/private")), /not allowed/);
});

test("validateUrl accepts public hostnames", () => {
  assert.doesNotThrow(() => validateUrl(new URL("https://example.com/page")));
});
