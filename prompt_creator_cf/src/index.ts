import { fetchPublicPage } from "./fetch-page.ts";

interface Env {
  ASSETS: Fetcher;
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    if (url.pathname === "/api/health") {
      return json({
        ok: true,
        service: "exact-match-prompt-creator",
        chromeAi: "client-side",
      });
    }
    if (url.pathname === "/api/fetch" && request.method === "POST") {
      try {
        const body = (await request.json()) as { url?: string };
        const html = await fetchPublicPage(String(body.url || ""));
        return json({
          html,
          bytes: html.length,
        });
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

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    },
  });
}

function message(error: unknown) {
  return error instanceof Error ? error.message : "Request failed.";
}
