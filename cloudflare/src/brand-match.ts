import type { ObservationState } from "./types.ts";

const MAX_PATTERN_LENGTH = 200;
const MAX_RESPONSE_LENGTH = 200_000;
const MAX_MATCHES = 10;

export interface BrandMatchResult {
  state: ObservationState;
  matches: string[];
}

export function compileBrandRegex(pattern?: string) {
  const value = String(pattern || "").trim();
  if (!value) return undefined;
  if (value.length > MAX_PATTERN_LENGTH) {
    throw new Error(`Brand regex must be ${MAX_PATTERN_LENGTH} characters or fewer.`);
  }
  try {
    return new RegExp(value, "giu");
  } catch (error) {
    throw new Error(
      `Brand regex is invalid: ${error instanceof Error ? error.message : "invalid expression"}`,
    );
  }
}

export function matchBrand(
  responseText: string | undefined,
  pattern: string | undefined,
): BrandMatchResult {
  const regex = compileBrandRegex(pattern);
  if (!regex) return { state: "N/A", matches: [] };
  if (!responseText) return { state: "UNKNOWN", matches: [] };

  const matches: string[] = [];
  const seen = new Set<string>();
  for (const match of responseText.slice(0, MAX_RESPONSE_LENGTH).matchAll(regex)) {
    const value = match[0];
    const key = value.toLocaleLowerCase();
    if (value && !seen.has(key)) {
      seen.add(key);
      matches.push(value);
    }
    if (matches.length >= MAX_MATCHES) break;
  }
  return { state: matches.length ? "YES" : "NO", matches };
}
