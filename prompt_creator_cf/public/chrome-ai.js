export async function getChromeAiStatus() {
  if (!globalThis.LanguageModel) return "unsupported";
  try {
    return await LanguageModel.availability({ languages: ["en"] });
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

export async function createChromeAiSession({ onDownloadProgress } = {}) {
  if (!globalThis.LanguageModel) {
    throw new Error("Chrome Prompt API is not available in this browser.");
  }
  const status = await getChromeAiStatus();
  if (status === "unavailable") {
    throw new Error("Chrome on-device AI is unavailable on this device.");
  }
  return LanguageModel.create({
    monitor(monitor) {
      if (!onDownloadProgress) return;
      monitor.addEventListener("downloadprogress", (event) => {
        onDownloadProgress(event.loaded);
      });
    },
  });
}

export async function promptChromeAi(session, instruction) {
  const response = await session.prompt(instruction);
  return typeof response === "string" ? response : String(response ?? "");
}
