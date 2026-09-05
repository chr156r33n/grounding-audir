# Grounding Source Observatory

A local-first Streamlit research tool for testing whether AI web-grounding
providers expose or cite a target domain for a query. It compares observable
evidence; it is **not** a conventional search-rank tracker.

## Run locally

Python 3.11+ is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Enter a query, target, match mode, and credentials in the app, then explicitly
select **Run test**. API calls are concurrent and each provider has a 45-second
application timeout. Provider API costs may apply.

## Provider configuration

| Provider | Configuration | Retrieval observability | Citation observability |
|---|---|---|---|
| Gemini + Google Search | Gemini API key; overridable model | Unknown unless the API exposes a complete source list | URL grounding citations |
| Microsoft Foundry Web Search | Foundry project endpoint, model deployment, Azure identity/token | Usually unknown; citations are not a complete retrieval set | Inline URL citations |
| Microsoft Grounding with Bing Search | Foundry endpoint, deployment, Bing grounding connection name or resource ID, Azure identity/token | Unknown: raw grounding output is withheld | URL citations and generated-query events where exposed |
| OpenAI Web Search | OpenAI API key; overridable model | Consulted `sources` requested through the Responses API | Inline URL citations |

For Microsoft providers, leave the optional access-token field empty to use
the Azure `DefaultAzureCredential` chain (for example, an existing Azure CLI
login). A pasted token is held only in process memory. The model/deployment
must support the selected search tool in the configured Foundry project. The
current Foundry API attaches search tools to a short-lived prompt-agent version;
the identity therefore needs permission to create and delete agent versions.
The app deletes that version after each request and reports cleanup status in
provider metadata.

Model and API surfaces were checked on 5 September 2026, but they change. The
current defaults are Gemini 3.5 Flash, Microsoft `gpt-5-mini`/`gpt-4.1-mini`,
and OpenAI GPT-5.5; every model field is user-overridable. Check current
provider documentation before relying on them:

- [Gemini Google Search grounding](https://ai.google.dev/gemini-api/docs/google-search)
- [Microsoft Foundry Web Search](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/web-search)
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

## Data and security

Credentials are password-masked and remain in Streamlit session/process
memory. They are not written to disk, logged, or included in exports. Raw
responses are optional in JSON exports and recursively redact secret-bearing
fields. Retrieved content is rendered as text; the app does not crawl cited
URLs or render provider HTML as unsafe markup.

Normal tests use sanitised fixtures and make no live API calls:

```bash
pytest
```
