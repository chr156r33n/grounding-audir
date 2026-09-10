import { discoverQueries, type DiscoveryRequest } from "./discovery.ts";
import { configuredProviders, runProvider } from "./providers.ts";
import { parseRunTargets, validateRunTargets } from "./targets.ts";
import type { Env, ProviderId, RunRequest } from "./types.ts";

const PROVIDER_IDS = new Set<ProviderId>([
  "openai_web",
  "deepseek_web",
  "gemini",
  "microsoft_web",
  "microsoft_web_iq",
]);

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/health") {
      return json({ ok: true, service: "grounding-source-observatory" });
    }
    if (url.pathname === "/api/config" && request.method === "GET") {
      return json({
        providers: configuredProviders(env),
        authRequired: !!env.OBSERVATORY_ACCESS_KEY,
        capabilities: {
          queryDiscovery: true,
          queryDiscoveryLlm: !!(env.OPENAI_API_KEY || env.GEMINI_API_KEY),
        },
        note:
          "Microsoft Bing Grounding remains available in Streamlit; the Worker supports Foundry Web Search and Web IQ.",
      });
    }
    if (
      request.method === "POST" &&
      url.pathname.startsWith("/api/") &&
      !(await authenticated(request, env))
    ) {
      return json({ error: "Invalid observatory access key." }, 401);
    }
    if (url.pathname === "/api/run" && request.method === "POST") {
      try {
        const body = (await request.json()) as Partial<RunRequest>;
        const runRequest = validateRun(body);
        const configured = new Map(
          configuredProviders(env).map((provider) => [provider.id, provider.configured]),
        );
        const unavailable = runRequest.providers.filter((id) => !configured.get(id));
        if (unavailable.length) {
          return json(
            { error: `Provider secrets are not configured: ${unavailable.join(", ")}` },
            400,
          );
        }
        const startedAt = new Date().toISOString();
        const providerRuns = await Promise.all(
          runRequest.providers.map((id) => runProvider(id, runRequest, env)),
        );
        return json({
          runId: crypto.randomUUID(),
          startedAt,
          finishedAt: new Date().toISOString(),
          request: runRequest,
          runs: providerRuns,
        });
      } catch (error) {
        return json({ error: message(error) }, 400);
      }
    }
    if (url.pathname === "/api/discover" && request.method === "POST") {
      try {
        const body = (await request.json()) as DiscoveryRequest;
        return json(await discoverQueries(body, env));
      } catch (error) {
        return json({ error: message(error) }, 400);
      }
    }
    if (url.pathname.startsWith("/api/")) {
      return json({ error: "Not found" }, 404);
    }
    return env.ASSETS.fetch(request);
  },
} satisfies ExportedHandler<Env>;

function validateRun(body: Partial<RunRequest>): RunRequest {
  const query = String(body.query || "").trim();
  if (!query) throw new Error("Query is required.");
  const targets = validateRunTargets(parseRunTargets(body));
  const providers = Array.isArray(body.providers)
    ? body.providers.filter((id): id is ProviderId => PROVIDER_IDS.has(id as ProviderId))
    : [];
  if (!providers.length) throw new Error("Select at least one configured provider.");
  return {
    query: query.slice(0, 1_000),
    targets,
    target: targets[0]?.value,
    matchMode: targets[0]?.matchMode,
    brandRegex: targets[0]?.brandRegex,
    resolveCitationRedirects:
      body.resolveCitationRedirects === undefined
        ? undefined
        : !!body.resolveCitationRedirects,
    market: String(body.market || "").trim().slice(0, 20) || undefined,
    language: String(body.language || "").trim().slice(0, 20) || undefined,
    providers,
    debug: !!body.debug,
  };
}

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
      "content-security-policy": "default-src 'none'; frame-ancestors 'none'",
    },
  });
}

function message(error: unknown) {
  return error instanceof Error ? error.message : "Unexpected request failure.";
}

async function authenticated(request: Request, env: Env) {
  if (!env.OBSERVATORY_ACCESS_KEY) return false;
  const supplied = request.headers.get("x-observatory-key") || "";
  const encoder = new TextEncoder();
  const [expectedHash, suppliedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(env.OBSERVATORY_ACCESS_KEY)),
    crypto.subtle.digest("SHA-256", encoder.encode(supplied)),
  ]);
  const expected = new Uint8Array(expectedHash);
  const actual = new Uint8Array(suppliedHash);
  let difference = 0;
  for (let index = 0; index < expected.length; index += 1) {
    difference |= expected[index] ^ actual[index];
  }
  return difference === 0;
}
