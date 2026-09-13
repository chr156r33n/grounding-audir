import assert from "node:assert/strict";
import test from "node:test";
import {
  buildGenerationInstruction,
  cleanQuestion,
  evidenceFromContent,
  extractExactPhrase,
  generatePrompts,
  questionIsGrounded,
  selectAnchorPassages,
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
      Victoria Harbour and the Central skyline.</p>
      <p>The rooftop pool opens from 7am until 9pm and includes a shallow children's
      area beside the garden terrace.</p>
      <h2>Cantonese dining and afternoon tea</h2>
      <p>The harbour-view restaurant serves traditional Cantonese tasting menus and
      afternoon tea every Friday, Saturday, and Sunday.</p>
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

test("selectAnchorPassages prefers specific facts", () => {
  const evidence = evidenceFromContent(HTML);
  const anchors = selectAnchorPassages(evidence, 4);
  assert.ok(anchors.length >= 3);
  assert.ok(anchors.some((anchor) => anchor.includes("7am until 9pm")));
});

test("selectAnchorPassages rejects generic pasted-page boilerplate", () => {
  const evidence = evidenceFromContent(`
Home

About us

Sign in

Subscribe to our newsletter and follow us on social media.

Accept all cookies and review our privacy policy.

The Calder House Meridian Suite includes a hand-carved walnut desk, room 417,
and a private terrace overlooking the Ashbourne Observatory.

The rooftop telescope session begins at 9:15pm every Thursday and is limited
to twelve registered guests.
`);
  const anchors = selectAnchorPassages(evidence, 4);
  assert.ok(anchors.length >= 2);
  assert.ok(anchors.some((anchor) => anchor.includes("Calder House Meridian Suite")));
  assert.ok(anchors.some((anchor) => anchor.includes("9:15pm")));
  assert.ok(anchors.every((anchor) => !/cookies|newsletter|sign in/i.test(anchor)));
});

test("generatePrompts builds exact-match prompts from templates", async () => {
  const evidence = evidenceFromContent(HTML);
  const prompts = await generatePrompts(evidence, { count: 4, exactMatch: true });
  assert.ok(prompts.length >= 3);
  assert.ok(
    prompts.every((item) => item.prompt.includes(`exact phrase "${item.exactPhrase}"`)),
  );
});

test("generatePrompts uses chrome session when provided", async () => {
  const evidence = evidenceFromContent(HTML);
  const prompts = await generatePrompts(evidence, {
    count: 3,
    exactMatch: false,
    session: {},
    generateQuestion: async (_session, instruction) => {
      assert.match(instruction, /Return only the question/);
      const anchor = instruction.match(/Text: (.+)\nQuestion:/)?.[1] || "";
      const phrase = extractExactPhrase(anchor, 4);
      return `What information is available about ${phrase}?`;
    },
  });
  assert.equal(prompts[0].generationMethod, "chrome_ai");
  assert.ok(prompts[0].prompt.endsWith("?"));
});

test("extractExactPhrase stays verbatim", () => {
  const text =
    "Guests can book connecting family suites with private balconies overlooking Victoria Harbour.";
  const phrase = extractExactPhrase(text);
  assert.ok(text.includes(phrase));
  assert.ok(phrase.split(/\s+/).length <= 10);
});

test("cleanQuestion normalizes model output", () => {
  assert.equal(cleanQuestion('Question: "What time does the pool open?"'), "What time does the pool open?");
});

test("questionIsGrounded rejects unrelated output", () => {
  assert.equal(questionIsGrounded("Tell me a joke.", "The rooftop pool opens from 7am until 9pm."), false);
  assert.equal(
    questionIsGrounded("When does the rooftop pool open?", "The rooftop pool opens from 7am until 9pm."),
    true,
  );
});

test("buildGenerationInstruction includes anchor text", () => {
  const instruction = buildGenerationInstruction("The rooftop pool opens from 7am until 9pm.", "Hotel");
  assert.match(instruction, /Page title: Hotel/);
  assert.match(instruction, /rooftop pool/);
});
