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
  target: "https://www.fourseasons.com/tokyo/est/",
  matchMode: "url_prefix",
  providers: ["gemini"],
};

function targetMatches(_request, candidate) {
  try {
    const candidateUrl = new URL(candidate.includes("://") ? candidate : `https://${candidate}`);
    const targetUrl = new URL("https://www.fourseasons.com/tokyo/est/");
    return (
      candidateUrl.origin === targetUrl.origin &&
      (candidateUrl.pathname === targetUrl.pathname ||
        candidateUrl.pathname.startsWith(`${targetUrl.pathname.replace(/\/$/, "")}/`))
    );
  } catch {
    return false;
  }
}

test("shouldResolveCitationRedirects defaults on for url_prefix", () => {
  assert.equal(shouldResolveCitationRedirects(request), true);
  assert.equal(
    shouldResolveCitationRedirects({ ...request, matchMode: "root_domain" }),
    false,
  );
  assert.equal(
    shouldResolveCitationRedirects({
      ...request,
      matchMode: "root_domain",
      resolveCitationRedirects: true,
    }),
    true,
  );
});

test("resolveGroundingRedirect returns final URL from fetch", async () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example";
  const finalUrl = "https://www.fourseasons.com/tokyo/est/";
  const fetcher = async () => ({ url: finalUrl });
  const result = await resolveGroundingRedirect(redirect, fetcher);
  assert.equal(result.resolvedUrl, finalUrl);
});

test("enrichCitationsWithRedirectResolution promotes prefix matches from resolved URL", async () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example";
  const citations = [
    {
      url: redirect,
      title: "fourseasons.com",
      targetMatch: false,
    },
  ];
  const fetcher = async () => ({
    url: "https://www.fourseasons.com/tokyo/est/",
  });
  await enrichCitationsWithRedirectResolution(citations, request, targetMatches, fetcher);
  assert.equal(citations[0].resolvedUrl, "https://www.fourseasons.com/tokyo/est/");
  assert.equal(citations[0].targetMatch, true);
  assert.equal(geminiTargetCited(citations, request), "YES");
});

test("geminiTargetCited is UNKNOWN when url_prefix redirects fail to resolve", async () => {
  const redirect = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/example";
  const citations = [
    {
      url: redirect,
      title: "fourseasons.com",
      targetMatch: false,
    },
  ];
  const fetcher = async () => {
    throw new Error("timeout");
  };
  await enrichCitationsWithRedirectResolution(citations, request, targetMatches, fetcher);
  assert.equal(citations[0].redirectResolution, "failed");
  assert.equal(geminiTargetCited(citations, request), "UNKNOWN");
});
