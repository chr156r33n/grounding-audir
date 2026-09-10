export interface Env {
  ASSETS: Fetcher;
  OBSERVATORY_ACCESS_KEY?: string;
  OPENAI_API_KEY?: string;
  OPENAI_MODEL: string;
  DEEPSEEK_API_KEY?: string;
  DEEPSEEK_MODEL: string;
  DEEPSEEK_BASE_URL: string;
  GEMINI_API_KEY?: string;
  GEMINI_MODEL: string;
  GEMINI_API_URL: string;
  FOUNDRY_PROJECT_ENDPOINT?: string;
  FOUNDRY_MODEL: string;
  FOUNDRY_SEARCH_CONTEXT_SIZE: string;
  AZURE_ACCESS_TOKEN?: string;
  WEBIQ_API_KEY?: string;
  WEBIQ_API_URL: string;
  WEBIQ_MAX_RESULTS: string;
}

export type ProviderId =
  | "openai_web"
  | "deepseek_web"
  | "gemini"
  | "microsoft_web"
  | "microsoft_web_iq";

export type ObservationState = "YES" | "NO" | "UNKNOWN" | "N/A";

export interface RunRequest {
  query: string;
  target: string;
  matchMode: "root_domain" | "exact_hostname" | "url_prefix";
  brandRegex?: string;
  resolveCitationRedirects?: boolean;
  market?: string;
  language?: string;
  providers: ProviderId[];
  debug?: boolean;
}

export interface Citation {
  url: string;
  title?: string;
  citedText?: string;
  targetMatch: boolean;
  resolvedUrl?: string;
  redirectResolution?: "resolved" | "failed" | "skipped";
  redirectResolutionError?: string;
}

export interface GeneratedQuery {
  query: string;
  actionType?: string;
  callStatus?: string;
}

export interface Source {
  url: string;
  title?: string;
  snippet?: string;
  position?: number;
  targetMatch: boolean;
  cited: ObservationState;
  sourceOrigin?: "open_page" | "source_list" | "action";
  callStatus?: string;
  actionType?: string;
}

export interface ProviderRun {
  providerId: ProviderId;
  providerName: string;
  model: string;
  status: "complete" | "failed";
  latencyMs: number;
  searchPerformed: ObservationState;
  targetRetrieved: ObservationState;
  targetCited: ObservationState;
  brandMentioned?: ObservationState;
  brandMatches?: string[];
  generatedQueries: GeneratedQuery[];
  sources: Source[];
  citations: Citation[];
  responseText?: string;
  error?: string;
  metadata: Record<string, unknown>;
  rawResponse?: unknown;
}
