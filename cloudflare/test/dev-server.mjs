import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { extname } from "node:path";
import worker from "../src/index.ts";

const root = new URL("../public/", import.meta.url);
const contentTypes = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
};

const env = {
  OBSERVATORY_ACCESS_KEY: "local",
  OPENAI_MODEL: "gpt-5.5",
  DEEPSEEK_MODEL: "deepseek-v4-flash",
  DEEPSEEK_BASE_URL: "https://api.deepseek.com",
  GEMINI_MODEL: "gemini-3.6-flash",
  GEMINI_API_URL: "https://generativelanguage.googleapis.com/v1beta/interactions",
  FOUNDRY_MODEL: "gpt-5-mini",
  FOUNDRY_SEARCH_CONTEXT_SIZE: "medium",
  WEBIQ_API_URL: "https://api.microsoft.ai/v3/search/web",
  WEBIQ_MAX_RESULTS: "10",
  ASSETS: {
    async fetch(request) {
      const pathname = new URL(request.url).pathname;
      const relative = pathname === "/" ? "index.html" : pathname.replace(/^\/+/, "");
      try {
        const body = await readFile(new URL(relative, root));
        return new Response(body, {
          headers: { "content-type": contentTypes[extname(relative)] || "application/octet-stream" },
        });
      } catch {
        return new Response("Not found", { status: 404 });
      }
    },
  },
};

createServer(async (incoming, outgoing) => {
  const chunks = [];
  for await (const chunk of incoming) chunks.push(chunk);
  const request = new Request(`http://127.0.0.1:8787${incoming.url}`, {
    method: incoming.method,
    headers: incoming.headers,
    body: ["GET", "HEAD"].includes(incoming.method || "GET")
      ? undefined
      : Buffer.concat(chunks),
  });
  const response = await worker.fetch(request, env);
  outgoing.writeHead(response.status, Object.fromEntries(response.headers));
  outgoing.end(Buffer.from(await response.arrayBuffer()));
}).listen(8787, "127.0.0.1", () => {
  console.log("Local Worker preview: http://127.0.0.1:8787");
});
