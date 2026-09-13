import assert from "node:assert/strict";
import test from "node:test";
import {
  buildPassageSelectionInstruction,
  chatbotLinks,
  evidenceFromContent,
  extractQuoteWindow,
  generatePrompts,
  parsePassageSelection,
  promptListText,
  selectQuotablePassages,
} from "../public/generator.js";

const HTML = `
<!doctype html>
<html>
  <head>
    <title>Harbour Hotel Hong Kong</title>
    <meta name="description" content="Luxury rooms and harbour-view dining in Central Hong Kong.">
    <script>ignoreThisInstruction()</script>
  </head>
  <body>
    <nav><p>This navigation sentence is deliberately long and must be ignored.</p></nav>
    <div class="cookie-consent"><p>Accept all cookies and review our privacy policy.</p></div>
    <section class="site-menu"><p>Home | About us | Contact us | Sign in | Subscribe</p></section>
    <main>
      <h1>Family stays beside Victoria Harbour</h1>
      <p>Guests can book connecting family suites with private balconies overlooking
      Victoria Harbour and the Central skyline, with a separate children's bedroom
      and complimentary breakfast served each morning.</p>
      <p>The rooftop pool opens from 7am until 9pm and includes a shallow children's
      area beside the garden terrace, where attendants provide towels, chilled water,
      and sun protection throughout the day.</p>
      <h2>Cantonese dining and afternoon tea</h2>
      <p>The harbour-view restaurant serves traditional Cantonese tasting menus and
      afternoon tea every Friday, Saturday, and Sunday, accompanied by a live
      string quartet from three o'clock.</p>
    </main>
  </body>
</html>
`;

test("evidenceFromContent ignores navigation and scripts", () => {
  const evidence = evidenceFromContent(HTML, "https://example.com/hotel");
  assert.equal(evidence.title, "Harbour Hotel Hong Kong");
  assert.ok(evidence.chunks.some((chunk) => chunk.text.includes("rooftop pool")));
  assert.ok(evidence.chunks.every((chunk) => !chunk.text.includes("navigation sentence")));
  assert.ok(evidence.chunks.every((chunk) => !chunk.text.includes("Accept all cookies")));
  assert.ok(evidence.chunks.every((chunk) => !chunk.text.includes("Sign in")));
});

test("selectQuotablePassages prefers specific facts", () => {
  const evidence = evidenceFromContent(HTML);
  const candidates = selectQuotablePassages(evidence, 4);
  assert.ok(candidates.length >= 3);
  assert.ok(candidates.some((item) => item.passage.includes("7am until 9pm")));
  assert.ok(
    candidates.every((item) => {
      const words = item.passage.match(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g) || [];
      return words.length >= 20 && words.length <= 30;
    }),
  );
});

test("selectQuotablePassages rejects generic pasted-page boilerplate", () => {
  const evidence = evidenceFromContent(`
Home

About us

Sign in

Subscribe to our newsletter and follow us on social media.

Accept all cookies and review our privacy policy.

The Calder House Meridian Suite includes a hand-carved walnut desk, room 417,
and a private terrace overlooking the Ashbourne Observatory, with bespoke brass
lighting designed by local artisan Eleanor Voss.

The rooftop telescope session begins at 9:15pm every Thursday and is limited
to twelve registered guests, who receive a printed celestial map and guidance
from the resident astronomer throughout the evening.
`);
  const candidates = selectQuotablePassages(evidence, 4);
  assert.ok(candidates.length >= 2);
  assert.ok(candidates.some((item) => item.passage.includes("Calder House Meridian Suite")));
  assert.ok(candidates.some((item) => item.passage.includes("9:15pm")));
  assert.ok(
    candidates.every((item) => !/cookies|newsletter|sign in/i.test(item.passage)),
  );
});

test("generatePrompts quotes exact 20–30 word page passages", async () => {
  const evidence = evidenceFromContent(HTML);
  const prompts = await generatePrompts(evidence, { count: 4 });
  assert.ok(prompts.length >= 3);
  for (const item of prompts) {
    assert.equal(
      item.prompt,
      `"${item.passage}" please retrieve a web page with this exact text`,
    );
    assert.ok(item.supportingText.includes(item.passage));
    const words = item.passage.match(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g) || [];
    assert.ok(words.length >= 20 && words.length <= 30);
  }
});

test("promptListText returns prompts without evidence or labels", () => {
  const text = promptListText([
    {
      prompt: "First generated prompt?",
      passage: "private evidence one",
      supportingText: "Supporting copy one",
    },
    {
      prompt: "Second generated prompt?",
      passage: "private evidence two",
      supportingText: "Supporting copy two",
    },
  ]);
  assert.equal(text, "First generated prompt?\n\nSecond generated prompt?");
  assert.doesNotMatch(text, /Supporting|private evidence/);
});

test("generatePrompts uses Chrome AI to rank passages without rewriting them", async () => {
  const evidence = evidenceFromContent(HTML);
  const prompts = await generatePrompts(evidence, {
    count: 3,
    session: {},
    rankPassages: async (_session, instruction) => {
      assert.match(instruction, /Do not rewrite any text/);
      return '{"ids":[2,0,1]}';
    },
  });
  assert.equal(prompts[0].generationMethod, "chrome_ai_selection");
  assert.ok(evidence.chunks.some((chunk) => chunk.text.includes(prompts[0].passage)));
});

test("extractQuoteWindow stays verbatim and within 20–30 words", () => {
  const text =
    "Guests can book connecting family suites with private balconies overlooking Victoria Harbour and the Central skyline, including breakfast, children's amenities, evening service, and flexible arrival options.";
  const passage = extractQuoteWindow(text);
  assert.ok(text.includes(passage));
  const words = passage.match(/[A-Za-z0-9][A-Za-z0-9'’&/-]*/g) || [];
  assert.ok(words.length >= 20 && words.length <= 30);
});

test("parsePassageSelection accepts valid unique candidate IDs", () => {
  assert.deepEqual(parsePassageSelection('{"ids":[2,0,2,99]}', 3), [2, 0]);
});

test("buildPassageSelectionInstruction asks for meaningful unchanged text", () => {
  const instruction = buildPassageSelectionInstruction(
    [{ passage: "A sufficiently long exact candidate passage from the supplied page content for retrieval testing and meaningful selection by the local model." }],
    "Hotel",
    1,
  );
  assert.match(instruction, /most meaningful, page-specific quotations/);
  assert.match(instruction, /Do not rewrite any text/);
});

test("chatbotLinks URL-encode the complete prompt", () => {
  const prompt = '"A quoted passage & detail" please retrieve a web page with this exact text';
  const links = chatbotLinks(prompt);
  assert.deepEqual(links.map((item) => item.id), ["chatgpt", "claude", "gemini"]);
  assert.equal(new URL(links[0].url).searchParams.get("q"), prompt);
  assert.equal(new URL(links[1].url).searchParams.get("q"), prompt);
  assert.equal(new URL(links[2].url).pathname, "/app");
  assert.equal(new URL(links[2].url).searchParams.get("q"), prompt);
});
