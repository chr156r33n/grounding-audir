import assert from "node:assert/strict";
import test from "node:test";

import {
  appendOrMergeCitation,
  citationMatchFields,
  parseHtmlLinkCitations,
} from "../src/citations.ts";

const request = {
  query: "est restaurant tokyo",
  targets: [{ value: "fourseasons.com", matchMode: "root_domain", category: "owned" }],
  providers: ["gemini"],
};

function parseGeminiCitations(raw) {
  const steps = Array.isArray(raw.steps) ? raw.steps : [];
  const citations = [];
  const pushCitation = (citation) => appendOrMergeCitation(citations, citation);

  for (const step of steps) {
    if (step?.type === "google_search_result" && Array.isArray(step.result)) {
      for (const result of step.result) {
        const markup = result?.search_suggestions;
        if (typeof markup !== "string") continue;
        for (const citation of parseHtmlLinkCitations(markup, request)) {
          pushCitation(citation);
        }
      }
    }
    if (step?.type !== "model_output" || !Array.isArray(step.content)) continue;
    for (const content of step.content) {
      if (typeof content?.text !== "string" || !Array.isArray(content.annotations)) continue;
      for (const annotation of content.annotations) {
        const url = typeof annotation?.url === "string" ? annotation.url : undefined;
        if (!url) continue;
        const title = typeof annotation.title === "string" ? annotation.title : undefined;
        const citedText =
          typeof annotation.start_index === "number" && typeof annotation.end_index === "number"
            ? content.text.slice(annotation.start_index, annotation.end_index)
            : undefined;
        pushCitation({
          url,
          title,
          citedText,
          ...citationMatchFields(request, url, title, citedText),
        });
      }
    }
  }
  return citations;
}

test("Gemini structured redirect citations match target domain from title", () => {
  const raw = {
    steps: [
      {
        type: "google_search_result",
        result: [
          {
            search_suggestions:
              '<a class="chip" href="https://www.google.com/search?q=test">query chip</a>',
          },
        ],
      },
      {
        type: "model_output",
        content: [
          {
            type: "text",
            text: "**est** is a **1-Michelin-starred** fine-dining restaurant located on the 39th floor of the **Four Seasons Hotel Tokyo at Otemachi** in Tokyo, Japan.",
            annotations: [
              {
                type: "url_citation",
                start_index: 0,
                end_index: 148,
                url: "https://vertexaisearch.cloud.google.com/grounding-api-redirect/fourseasons",
                title: "fourseasons.com",
              },
              {
                type: "url_citation",
                start_index: 0,
                end_index: 148,
                url: "https://vertexaisearch.cloud.google.com/grounding-api-redirect/michelin",
                title: "michelin.com",
              },
            ],
          },
        ],
      },
    ],
  };

  const citations = parseGeminiCitations(raw);
  assert.ok(citations.length >= 2);
  const fourSeasons = citations.find((citation) => citation.title === "fourseasons.com");
  assert.ok(fourSeasons);
  assert.equal(fourSeasons.targetMatch, true);
  assert.deepEqual(fourSeasons.targetMatches, ["fourseasons.com"]);
  assert.equal(
    citations.some((citation) => citation.title === "michelin.com" && citation.targetMatch),
    false,
  );
});
