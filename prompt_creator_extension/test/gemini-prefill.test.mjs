import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

test("manifest limits persistent page access to Gemini", async () => {
  const manifest = JSON.parse(
    await readFile(new URL("../manifest.json", import.meta.url), "utf8"),
  );
  assert.deepEqual(manifest.host_permissions, ["https://gemini.google.com/*"]);
  assert.deepEqual(
    manifest.content_scripts[0].matches,
    ["https://gemini.google.com/*"],
  );
  assert.deepEqual(manifest.content_scripts[0].js, ["gemini-prefill.js"]);
});

test("Gemini prefill reads q and prompt parameters safely", async () => {
  const source = await readFile(
    new URL("../gemini-prefill.js", import.meta.url),
    "utf8",
  );
  const context = { URL };
  context.globalThis = context;
  vm.runInNewContext(source, context);

  const helper = context.GeminiPromptPrefill;
  assert.equal(
    helper.promptFromUrl("https://gemini.google.com/app?q=Exact%20quoted%20text"),
    "Exact quoted text",
  );
  assert.equal(
    helper.promptFromUrl("https://gemini.google.com/app?prompt=Second%20format"),
    "Second format",
  );
  assert.equal(helper.promptFromUrl("https://gemini.google.com/app"), null);
});

test("Gemini integration does not auto-submit the composer", async () => {
  const source = await readFile(
    new URL("../gemini-prefill.js", import.meta.url),
    "utf8",
  );
  assert.doesNotMatch(source, /\.click\s*\(/);
  assert.doesNotMatch(source, /submit\s*\(/);
  assert.match(source, /replaceState/);
});
