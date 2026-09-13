import {
  chromeAiLabel,
  createChromeAiSession,
  getChromeAiStatus,
  promptChromeAi,
} from "./chrome-ai.js";
import {
  chatbotLinks,
  evidenceFromContent,
  generatePrompts,
  promptListText,
} from "./generator.js";

const $ = (selector) => document.querySelector(selector);
let lastResults = null;

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

function loadEvidence(formData) {
  const content = String(formData.get("page-content") || "").trim();
  if (!content) throw new Error("Paste page HTML or visible page copy.");
  return evidenceFromContent(content);
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
          <div class="chatbot-links">
            ${chatbotLinks(item.prompt)
              .map(
                (link) => `
                  <a href="${escapeHtml(link.url)}" target="_blank" rel="noopener noreferrer">
                    ${escapeHtml(link.name)}
                  </a>`,
              )
              .join("")}
          </div>
          <details>
            <summary>Why this passage was selected</summary>
            <dl>
              <dt>Quoted passage</dt>
              <dd>${escapeHtml(item.passage)}</dd>
              <dt>Supporting page text</dt>
              <dd>${escapeHtml(item.supportingText)}</dd>
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
    `${result.evidence.title || result.evidence.source} · ` +
    `${result.prompts.length} prompts · ` +
    `${result.chromeAiUsed ? "Chrome AI selection" : "Heuristic selection"}`;

  const plainPromptList = promptListText(result.prompts);
  const copyAllButton = $("#copy-all");
  copyAllButton.onclick = async () => {
    await navigator.clipboard.writeText(plainPromptList);
    copyAllButton.textContent = "All prompts copied";
    setTimeout(() => {
      copyAllButton.textContent = "Copy all prompts";
    }, 1500);
  };
  const textExport = result.prompts
    .map((item, index) => `${index + 1}. ${item.prompt}`)
    .join("\n\n");
  $("#download-txt").onclick = () => downloadBlob(textExport, "exact-match-prompts.txt", "text/plain");
  $("#download-json").onclick = () =>
    downloadBlob(
      JSON.stringify(
        {
          source: result.evidence.source,
          title: result.evidence.title,
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
    const evidence = loadEvidence(formData);
    const count = Number(formData.get("count") || 5);

    let session = null;
    let chromeAiUsed = false;
    const status = await getChromeAiStatus();
    if (status !== "unsupported" && status !== "unavailable") {
      try {
        setStatus("Preparing Chrome on-device model…", "pending");
        session = await createChromeAiSession({
          onDownloadProgress: (loaded) => {
            setStatus(
              `Downloading Chrome AI model… ${Math.round(loaded * 100)}%`,
              "pending",
            );
          },
        });
        setStatus("Chrome AI ready", "ready");
        chromeAiUsed = true;
      } catch {
        session = null;
        setStatus("Chrome AI timed out — using heuristic selection", "muted");
      }
    }

    const prompts = await generatePrompts(evidence, {
      count,
      session,
      rankPassages: promptChromeAi,
      onProgress: ({ total }) => {
        button.textContent =
          total === 1 ? "Selecting the best passages…" : "Creating prompts…";
      },
    });
    chromeAiUsed = prompts.some(
      (item) => item.generationMethod === "chrome_ai_selection",
    );

    lastResults = { evidence, prompts, chromeAiUsed };
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

refreshChromeAiStatus();
