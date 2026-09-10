const $ = (selector) => document.querySelector(selector);
let lastResult = null;
let lastRuns = [];
let lastDiscoveryCandidates = [];
let selectedCandidateQueries = new Set();

function splitInputPhrases(value) {
  return String(value || "")
    .split(/[\n,]+/)
    .map((part) => part.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .filter((phrase, index, items) => items.findIndex((item) => item.toLowerCase() === phrase.toLowerCase()) === index);
}

function syncQueryFieldFromSelection() {
  const ordered = lastDiscoveryCandidates
    .map((candidate) => candidate.query)
    .filter((query) => selectedCandidateQueries.has(query));
  $("#query").value = ordered.join("\n");
}

function updateCandidateButtonStates() {
  document.querySelectorAll(".candidate button[data-query]").forEach((button) => {
    const query = decodeURIComponent(button.dataset.query);
    const selected = selectedCandidateQueries.has(query);
    button.classList.toggle("is-selected", selected);
    button.textContent = selected ? "Selected" : "Use";
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  });
}

function syncSelectionFromQueryField() {
  const lines = new Set(splitInputPhrases($("#query").value));
  selectedCandidateQueries = new Set(
    lastDiscoveryCandidates.map((candidate) => candidate.query).filter((query) => lines.has(query)),
  );
  updateCandidateButtonStates();
}

function toggleCandidateQuery(encodedQuery) {
  const query = decodeURIComponent(encodedQuery);
  if (selectedCandidateQueries.has(query)) {
    selectedCandidateQueries.delete(query);
  } else {
    selectedCandidateQueries.add(query);
  }
  syncQueryFieldFromSelection();
  updateCandidateButtonStates();
  $("#query").focus();
}

async function api(path, options) {
  const response = await fetch(path, {
    headers: {
      "content-type": "application/json",
      ...(options?.method === "POST"
        ? { "x-observatory-key": $("#access-key")?.value || "" }
        : {}),
    },
    ...options,
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || `Request failed (${response.status})`);
  return payload;
}

async function loadConfig() {
  try {
    const config = await api("/api/config");
    $("#providers").innerHTML = config.providers
      .map(
        (provider) => `
          <label class="provider ${provider.configured ? "" : "unavailable"}">
            <input type="checkbox" name="provider" value="${provider.id}"
              ${provider.configured ? "checked" : "disabled"} />
            <span>${escapeHtml(provider.name)}
              <small>${provider.configured ? escapeHtml(provider.model) : "secret not configured"}</small>
            </span>
          </label>`,
      )
      .join("");
  } catch (error) {
    $("#providers").innerHTML = `<p class="error">${escapeHtml(error.message)}</p>`;
  }
}

$("#run-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#run-button");
  const error = $("#form-error");
  error.textContent = "";
  button.disabled = true;
  const phrases = splitInputPhrases($("#query").value);
  if (!phrases.length) {
    error.textContent = "Enter at least one grounding/search phrase.";
    button.disabled = false;
    return;
  }
  button.querySelector("span").textContent =
    phrases.length > 1 ? `Running ${phrases.length} phrases…` : "Running providers…";
  try {
    const providers = [...document.querySelectorAll('input[name="provider"]:checked')].map(
      (input) => input.value,
    );
    const shared = {
      target: $("#target").value,
      brandRegex: $("#brand-regex").value,
      matchMode: $("#match-mode").value,
      resolveCitationRedirects: $("#resolve-redirects").checked,
      market: $("#market").value,
      language: $("#language").value,
      debug: $("#debug").checked,
      providers,
    };
    const batches = [];
    for (const [index, query] of phrases.entries()) {
      if (phrases.length > 1) {
        button.querySelector("span").textContent = `Running phrase ${index + 1} of ${phrases.length}…`;
      }
      const result = await api("/api/run", {
        method: "POST",
        body: JSON.stringify({ ...shared, query }),
      });
      batches.push({ query, ...result });
    }
    lastResult = batches.length === 1 ? batches[0] : { batches };
    renderResults(lastResult);
  } catch (caught) {
    error.textContent = caught.message;
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Run observatory";
  }
});

$("#query").addEventListener("input", syncSelectionFromQueryField);

$("#discover-button").addEventListener("click", async () => {
  const button = $("#discover-button");
  const error = $("#discovery-error");
  error.textContent = "";
  button.disabled = true;
  button.textContent = "Discovering…";
  try {
    const result = await api("/api/discover", {
      method: "POST",
      body: JSON.stringify({
        url: $("#discovery-url").value,
        content: $("#discovery-content").value,
        count: 6,
      }),
    });
    lastDiscoveryCandidates = result.candidates || [];
    selectedCandidateQueries = new Set();
    $("#term-list").innerHTML = result.keyTerms
      .map((term) => `<span class="term">${escapeHtml(term)}</span>`)
      .join("");
    $("#candidate-list").innerHTML = result.candidates
      .map(
        (candidate) => `
          <div class="candidate">
            <div class="candidate-copy">
              <span>${escapeHtml(candidate.query)}</span>
              ${
                candidate.rationale
                  ? `<small class="muted">${escapeHtml(candidate.rationale)}</small>`
                  : ""
              }
              ${
                candidate.generator
                  ? `<small class="muted">${escapeHtml(candidate.generator)}</small>`
                  : ""
              }
            </div>
            <button type="button" data-query="${encodeURIComponent(candidate.query)}" aria-pressed="false">Use</button>
          </div>`,
      )
      .join("");
    if (result.error && result.candidates?.length) {
      $("#discovery-error").textContent = result.error;
    } else if (result.error) {
      throw new Error(result.error);
    }
    $("#discovery-results").hidden = false;
    document.querySelectorAll(".candidate button[data-query]").forEach((item) => {
      item.addEventListener("click", () => toggleCandidateQuery(item.dataset.query));
    });
    syncSelectionFromQueryField();
  } catch (caught) {
    error.textContent = caught.message;
  } finally {
    button.disabled = false;
    button.textContent = "Discover queries";
  }
});

$("#download-button").addEventListener("click", () => {
  if (!lastResult) return;
  const blob = new Blob([JSON.stringify(lastResult, null, 2)], { type: "application/json" });
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(blob);
  anchor.download = `grounding-run-${lastResult.batches?.[0]?.runId || lastResult.runId || "grounding-run"}.json`;
  anchor.click();
  URL.revokeObjectURL(anchor.href);
});

function renderResults(result) {
  const results = $("#results");
  if (result.batches?.length) {
    lastRuns = result.batches.flatMap((batch) =>
      (batch.runs || []).map((run) => ({ ...run, inputQuery: batch.query })),
    );
    $("#summary-grid").innerHTML = result.batches
      .map(
        (batch) => `
          <section class="query-batch">
            <p class="query-batch-label">${escapeHtml(batch.query)}</p>
            <div class="summary-grid-inner">
              ${(batch.runs || [])
                .map(
                  (run) => `
                    <article class="summary-card">
                      <h3>${escapeHtml(run.providerName)}</h3>
                      <div class="state ${run.targetCited}">${run.targetCited}</div>
                      <small>target cited · brand ${run.brandMentioned || "N/A"} · ${(run.latencyMs / 1000).toFixed(1)}s</small>
                    </article>`,
                )
                .join("")}
            </div>
          </section>`,
      )
      .join("");
    let runIndex = 0;
    $("#run-details").innerHTML = result.batches
      .map(
        (batch) => `
          <section class="query-batch">
            <p class="query-batch-label">${escapeHtml(batch.query)}</p>
            ${(batch.runs || [])
              .map(() => {
                const index = runIndex;
                runIndex += 1;
                return renderRunShell(lastRuns[index], index);
              })
              .join("")}
          </section>`,
      )
      .join("");
  } else {
    lastRuns = result.runs || [];
    $("#summary-grid").innerHTML = `
      <div class="summary-grid-inner">
        ${result.runs
          .map(
            (run) => `
              <article class="summary-card">
                <h3>${escapeHtml(run.providerName)}</h3>
                <div class="state ${run.targetCited}">${run.targetCited}</div>
                <small>target cited · brand ${run.brandMentioned || "N/A"} · ${(run.latencyMs / 1000).toFixed(1)}s</small>
              </article>`,
          )
          .join("")}
      </div>`;
    $("#run-details").innerHTML = result.runs.map((run, index) => renderRunShell(run, index)).join("");
  }
  bindLazyRunPanels();
  results.hidden = false;
  results.scrollIntoView({ block: "start" });
}

function bindLazyRunPanels() {
  document.querySelectorAll(".run-panel").forEach((panel) => {
    panel.addEventListener("toggle", onRunPanelToggle);
  });
}

function onRunPanelToggle(event) {
  const panel = event.currentTarget;
  if (!panel.open || panel.dataset.rendered === "true") return;
  const index = Number(panel.dataset.runIndex);
  const run = lastRuns[index];
  if (!run) return;
  panel.insertAdjacentHTML("beforeend", `<div class="detail-body">${renderRunBody(run, index)}</div>`);
  panel.dataset.rendered = "true";
  panel.querySelectorAll(".raw-block").forEach((block) => bindRawBlock(block, run));
}

function bindRawBlock(block, run) {
  block.addEventListener("toggle", () => {
    if (!block.open) return;
    const pre = block.querySelector(".raw-pre");
    if (!pre || pre.dataset.loaded === "true") return;
    if (!run?.rawResponse) return;
    pre.textContent = JSON.stringify(run.rawResponse, null, 2);
    pre.dataset.loaded = "true";
  });
}

function renderRunShell(run, index) {
  const brand = run.brandMentioned && run.brandMentioned !== "N/A"
    ? ` · brand ${run.brandMentioned}`
    : "";
  return `
    <details class="run-panel" data-run-index="${index}">
      <summary>
        <span>${escapeHtml(run.providerName)}</span>
        <span>${run.status === "failed" ? "FAILED" : `retrieved ${run.targetRetrieved} · cited ${run.targetCited}${brand}`}</span>
      </summary>
    </details>`;
}

function renderSourceSection(title, caption, sources, emptyMessage) {
  if (!sources.length) {
    return `<div><h4>${title}</h4><p class="muted">${emptyMessage}</p></div>`;
  }
  return `<div><h4>${title}</h4><p class="muted">${caption}</p><ul class="link-list">${sources
    .map(
      (source) =>
        `<li><a href="${escapeAttribute(source.url)}" target="_blank" rel="noopener">${escapeHtml(
          source.title || source.url,
        )}${source.callStatus ? ` · ${escapeHtml(source.callStatus)}` : ""}${
          source.targetMatch ? " · TARGET" : ""
        }</a></li>`,
    )
    .join("")}</ul></div>`;
}

function formatGeneratedQueryItem(item) {
  if (typeof item === "string") return item;
  if (!item || typeof item !== "object") return "";
  if (typeof item.query === "string") return item.query;
  if (item.query && typeof item.query === "object") return formatGeneratedQueryItem(item.query);
  for (const key of ["query", "search_query", "text", "q"]) {
    if (typeof item[key] === "string") return item[key];
  }
  return "";
}

function renderRunBody(run, index) {
  const openedPages = (run.sources || []).filter((source) => source.sourceOrigin === "open_page");
  const listedSources = (run.sources || []).filter(
    (source) => source.sourceOrigin !== "open_page",
  );
  const citations = run.citations?.length
    ? `<div><h4>Citations</h4><p class="muted">Inline URL citations exposed in the final answer.</p><ul class="link-list">${run.citations
        .map(
          (citation) => {
            const resolved = citation.resolvedUrl
              ? ` · resolved ${escapeHtml(citation.resolvedUrl)}`
              : citation.redirectResolution === "failed"
                ? " · redirect unresolved"
                : "";
            return `<li><a href="${escapeAttribute(citation.url)}" target="_blank" rel="noopener">${escapeHtml(
              citation.title || citation.url,
            )}${citation.targetMatch ? " · TARGET" : ""}${resolved}</a></li>`;
          },
        )
        .join("")}</ul></div>`
    : `<div><h4>Citations</h4><p class="muted">No inline URL citations were exposed. Check Opened pages if the provider opened target URLs during search.</p></div>`;
  const queries = run.generatedQueries?.length
    ? `<div><h4>Generated queries</h4><p class="muted">Search-tool queries with internal ws_call_id suffixes removed when present.</p><ul class="link-list">${run.generatedQueries
        .map((item) => {
          const query = formatGeneratedQueryItem(item);
          if (!query) return "";
          const actionType =
            item && typeof item === "object" && typeof item.actionType === "string"
              ? item.actionType
              : "";
          return `<li><span>${escapeHtml(query)}${
            actionType ? ` · ${escapeHtml(actionType)}` : ""
          }</span></li>`;
        })
        .filter(Boolean)
        .join("")}</ul></div>`
    : "";
  const raw = run.rawResponse
    ? `<details class="raw-block"><summary>Show sanitised raw response</summary><pre class="raw-pre">Open to load response JSON…</pre></details>`
    : "";
  const brandMatch = run.brandMentioned && run.brandMentioned !== "N/A"
    ? `<div><h4>Brand mentioned</h4><p class="muted">${escapeHtml(run.brandMentioned)}${
        run.brandMatches?.length
          ? ` · matched ${run.brandMatches.map((item) => `"${escapeHtml(item)}"`).join(", ")}`
          : ""
      }</p></div>`
    : "";
  return `
    ${run.error ? `<p class="error">${escapeHtml(run.error)}</p>` : ""}
    ${brandMatch}
    ${queries}
    ${renderSourceSection(
      "Opened pages",
      "Pages the search tool opened during the run. These are retrieval evidence, not inline citations.",
      openedPages,
      "No open_page URLs were exposed.",
    )}
    ${renderSourceSection(
      "Consulted source URLs",
      "URLs from explicit consulted-source lists when the provider exposes them.",
      listedSources,
      openedPages.length
        ? "No explicit consulted-source list was returned."
        : "No consulted-source URLs were exposed.",
    )}
    ${citations}
    ${run.responseText ? `<div><h4>Grounded response</h4><p class="response-text">${escapeHtml(run.responseText)}</p></div>` : ""}
    ${raw}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/"/g, "&quot;");
}

loadConfig();

function syncResolveRedirectsDefault() {
  const matchMode = $("#match-mode")?.value;
  const checkbox = $("#resolve-redirects");
  if (!checkbox || checkbox.dataset.userTouched === "true") return;
  checkbox.checked = matchMode === "url_prefix";
}

$("#match-mode")?.addEventListener("change", syncResolveRedirectsDefault);
$("#resolve-redirects")?.addEventListener("change", (event) => {
  event.currentTarget.dataset.userTouched = "true";
});
syncResolveRedirectsDefault();
