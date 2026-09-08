const $ = (selector) => document.querySelector(selector);
let lastResult = null;

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
  button.querySelector("span").textContent = "Running providers…";
  try {
    const providers = [...document.querySelectorAll('input[name="provider"]:checked')].map(
      (input) => input.value,
    );
    lastResult = await api("/api/run", {
      method: "POST",
      body: JSON.stringify({
        query: $("#query").value,
        target: $("#target").value,
        matchMode: $("#match-mode").value,
        market: $("#market").value,
        language: $("#language").value,
        debug: $("#debug").checked,
        providers,
      }),
    });
    renderResults(lastResult);
  } catch (caught) {
    error.textContent = caught.message;
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "Run observatory";
  }
});

$("#discover-button").addEventListener("click", async () => {
  const button = $("#discover-button");
  const error = $("#discovery-error");
  error.textContent = "";
  button.disabled = true;
  button.textContent = "Extracting…";
  try {
    const result = await api("/api/discover", {
      method: "POST",
      body: JSON.stringify({
        url: $("#discovery-url").value,
        content: $("#discovery-content").value,
        count: 6,
      }),
    });
    $("#term-list").innerHTML = result.keyTerms
      .map((term) => `<span class="term">${escapeHtml(term)}</span>`)
      .join("");
    $("#candidate-list").innerHTML = result.candidates
      .map(
        (candidate, index) => `
          <div class="candidate">
            <span>${escapeHtml(candidate.query)}</span>
            <button type="button" data-query="${encodeURIComponent(candidate.query)}">Use</button>
          </div>`,
      )
      .join("");
    $("#discovery-results").hidden = false;
    document.querySelectorAll(".candidate button").forEach((item) => {
      item.addEventListener("click", () => {
        $("#query").value = decodeURIComponent(item.dataset.query);
        $("#query").focus();
      });
    });
  } catch (caught) {
    error.textContent = caught.message;
  } finally {
    button.disabled = false;
    button.textContent = "Extract terms & queries";
  }
});

$("#download-button").addEventListener("click", () => {
  if (!lastResult) return;
  const blob = new Blob([JSON.stringify(lastResult, null, 2)], { type: "application/json" });
  const anchor = document.createElement("a");
  anchor.href = URL.createObjectURL(blob);
  anchor.download = `grounding-run-${lastResult.runId}.json`;
  anchor.click();
  URL.revokeObjectURL(anchor.href);
});

function renderResults(result) {
  const results = $("#results");
  $("#summary-grid").innerHTML = result.runs
    .map(
      (run) => `
        <article class="summary-card">
          <h3>${escapeHtml(run.providerName)}</h3>
          <div class="state ${run.targetCited}">${run.targetCited}</div>
          <small>target cited · ${(run.latencyMs / 1000).toFixed(1)}s</small>
        </article>`,
    )
    .join("");
  $("#run-details").innerHTML = result.runs.map(renderRun).join("");
  results.hidden = false;
  results.scrollIntoView({ behavior: "smooth", block: "start" });
}

function renderSourceSection(title, caption, sources, emptyMessage) {
  if (!sources.length) {
    return `<div><h4>${title}</h4><p class="muted">${emptyMessage}</p></div>`;
  }
  return `<div><h4>${title}</h4><p class="muted">${caption}</p><div class="link-list">${sources
    .map(
      (source) =>
        `<a href="${escapeAttribute(source.url)}" target="_blank" rel="noopener">${escapeHtml(
          source.title || source.url,
        )}${source.callStatus ? ` · ${escapeHtml(source.callStatus)}` : ""}${
          source.targetMatch ? " · TARGET" : ""
        }</a>`,
    )
    .join("")}</div></div>`;
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

function renderRun(run) {
  const openedPages = (run.sources || []).filter((source) => source.sourceOrigin === "open_page");
  const listedSources = (run.sources || []).filter(
    (source) => source.sourceOrigin !== "open_page",
  );
  const citations = run.citations?.length
    ? `<div><h4>Citations</h4><p class="muted">Inline URL citations exposed in the final answer.</p><div class="link-list">${run.citations
        .map(
          (citation) =>
            `<a href="${escapeAttribute(citation.url)}" target="_blank" rel="noopener">${escapeHtml(
              citation.title || citation.url,
            )}${citation.targetMatch ? " · TARGET" : ""}</a>`,
        )
        .join("")}</div></div>`
    : `<div><h4>Citations</h4><p class="muted">No inline URL citations were exposed. Check Opened pages if the provider opened target URLs during search.</p></div>`;
  const queries = run.generatedQueries?.length
    ? `<div><h4>Generated queries</h4><p class="muted">Search-tool queries with internal ws_call_id suffixes removed when present.</p><div class="link-list">${run.generatedQueries
        .map((item) => {
          const query = formatGeneratedQueryItem(item);
          if (!query) return "";
          const actionType =
            item && typeof item === "object" && typeof item.actionType === "string"
              ? item.actionType
              : "";
          return `<span>${escapeHtml(query)}${
            actionType ? ` · ${escapeHtml(actionType)}` : ""
          }</span>`;
        })
        .filter(Boolean)
        .join("")}</div></div>`
    : "";
  const raw = run.rawResponse
    ? `<div><h4>Raw response</h4><pre>${escapeHtml(JSON.stringify(run.rawResponse, null, 2))}</pre></div>`
    : "";
  return `
    <details>
      <summary>
        <span>${escapeHtml(run.providerName)}</span>
        <span>${run.status === "failed" ? "FAILED" : `retrieved ${run.targetRetrieved} · cited ${run.targetCited}`}</span>
      </summary>
      <div class="detail-body">
        ${run.error ? `<p class="error">${escapeHtml(run.error)}</p>` : ""}
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
        ${run.responseText ? `<div><h4>Grounded response</h4><p>${escapeHtml(run.responseText)}</p></div>` : ""}
        ${raw}
      </div>
    </details>`;
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = String(value ?? "");
  return node.innerHTML;
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/"/g, "&quot;");
}

loadConfig();
