import {
  chromeAiLabel,
  createChromeAiSession,
  getChromeAiStatus,
  promptChromeAi,
} from "./chrome-ai.js";
import { evidenceFromContent, generatePrompts } from "./generator.js";

const $ = (selector) => document.querySelector(selector);
let lastResults = null;

async function api(path, options) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

function setStatus(text, tone = "neutral") {
  const badge = $("#model-status");
  badge.textContent = text;
  badge.dataset.tone = tone;
}

async function refreshChromeAiStatus() {
  const status = await getChromeAiStatus();
  const tone =
    status === "available"
      ? "ready"
      : status === "downloadable" || status === "downloading"
        ? "pending"
        : "muted";
  setStatus(chromeAiLabel(status), tone);
  return status;
}

function toggleInputMode() {
  const mode = document.querySelector('input[name="input-mode"]:checked')?.value || "paste";
  $("#page-content").disabled = mode !== "paste";
  $("#source-url").required = mode === "url";
}

async function loadEvidence(formData) {
  const mode = formData.get("input-mode");
  if (mode === "url") {
    const url = String(formData.get("source-url") || "").trim();
    if (!url) throw new Error("Enter a public page URL.");
    const payload = await api("/api/fetch", {
      method: "POST",
      body: JSON.stringify({ url }),
    });
    return evidenceFromContent(payload.html, url);
  }
  const content = String(formData.get("page-content") || "").trim();
  if (!content) throw new Error("Paste page HTML or visible page copy.");
  const source = String(formData.get("source-url") || "").trim();
  return evidenceFromContent(content, source);
}

function renderResults(result) {
  const list = $("#prompt-list");
  list.innerHTML = result.prompts
    .map(
      (item, index) => `
        <article class="prompt-card">
          <div class="prompt-card-head">
            <span class="prompt-index">${index + 1}</span>
            <span class="method-pill">${escapeHtml(item.generationMethod.replace(/_/g, " "))}</span>
          </div>
          <pre class="prompt-text">${escapeHtml(item.prompt)}</pre>
          <details>
            <summary>Why this prompt is grounded</summary>
            <dl>
              <dt>Exact phrase</dt>
              <dd>${escapeHtml(item.exactPhrase)}</dd>
              <dt>Supporting copy</dt>
              <dd>${escapeHtml(item.sourceExcerpt)}</dd>
            </dl>
          </details>
          <button type="button" class="copy-button" data-prompt="${encodeURIComponent(item.prompt)}">
            Copy prompt
          </button>
        </article>`,
    )
    .join("");

  list.querySelectorAll(".copy-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const text = decodeURIComponent(button.dataset.prompt);
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
      setTimeout(() => {
        button.textContent = "Copy prompt";
      }, 1200);
    });
  });

  $("#results-meta").textContent =
    `${result.exactMatch ? "Exact-match" : "Natural-language"} mode · ` +
    `${result.evidence.title || result.evidence.source} · ` +
    `${result.prompts.length} prompts · ` +
    `${result.chromeAiUsed ? "Chrome AI used where available" : "Templates only"}`;

  const textExport = result.prompts.map((item, index) => `${index + 1}. ${item.prompt}`).join("\n\n");
  $("#download-txt").onclick = () => downloadBlob(textExport, "exact-match-prompts.txt", "text/plain");
  $("#download-json").onclick = () =>
    downloadBlob(
      JSON.stringify(
        {
          source: result.evidence.source,
          title: result.evidence.title,
          exactMatch: result.exactMatch,
          prompts: result.prompts,
        },
        null,
        2,
      ),
      "exact-match-prompts.json",
      "application/json",
    );

  $("#results").hidden = false;
  $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
}

function downloadBlob(content, filename, type) {
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(new Blob([content], { type }));
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(anchor.href);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

$("#prompt-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#generate-button");
  const error = $("#form-error");
  error.textContent = "";
  button.disabled = true;
  button.textContent = "Creating prompts…";

  try {
    const formData = new FormData(event.currentTarget);
    const evidence = await loadEvidence(formData);
    const count = Number(formData.get("count") || 5);
    const exactMatch = formData.get("exact-match") === "on";

    let session = null;
    let chromeAiUsed = false;
    const status = await getChromeAiStatus();
    if (status !== "unsupported" && status !== "unavailable") {
      setStatus("Preparing Chrome on-device model…", "pending");
      session = await createChromeAiSession({
        onDownloadProgress: (loaded) => {
          setStatus(`Downloading Chrome AI model… ${Math.round(loaded * 100)}%`, "pending");
        },
      });
      setStatus("Chrome AI ready", "ready");
      chromeAiUsed = true;
    }

    const prompts = await generatePrompts(evidence, {
      count,
      exactMatch,
      session,
      generateQuestion: promptChromeAi,
      onProgress: ({ index, total }) => {
        button.textContent = `Creating prompts… ${index + 1}/${total}`;
      },
    });

    lastResults = { evidence, prompts, exactMatch, chromeAiUsed };
    renderResults(lastResults);
  } catch (caught) {
    error.textContent = caught.message;
    $("#results").hidden = true;
  } finally {
    button.disabled = false;
    button.textContent = "Create prompts";
    await refreshChromeAiStatus();
  }
});

document.querySelectorAll('input[name="input-mode"]').forEach((input) => {
  input.addEventListener("change", toggleInputMode);
});

toggleInputMode();
refreshChromeAiStatus();
