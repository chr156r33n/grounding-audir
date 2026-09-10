const $ = (selector) => document.querySelector(selector);
let lastResult = null;
let lastRuns = [];
let lastRequest = null;
let lastDiscoveryCandidates = [];
let selectedCandidateQueries = new Set();
const MAX_PROPERTIES = 5;
const CATEGORY_OPTIONS = [
  { value: "owned", label: "Owned" },
  { value: "of_interest", label: "Of interest" },
  { value: "competition", label: "Competition" },
];
const MATCH_OPTIONS = [
  { value: "root_domain", label: "Root domain" },
  { value: "exact_hostname", label: "Exact hostname" },
  { value: "url_prefix", label: "URL prefix" },
];
let propertyCount = 1;

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

function propertyRowHtml(index) {
  const categoryOptions = CATEGORY_OPTIONS.map(
    (option) =>
      `<option value="${option.value}">${escapeHtml(option.label)}</option>`,
  ).join("");
  const matchOptions = MATCH_OPTIONS.map(
    (option) =>
      `<option value="${option.value}">${escapeHtml(option.label)}</option>`,
  ).join("");
  return `
    <div class="property-row" data-property-index="${index}">
      <div class="property-row-head">
        <strong>Property ${index + 1}</strong>
        ${
          index > 0
            ? `<button type="button" class="text-button remove-property" data-index="${index}">Remove</button>`
            : ""
        }
      </div>
      <div class="property-row-grid">
        <label>
          <span>URL or domain</span>
          <input class="property-value" ${index === 0 ? "required" : ""} placeholder="example.com" />
        </label>
        <label>
          <span>Label</span>
          <input class="property-label" placeholder="Optional display name" />
        </label>
        <label>
          <span>Category</span>
          <select class="property-category">${categoryOptions}</select>
        </label>
        <label>
          <span>Match mode</span>
          <select class="property-match">${matchOptions}</select>
        </label>
        <label class="full-width">
          <span>Brand regex</span>
          <input class="property-brand" placeholder="Optional, per property" />
        </label>
      </div>
    </div>`;
}

function renderPropertyRows() {
  const list = $("#property-list");
  if (!list) return;
  list.innerHTML = Array.from({ length: propertyCount }, (_, index) => propertyRowHtml(index)).join("");
  list.querySelectorAll(".remove-property").forEach((button) => {
    button.addEventListener("click", () => {
      if (propertyCount <= 1) return;
      propertyCount -= 1;
      renderPropertyRows();
      syncResolveRedirectsDefault();
    });
  });
  list.querySelectorAll(".property-match").forEach((select) => {
    select.addEventListener("change", syncResolveRedirectsDefault);
  });
  $("#add-property").disabled = propertyCount >= MAX_PROPERTIES;
}

function collectTargets() {
  const rows = [...document.querySelectorAll(".property-row")];
  const targets = rows
    .map((row) => ({
      value: row.querySelector(".property-value")?.value.trim() || "",
      label: row.querySelector(".property-label")?.value.trim() || "",
      category: row.querySelector(".property-category")?.value || "owned",
      matchMode: row.querySelector(".property-match")?.value || "root_domain",
      brandRegex: row.querySelector(".property-brand")?.value.trim() || "",
    }))
    .filter((target) => target.value);
  if (!targets.length) {
    throw new Error("Add at least one property to monitor.");
  }
  return targets;
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
    const targets = collectTargets();
    const shared = {
      targets,
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
    lastRequest = batches.length === 1 ? batches[0].request : batches[0]?.request || null;
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
  const batches = result.batches?.length ? result.batches : [result];
  lastRuns = batches.flatMap((batch) =>
    (batch.runs || []).map((run) => ({ ...run, inputQuery: batch.query })),
  );
  lastRequest = batches[0]?.request || result.request || lastRequest;
  $("#summary-grid").innerHTML = batches
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
                    <small>any property cited · ${(run.latencyMs / 1000).toFixed(1)}s</small>
                  </article>`,
              )
              .join("")}
          </div>
        </section>`,
    )
    .join("");
  renderPropertyMatrix(batches);
  let runIndex = 0;
  $("#run-details").innerHTML = batches
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
  bindLazyRunPanels();
  results.hidden = false;
  results.scrollIntoView({ block: "start" });
}

function renderPropertyMatrix(batches) {
  const matrix = $("#property-matrix");
  if (!matrix) return;
  const request = batches[0]?.request || lastRequest;
  const targets = request?.targets || [];
  const runs = batches.flatMap((batch) =>
    (batch.runs || []).map((run) => ({ ...run, inputQuery: batch.query })),
  );
  if (!targets.length || !runs.length) {
    matrix.innerHTML = "";
    return;
  }
  const providerHeaders = runs
    .map(
      (run) => `
        <th colspan="3" class="provider-group">${escapeHtml(
          batches.length > 1 ? `${run.providerName} · ${run.inputQuery}` : run.providerName,
        )}</th>`,
    )
    .join("");
  const metricHeaders = runs
    .map(() => `<th>Retrieved</th><th>Cited</th><th>Brand</th>`)
    .join("");
  const body = targets
    .map((target) => {
      const cells = runs
        .map((run) => {
          const match = (run.propertyResults || []).find((item) => item.value === target.value);
          const retrieved = match?.retrieved || run.targetRetrieved || "UNKNOWN";
          const cited = match?.cited || run.targetCited || "UNKNOWN";
          const brand = match?.brandMentioned || "N/A";
          return `
            <td class="state ${retrieved}">${escapeHtml(retrieved)}</td>
            <td class="state ${cited}">${escapeHtml(cited)}</td>
            <td class="state ${brand}">${escapeHtml(brand)}</td>`;
        })
        .join("");
      const label = target.label || target.value;
      return `
        <tr class="category-${target.category || "owned"}">
          <td>
            <strong>${escapeHtml(label)}</strong>
            <div class="muted">${escapeHtml(target.value)}</div>
          </td>
          <td>${escapeHtml(formatCategory(target.category))}</td>
          ${cells}
        </tr>`;
    })
    .join("");
  matrix.innerHTML = `
    <p class="micro-label">Property comparison matrix</p>
    <table>
      <thead>
        <tr>
          <th rowspan="2">Property</th>
          <th rowspan="2">Category</th>
          ${providerHeaders}
        </tr>
        <tr>${metricHeaders}</tr>
      </thead>
      <tbody>${body}</tbody>
    </table>`;
}

function formatCategory(category) {
  return CATEGORY_OPTIONS.find((item) => item.value === category)?.label || category || "Owned";
}

function formatPropertyMatches(values) {
  if (!values?.length) return "";
  return ` · ${values.map((item) => escapeHtml(item)).join(", ")}`;
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
  const propertySummary = (run.propertyResults || [])
    .map((item) => `${item.label || item.value}: ${item.cited}`)
    .join(" · ");
  return `
    <details class="run-panel" data-run-index="${index}">
      <summary>
        <span>${escapeHtml(run.providerName)}</span>
        <span>${run.status === "failed" ? "FAILED" : propertySummary || `retrieved ${run.targetRetrieved} · cited ${run.targetCited}`}</span>
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
          formatPropertyMatches(source.targetMatches)
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
            )}${formatPropertyMatches(citation.targetMatches)}${resolved}</a></li>`;
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
  const propertyResults = run.propertyResults?.length
    ? `<div><h4>Property results</h4><table class="property-mini-table"><thead><tr><th>Property</th><th>Category</th><th>Retrieved</th><th>Cited</th><th>Brand</th></tr></thead><tbody>${run.propertyResults
        .map(
          (item) => `
            <tr>
              <td>${escapeHtml(item.label || item.value)}</td>
              <td>${escapeHtml(formatCategory(item.category))}</td>
              <td class="state ${item.retrieved}">${escapeHtml(item.retrieved)}</td>
              <td class="state ${item.cited}">${escapeHtml(item.cited)}</td>
              <td class="state ${item.brandMentioned}">${escapeHtml(item.brandMentioned)}</td>
            </tr>`,
        )
        .join("")}</tbody></table></div>`
    : "";
  return `
    ${run.error ? `<p class="error">${escapeHtml(run.error)}</p>` : ""}
    ${propertyResults}
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
renderPropertyRows();
$("#add-property")?.addEventListener("click", () => {
  if (propertyCount >= MAX_PROPERTIES) return;
  propertyCount += 1;
  renderPropertyRows();
  syncResolveRedirectsDefault();
});

function syncResolveRedirectsDefault() {
  const checkbox = $("#resolve-redirects");
  if (!checkbox || checkbox.dataset.userTouched === "true") return;
  checkbox.checked = [...document.querySelectorAll(".property-match")].some(
    (select) => select.value === "url_prefix",
  );
}

document.querySelectorAll(".property-match").forEach((select) => {
  select.addEventListener("change", syncResolveRedirectsDefault);
});
$("#resolve-redirects")?.addEventListener("change", (event) => {
  event.currentTarget.dataset.userTouched = "true";
});
syncResolveRedirectsDefault();
