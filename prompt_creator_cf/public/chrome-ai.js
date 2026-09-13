const LANGUAGE_OPTIONS = {
  expectedInputs: [{ type: "text", languages: ["en"] }],
  expectedOutputs: [{ type: "text", languages: ["en"] }],
};

export async function getChromeAiStatus() {
  if (!globalThis.LanguageModel) return "unsupported";
  try {
    return await LanguageModel.availability(LANGUAGE_OPTIONS);
  } catch {
    return "unsupported";
  }
}

export function chromeAiLabel(status) {
  switch (status) {
    case "available":
      return "Chrome AI ready";
    case "downloadable":
      return "Chrome AI available after download";
    case "downloading":
      return "Chrome AI downloading";
    case "unsupported":
      return "Chrome AI unavailable — heuristic selection";
    default:
      return "Chrome AI unavailable on this device";
  }
}

export async function createChromeAiSession({
  onDownloadProgress,
  timeoutMs = 15_000,
} = {}) {
  if (!globalThis.LanguageModel) {
    throw new Error("Chrome Prompt API is not available in this browser.");
  }
  const status = await getChromeAiStatus();
  if (status === "unavailable") {
    throw new Error("Chrome on-device AI is unavailable on this device.");
  }
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await LanguageModel.create({
      ...LANGUAGE_OPTIONS,
      signal: controller.signal,
      monitor(monitor) {
        if (!onDownloadProgress) return;
        monitor.addEventListener("downloadprogress", (event) => {
          onDownloadProgress(event.loaded);
        });
      },
    });
  } finally {
    clearTimeout(timeout);
  }
}

export async function promptChromeAi(session, instruction, timeoutMs = 12_000) {
  let timeout;
  try {
    const response = await Promise.race([
      session.prompt(instruction),
      new Promise((_, reject) => {
        timeout = setTimeout(
          () => reject(new Error("Chrome AI selection timed out.")),
          timeoutMs,
        );
      }),
    ]);
    return typeof response === "string" ? response : String(response ?? "");
  } finally {
    clearTimeout(timeout);
  }
}
