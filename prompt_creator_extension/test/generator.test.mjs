import assert from "node:assert/strict";
import test from "node:test";
import {
  chatbotLinks,
  extractQuoteWindow,
  generatePrompts,
  parseSelection,
  selectQuotablePassages,
} from "../generator.js";

const evidence = {
  source: "https://example.com/calder-house",
  title: "Calder House Observatory Suites",
  chunks: [
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
  ],
};

test("selectQuotablePassages returns unchanged 20–30 word passages", () => {
  const passages = selectQuotablePassages(evidence, 5);
  assert.ok(passages.length >= 3);
  for (const item of passages) {
    assert.ok(item.supportingText.includes(item.passage));
    const words = item.passage.match(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g) || [];
    assert.ok(words.length >= 20 && words.length <= 30);
  }
});

test("generatePrompts uses exact retrieval wording", async () => {
  const prompts = await generatePrompts(evidence, { count: 3 });
  assert.equal(prompts.length, 3);
  assert.equal(
    prompts[0].prompt,
    `"${prompts[0].passage}" please retrieve a web page with this exact text`,
  );
});

test("Chrome selection changes ordering but never passage text", async () => {
  const pool = selectQuotablePassages(evidence, 12);
  const prompts = await generatePrompts(evidence, {
    count: 3,
    session: {},
    rankPassages: async () => '{"ids":[2,0,1]}',
  });
  assert.equal(prompts[0].passage, pool[2].passage);
  assert.equal(prompts[0].generationMethod, "chrome_ai_selection");
});

test("extractQuoteWindow preserves exact text", () => {
  const source = evidence.chunks[0].text;
  const passage = extractQuoteWindow(source);
  assert.ok(source.includes(passage));
});

test("parseSelection rejects invalid and duplicate IDs", () => {
  assert.deepEqual(parseSelection('{"ids":[2,0,2,50]}', 3), [2, 0]);
});

test("chatbotLinks encode complete prompts", () => {
  const prompt = '"Calder House & Observatory" please retrieve a web page with this exact text';
  const links = chatbotLinks(prompt);
  assert.equal(new URL(links[0].url).searchParams.get("q"), prompt);
  assert.equal(new URL(links[1].url).searchParams.get("q"), prompt);
  assert.equal(new URL(links[2].url).pathname, "/app");
  assert.equal(new URL(links[2].url).searchParams.get("q"), prompt);
});
