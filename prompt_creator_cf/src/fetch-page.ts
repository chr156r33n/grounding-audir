const MAX_BYTES = 1_500_000;
const MAX_REDIRECTS = 5;

export async function fetchPublicPage(value: string): Promise<string> {
  let url = normalizeUrl(value);
  for (let redirect = 0; redirect <= MAX_REDIRECTS; redirect += 1) {
    validateUrl(url);
    const response = await fetch(url, {
      headers: {
        "user-agent":
          "Mozilla/5.0 (compatible; ExactMatchPromptCreator/1.0; +https://github.com/chr156r33n/grounding-audir)",
        accept: "text/html,application/xhtml+xml",
      },
      redirect: "manual",
    });
    if (response.status >= 300 && response.status < 400) {
      const location = response.headers.get("location");
      if (!location) {
        throw new Error("The page returned a redirect without a destination.");
      }
      url = new URL(location, url);
      continue;
    }
    if (!response.ok) {
      throw new Error(`Page fetch failed with HTTP ${response.status}.`);
    }
    const type = response.headers.get("content-type") || "";
    if (!type.includes("text/html")) {
      throw new Error("The URL did not return HTML.");
    }
    const text = await response.text();
    if (text.length > MAX_BYTES) {
      throw new Error("The page exceeds the 1.5 MB limit.");
    }
    return text;
  }
  throw new Error("The page exceeded the five-redirect limit.");
}

export function validateUrl(url: URL) {
  if (!["http:", "https:"].includes(url.protocol)) {
    throw new Error("Only HTTP(S) URLs are allowed.");
  }
  const host = url.hostname.toLowerCase();
  if (
    host === "localhost" ||
    host.endsWith(".local") ||
    /^127\./.test(host) ||
    /^10\./.test(host) ||
    /^192\.168\./.test(host) ||
    /^169\.254\./.test(host) ||
    /^172\.(1[6-9]|2\d|3[01])\./.test(host) ||
    host === "::1"
  ) {
    throw new Error("Private and local URLs are not allowed.");
  }
}

function normalizeUrl(value: string): URL {
  const text = value.trim();
  if (!text) throw new Error("Enter a public page URL.");
  try {
    return new URL(text.includes("://") ? text : `https://${text}`);
  } catch {
    throw new Error("Enter a valid public HTTP(S) URL.");
  }
}
