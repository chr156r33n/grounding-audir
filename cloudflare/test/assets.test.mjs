import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("edge UI exposes run and discovery controls", async () => {
  const html = await readFile(new URL("../public/index.html", import.meta.url), "utf8");
  assert.match(html, /id="run-form"/);
  assert.match(html, /id="discover-button"/);
  assert.match(html, /id="results"/);
  assert.match(html, /Torque Partnership/);
  assert.match(html, /Turning Digital/);
});

test("client avoids eager raw response rendering", async () => {
  const script = await readFile(new URL("../public/app.js", import.meta.url), "utf8");
  assert.match(script, /bindLazyRawResponses/);
  assert.match(script, /JSON\.stringify\(run\.rawResponse/);
  assert.doesNotMatch(script, /JSON\.stringify\(run\.rawResponse, null, 2\)\}\)<\/pre>/);
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
