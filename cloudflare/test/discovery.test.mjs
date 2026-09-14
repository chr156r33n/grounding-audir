import assert from "node:assert/strict";
import test from "node:test";
import {
  discoverQueries,
  extractSnippetWindow,
  selectPageSnippets,
} from "../src/discovery.ts";

const chunks = [
  {
    kind: "p",
    score: 40,
    text:
      "The Calder House Meridian Suite includes a hand-carved walnut desk, room 417, and a private terrace overlooking the Ashbourne Observatory, with bespoke brass lighting designed by Eleanor Voss.",
  },
  {
    kind: "p",
    score: 40,
    text:
      "The rooftop telescope session begins at 9:15pm every Thursday and is limited to twelve registered guests, who receive a printed celestial map and guidance from the resident astronomer.",
  },
  {
    kind: "p",
    score: 40,
    text:
      "The archive displays three notebooks written by expedition leader Mara Bell during the 1927 Kestrel survey, alongside the original silver navigation instrument used on the journey.",
  },
];

test("selectPageSnippets returns unchanged 20–30 word passages", () => {
  const snippets = selectPageSnippets(
    {
      url: "https://example.com/calder-house",
      title: "Calder House Observatory Suites",
      description: null,
      language: "en",
      domChunks: chunks,
    },
    5,
  );

  assert.equal(snippets.length, 3);
  for (const item of snippets) {
    assert.ok(item.evidence.includes(item.query));
    const words = item.query.match(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g) || [];
    assert.ok(words.length >= 20 && words.length <= 30);
    assert.deepEqual(item.generators, ["page_snippet"]);
  }
});

test("extractSnippetWindow preserves exact source text", () => {
  const snippet = extractSnippetWindow(chunks[0].text);
  assert.ok(snippet);
  assert.ok(chunks[0].text.includes(snippet));
});

test("discoverQueries selects pasted snippets without provider configuration", async () => {
  const result = await discoverQueries({
    url: "https://example.com/calder-house",
    content: chunks.map((chunk) => chunk.text).join("\n\n"),
    count: 3,
  });

  assert.equal(result.candidates.length, 3);
  assert.deepEqual(result.generators, []);
  assert.ok(result.candidates.every((item) => item.generator === "page_snippet"));
  assert.ok(result.candidates.every((item) => !item.query.includes("retrieve a web page")));
});
