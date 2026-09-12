# Grounding Source Observatory

A local-first Streamlit research tool for testing whether AI web-grounding
providers expose or cite a target domain for a query. It compares observable
evidence; it is **not** a conventional search-rank tracker.

This repository also contains a separate Cloudflare Workers edition in
[`cloudflare/`](cloudflare/README.md). It has its own edge-native UI, API, and
GitHub deployment workflow. The Worker and Streamlit deployments are parallel;
deploying one does not replace or remove the other.

A credential-free, standalone query-generation spin-off is available in
[`exact_match_prompt_creator/`](exact_match_prompt_creator/README.md). It uses a
small local model to create page-specific prompts for testing chatbot retrieval.

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Enter a query, target, match mode, and credentials in the app, then explicitly
select **Run test**. API calls are concurrent. The default per-provider timeout is
90 seconds (configurable in the form; OpenAI and other web-search providers use
at least 120 seconds when needed). Provider API costs may apply.

## URL query discovery

Optionally paste a public page URL in **Source URL for query discovery**, then
select **Discover queries from URL** to run discovery without starting the
grounding providers. Alternatively, **Run test** performs discovery and the
configured grounding run together. The app:

1. downloads the page's static HTML once (no browser or JavaScript execution);
2. extracts the title, description, canonical URL, headings, and high-signal
   body chunks;
3. asks each configured OpenAI and Gemini API for realistic queries where that
   page would be highly relevant if it is indexed and available to the
   retrieval pipeline; and
4. merges and displays the candidates with rationale and supporting DOM
   evidence.

Use a suggestion to populate the main query field, then explicitly run the test
again. Suggestions are retrieval hypotheses, not rank or inclusion guarantees.
Query discovery only fetches public HTTP(S) addresses: private, loopback, and
link-local targets are rejected, redirects are revalidated, downloads are
size-limited, and only HTML content is accepted.

## Provider configuration

| Provider | Configuration | Retrieval observability | Citation observability |
|---|---|---|---|
| Gemini + Google Search | Gemini API key; model from documented Interactions list | Unknown: Interactions does not expose raw SERP rows | URL citation annotations |
| Microsoft Foundry Web Search | Foundry project endpoint, model deployment from documented list, Azure identity/token | Complete consulted `sources` requested through Responses; unknown if omitted | Inline URL citations |
| Microsoft Web IQ | Web IQ API key from [webiq.microsoft.ai](https://webiq.microsoft.ai); optional max results (1–50) | Ranked `webResults` with passage-level content | N/A: retrieval API, not a citation layer |
| Microsoft Grounding with Bing Search | Foundry endpoint, deployment from documented list, Bing grounding connection name or resource ID, Azure identity/token | Unknown: raw grounding output is withheld | URL citations and generated-query events where exposed |
| OpenAI Web Search | OpenAI API key; model from documented Responses web_search list | Consulted `sources` requested through the Responses API | Inline URL citations |

For Microsoft providers, leave the optional access-token field empty to use
the Azure `DefaultAzureCredential` chain (for example, an existing Azure CLI
login). A pasted token is held only in process memory. The model/deployment
must support the selected search tool in the configured Foundry project. The
explicit Bing provider attaches its tool to a short-lived prompt-agent version,
so that identity also needs permission to create and delete agent versions. The
app deletes that version after each Bing request and reports cleanup status.

Model dropdowns are populated from provider documentation checked on 6 September 2026
(see `providers/model_catalog.py` for source URLs). Enable **Debug mode** in the run
form to capture per-provider request payloads, execution traces, response summaries,
and sanitised raw responses.

- [Gemini Interactions Google Search](https://ai.google.dev/gemini-api/docs/interactions/google-search)
- [Gemini Google Search grounding](https://ai.google.dev/gemini-api/docs/google-search)
- [Microsoft Foundry Web Search](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/web-search)
- [Microsoft Web IQ](https://webiq.microsoft.ai/documentation/sdk/)
- [Microsoft Grounding with Bing Search](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)
- [OpenAI Web Search](https://developers.openai.com/api/docs/guides/tools-web-search)

## Reading results

`YES`, `NO`, `UNKNOWN`, and `N/A` are distinct internal states. In particular,
**UNKNOWN does not mean NO**. A citation proves attribution, not that the API
showed the complete retrieval set; a missing citation does not prove that a
domain was never retrieved. Retrieval/citation order is not labelled as
organic rank.

Grounding is variable. A single run is weak evidence, so preserve the run ID,
provider, model, locale, and exported evidence when comparing results.

When a state is **UNKNOWN**, expand the provider section and read **Why these
states?** — each YES/NO/UNKNOWN/N/A value includes a plain-language reason
(for example, OpenAI search ran but omitted `web_search_call.action.sources`).

## Data and security

Credentials are password-masked and remain in Streamlit session/process
memory. They are not written to disk, logged, or included in exports. Raw
responses are optional in JSON exports and recursively redact secret-bearing
fields. Retrieved content is rendered as text. The optional query-discovery
fetch downloads only the user-supplied public page; provider citations are not
crawled. Google Search Suggestions are the sole provider markup rendered, using
isolated Streamlit iframes as required by Google; other provider HTML is not
rendered.

Normal tests use sanitised fixtures and make no live API calls:

```bash
pytest
```
