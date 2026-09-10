import { compileBrandRegex, matchBrand } from "./brand-match.ts";
import { isGroundingRedirectUrl } from "./citations.ts";
import type {
  Citation,
  MonitorTarget,
  ObservationState,
  PropertyResult,
  ProviderRun,
  RunRequest,
  Source,
} from "./types.ts";

export const MAX_MONITOR_PROPERTIES = 5;

export const CATEGORY_LABELS: Record<PropertyResult["category"], string> = {
  owned: "Owned",
  of_interest: "Of interest",
  competition: "Competition",
};

const CATEGORY_ALIASES: Record<string, PropertyResult["category"]> = {
  owned: "owned",
  of_interest: "of_interest",
  interest: "of_interest",
  competition: "competition",
  competitor: "competition",
  competitors: "competition",
};

export function displayLabel(target: MonitorTarget) {
  return String(target.label || "").trim() || target.value;
}

export function parseTargetCategory(value: unknown): PropertyResult["category"] {
  const normalized = String(value || "owned")
    .trim()
    .toLowerCase()
    .replace(/-/g, "_")
    .replace(/\s+/g, "_");
  return CATEGORY_ALIASES[normalized] || "owned";
}

function validateTargetValue(value: string) {
  try {
    new URL(value.includes("://") ? value : `https://${value}`);
  } catch {
    throw new Error(`Property "${value}" must be a valid domain or HTTP(S) URL.`);
  }
}

export function normalizeTargets(raw: MonitorTarget[]): MonitorTarget[] {
  const normalized: MonitorTarget[] = [];
  const seen = new Set<string>();
  for (const target of raw) {
    const value = String(target.value || "").trim().slice(0, 2_000);
    if (!value) continue;
    const key = value.toLowerCase();
    if (seen.has(key)) continue;
    seen.add(key);
    validateTargetValue(value);
    const brandRegex = String(target.brandRegex || "").trim();
    compileBrandRegex(brandRegex);
    normalized.push({
      value,
      matchMode: target.matchMode || "root_domain",
      label: String(target.label || "").trim().slice(0, 120),
      category: parseTargetCategory(target.category),
      brandRegex: brandRegex || undefined,
    });
  }
  return normalized;
}

export function parseRunTargets(body: Partial<RunRequest>): MonitorTarget[] {
  if (Array.isArray(body.targets) && body.targets.length) {
    return normalizeTargets(body.targets);
  }
  const legacyValue = String(body.target || "").trim();
  if (!legacyValue) {
    throw new Error("Add at least one property to monitor.");
  }
  validateTargetValue(legacyValue);
  const brandRegex = String(body.brandRegex || "").trim();
  compileBrandRegex(brandRegex);
  const matchMode = ["root_domain", "exact_hostname", "url_prefix"].includes(String(body.matchMode))
    ? (body.matchMode as MonitorTarget["matchMode"])
    : "root_domain";
  return normalizeTargets([
    {
      value: legacyValue,
      matchMode,
      category: "owned",
      brandRegex: brandRegex || undefined,
    },
  ]);
}

export function validateRunTargets(targets: MonitorTarget[]) {
  if (!targets.length) throw new Error("Add at least one property to monitor.");
  if (targets.length > MAX_MONITOR_PROPERTIES) {
    throw new Error(`At most ${MAX_MONITOR_PROPERTIES} properties are supported.`);
  }
  return targets;
}

const MULTI_PART_SUFFIXES = new Set([
  "co.uk",
  "org.uk",
  "ac.uk",
  "com.au",
  "co.jp",
  "com.br",
  "co.nz",
  "com.mx",
]);

function rootDomain(hostname: string) {
  const normalized = hostname.toLowerCase().replace(/\.$/, "");
  const parts = normalized.split(".").filter(Boolean);
  if (parts.length <= 2) return normalized;
  const lastTwo = parts.slice(-2).join(".");
  if (MULTI_PART_SUFFIXES.has(lastTwo) && parts.length >= 3) {
    return parts.slice(-3).join(".");
  }
  return lastTwo;
}

export function targetMatchesTarget(target: MonitorTarget, candidate: string) {
  try {
    const candidateUrl = new URL(candidate.includes("://") ? candidate : `https://${candidate}`);
    const targetUrl = new URL(
      target.value.includes("://") ? target.value : `https://${target.value}`,
    );
    if (target.matchMode === "exact_hostname") {
      return candidateUrl.hostname.toLowerCase() === targetUrl.hostname.toLowerCase();
    }
    if (target.matchMode === "url_prefix") {
      return (
        candidateUrl.origin === targetUrl.origin &&
        (candidateUrl.pathname === targetUrl.pathname ||
          candidateUrl.pathname.startsWith(`${targetUrl.pathname.replace(/\/$/, "")}/`))
      );
    }
    return rootDomain(candidateUrl.hostname) === rootDomain(targetUrl.hostname);
  } catch {
    return false;
  }
}

export function matchingTargets(request: RunRequest, candidate: string) {
  return request.targets.filter((target) => targetMatchesTarget(target, candidate)).map((target) => target.value);
}

export function targetMatchFields(request: RunRequest, candidate: string) {
  const targetMatches = matchingTargets(request, candidate);
  return {
    targetMatch: targetMatches.length > 0,
    targetMatches,
  };
}

function aggregateState(
  results: PropertyResult[],
  field: keyof Pick<PropertyResult, "retrieved" | "cited" | "brandMentioned">,
) {
  if (!results.length) return "UNKNOWN" as ObservationState;
  const states = results.map((item) => item[field]);
  if (states.some((state) => state === "YES")) return "YES";
  if (states.some((state) => state === "UNKNOWN")) return "UNKNOWN";
  if (states.every((state) => state === "N/A")) return "N/A";
  return "NO";
}

export function computePropertyResults(
  run: ProviderRun,
  request: RunRequest,
  options: { retrievalComplete?: boolean; citationComplete?: boolean } = {},
): PropertyResult[] {
  const retrievalComplete = !!options.retrievalComplete;
  const citationComplete = options.citationComplete !== false;
  return request.targets.map((target) => {
    const hasFailedRedirects = run.citations.some(
      (citation) => isGroundingRedirectUrl(citation.url) && citation.redirectResolution === "failed",
    );
    const shouldResolve =
      request.resolveCitationRedirects ??
      request.targets.some((item) => item.matchMode === "url_prefix");
    const retrieved = run.sources.some((source) => source.targetMatches.includes(target.value))
      ? "YES"
      : retrievalComplete
        ? "NO"
        : "UNKNOWN";
    const cited = run.citations.some((citation) => citation.targetMatches.includes(target.value))
      ? "YES"
      : target.matchMode === "url_prefix" && shouldResolve && hasFailedRedirects
        ? "UNKNOWN"
        : citationComplete
          ? "NO"
          : "UNKNOWN";
    const brand = matchBrand(run.responseText, target.brandRegex);
    return {
      value: target.value,
      label: displayLabel(target),
      category: target.category,
      retrieved,
      cited,
      brandMentioned: brand.state,
      brandMatches: brand.matches,
    };
  });
}

export function applyPropertyResults(
  run: ProviderRun,
  request: RunRequest,
  options: { retrievalComplete?: boolean; citationComplete?: boolean } = {},
) {
  const propertyResults = computePropertyResults(run, request, options);
  run.propertyResults = propertyResults;
  run.targetRetrieved = aggregateState(propertyResults, "retrieved");
  run.targetCited = aggregateState(propertyResults, "cited");
  run.metadata.propertyResults = propertyResults;
  return run;
}

export function mergeTargetMatchFields(
  existing: Pick<Source | Citation, "targetMatch" | "targetMatches">,
  incoming: Pick<Source | Citation, "targetMatch" | "targetMatches">,
) {
  existing.targetMatches = [...new Set([...existing.targetMatches, ...incoming.targetMatches])];
  existing.targetMatch = existing.targetMatches.length > 0;
}
