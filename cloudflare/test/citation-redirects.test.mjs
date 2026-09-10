import assert from "node:assert/strict";
import test from "node:test";
import {
  enrichCitationsWithRedirectResolution,
  geminiTargetCited,
  resolveGroundingRedirect,
  shouldResolveCitationRedirects,
} from "../src/citation-redirects.ts";

const request = {
  query: "est restaurant tokyo",
  targets: [
    {
      value: "https://www.fourseasons.com/tokyo/est/",
      matchMode: "url_prefix",
      category: "owned",
    },
  ],
  providers: ["gemini"],
};

test("shouldResolveCitationRedirects defaults on for url_prefix", () => {
  assert.equal(shouldResolveCitationRedirects(request), true);
  assert.equal(
    shouldResolveCitationRedirects({
      ...request,
      targets: [{ value: "example.com", matchMode: "root_domain", category: "owned" }],
    }),
    false,
  );
  assert.equal(
    shouldResolveCitationRedirects({
      ...request,
      targets: [{ value: "example.com", matchMode: "root_domain", category: "owned" }],
      resolveCitationRedirects: true,
    }),
    true,
  );
});

test("resolveGroundingRedirect returns final URL from fetch", async () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example";
  const finalUrl = "https://www.fourseasons.com/tokyo/est/";
  const fetcher = async (_url, init) => {
    if (init?.method === "HEAD") {
      return {
        status: 302,
        url: redirect,
        headers: { get: (key) => (key.toLowerCase() === "location" ? finalUrl : null) },
      };
    }
    throw new Error("unexpected method");
  };
  const result = await resolveGroundingRedirect(redirect, fetcher);
  assert.equal(result.resolvedUrl, finalUrl);
});

test("resolveGroundingRedirect reads embedded url query parameter", async () => {
  const redirect =
    "https://vertexaisearch.cloud.google.com/url?q=https%3A%2F%2Fwww.fourseasons.com%2Ftokyo%2Fest%2F";
  const fetcher = async () => {
    throw new Error("should not fetch when query parameter contains target");
  };
  const result = await resolveGroundingRedirect(redirect, fetcher);
  assert.equal(result.resolvedUrl, "https://www.fourseasons.com/tokyo/est/");
});

test("enrichCitationsWithRedirectResolution promotes prefix matches from resolved URL", async () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example";
  const citations = [
    {
      url: redirect,
      title: "fourseasons.com",
      targetMatch: false,
      targetMatches: [],
    },
  ];
  const fetcher = async (_url, init) => ({
    status: init?.method === "HEAD" ? 302 : 200,
    url: redirect,
    headers: {
      get: (key) =>
        key.toLowerCase() === "location" ? "https://www.fourseasons.com/tokyo/est/" : null,
    },
  });
  await enrichCitationsWithRedirectResolution(citations, request, fetcher);
  assert.equal(citations[0].resolvedUrl, "https://www.fourseasons.com/tokyo/est/");
  assert.equal(citations[0].targetMatch, true);
  assert.deepEqual(citations[0].targetMatches, ["https://www.fourseasons.com/tokyo/est/"]);
  assert.equal(geminiTargetCited(citations, request), "YES");
});

test("geminiTargetCited is UNKNOWN when url_prefix redirects fail to resolve", async () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example";
  const citations = [
    {
      url: redirect,
      title: "fourseasons.com",
      targetMatch: false,
      targetMatches: [],
    },
  ];
  const fetcher = async () => {
    throw new Error("timeout");
  };
  await enrichCitationsWithRedirectResolution(citations, request, fetcher);
  assert.equal(citations[0].redirectResolution, "failed");
  assert.equal(geminiTargetCited(citations, request), "UNKNOWN");
});
