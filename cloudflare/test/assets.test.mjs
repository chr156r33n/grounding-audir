import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("edge UI exposes run and discovery controls", async () => {
  const html = await readFile(new URL("../public/index.html", import.meta.url), "utf8");
  assert.match(html, /id="run-form"/);
  assert.match(html, /id="discover-button"/);
  assert.match(html, /Discover queries/);
  assert.match(html, /id="results"/);
  assert.match(html, /<select id="market"/);
  assert.match(html, /<select id="language"/);
  assert.match(html, /id="brand-regex"/);
  assert.match(html, /id="resolve-redirects"/);
  assert.match(html, /Torque Partnership/);
  assert.match(html, /Turning Digital/);
});

test("client avoids eager raw response rendering", async () => {
  const script = await readFile(new URL("../public/app.js", import.meta.url), "utf8");
  assert.match(script, /bindLazyRunPanels/);
  assert.match(script, /renderRunShell/);
  assert.match(script, /insertAdjacentHTML\("beforeend", `<div class="detail-body">\$\{renderRunBody/);
  assert.doesNotMatch(script, /function renderRunShell[\s\S]*?detail-body/);
});

test("styles use Torque blue palette not orange accents", async () => {
  const css = await readFile(new URL("../public/styles.css", import.meta.url), "utf8");
  assert.match(css, /--blue:/);
  assert.match(css, /--navy:/);
  assert.doesNotMatch(css, /#e8622a|orange/i);
});

test("client supports multi-phrase runs and candidate toggles", async () => {
  const script = await readFile(new URL("../public/app.js", import.meta.url), "utf8");
  assert.match(script, /function splitInputPhrases/);
  assert.match(script, /function toggleCandidateQuery/);
  assert.match(script, /selectedCandidateQueries/);
  assert.match(script, /result\.batches/);
});

test("client calls only same-origin API routes", async () => {
  const script = await readFile(new URL("../public/app.js", import.meta.url), "utf8");
  assert.match(script, /api\("\/api\/config"/);
  assert.match(script, /api\("\/api\/run"/);
  assert.match(script, /api\("\/api\/discover"/);
  assert.doesNotMatch(script, /api[_-]?key/i);
});

test("Worker config keeps provider credentials out of source vars", async () => {
  const config = await readFile(new URL("../wrangler.jsonc", import.meta.url), "utf8");
  for (const secret of [
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "GEMINI_API_KEY",
    "AZURE_ACCESS_TOKEN",
    "WEBIQ_API_KEY",
  ]) {
    assert.doesNotMatch(config, new RegExp(`"${secret}"\\s*:`));
  }
});
