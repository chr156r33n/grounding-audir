from __future__ import annotations

from dataclasses import dataclass

from core.provider_errors import FOUNDRY_ACCESS_TOKEN_COMMAND

_FOUNDRY_ENDPOINT_EXAMPLE = (
    "https://<resource>.services.ai.azure.com/api/projects/<project-name>"
)


@dataclass(frozen=True)
class CredentialSection:
    provider_id: str
    title: str
    body: str


CREDENTIAL_SECTIONS: tuple[CredentialSection, ...] = (
    CredentialSection(
        "overview",
        "Before you start",
        f"""
Getting credentials right is usually the hardest part. This app never stores secrets in
exports, logs, or Git — values live only in this Streamlit session.

**Local Streamlit (`streamlit run app.py`)**
- API-key providers (OpenAI, Gemini, Web IQ) work by pasting keys.
- Microsoft Foundry providers can use `az login` on the same machine, or a pasted token.

**Streamlit Community Cloud**
- API-key providers still work normally.
- Microsoft Foundry providers **cannot** use `az login` on the server. Paste a fresh
  Foundry access token before each run (tokens expire in about an hour).
- The Cognitive Services **Key 1 / Key 2** from the Azure portal is **not** the same
  as the Foundry access token field in this app.

**If a run fails**
1. Enable **Debug mode** and open **API error details** on the failed provider.
2. **HTTP 401** → wrong, expired, or incorrectly pasted token/key.
3. **HTTP 403** → token/key accepted, but your identity lacks RBAC on the project.
4. **HTTP 404 / 422** → wrong deployment name, endpoint, or unsupported tool on that deployment.
""",
    ),
    CredentialSection(
        "openai_web",
        "OpenAI Web Search",
        """
**Credential type:** OpenAI API key (starts with `sk-`).

**Where to get it**
1. Sign in at [platform.openai.com](https://platform.openai.com/).
2. Go to **API keys** and create a key with access to the Responses API / web search.
3. Paste into **OpenAI API key**.

**Model field:** choose a documented Responses `web_search` model. Billing applies per OpenAI pricing.

**Works on Community Cloud:** yes — static API keys are fine.

**Docs:** [OpenAI web search guide](https://developers.openai.com/api/docs/guides/tools-web-search)
""",
    ),
    CredentialSection(
        "deepseek_web",
        "DeepSeek Web Search",
        """
**Credential type:** DeepSeek API key.

**Where to get it**
1. Sign in at [platform.deepseek.com](https://platform.deepseek.com/) (or the DeepSeek API console).
2. Create an API key with access to the **Responses API** and the built-in `web_search` tool.
3. Paste into **DeepSeek API key**.

**Model field:** choose `deepseek-v4-flash` (fast) or `deepseek-v4-pro` from the dropdown.

**Important:** DeepSeek web search uses the separate **Responses API** (`POST /responses`), not the
OpenAI-compatible `/chat/completions` endpoint. This app calls Responses with `tool_choice: required`
and the built-in `web_search` tool.

**Works on Community Cloud:** yes — static API keys are fine.

**Docs:** [DeepSeek Responses API](https://api-docs.deepseek.com/api/create-response/)
""",
    ),
    CredentialSection(
        "gemini",
        "Gemini + Google Search",
        """
**Credential type:** Gemini API key.

**Where to get it**
1. Sign in at [aistudio.google.com](https://aistudio.google.com/) or Google AI Studio.
2. Create an API key for the Gemini API.
3. Paste into **Gemini API key**.

**Model field:** choose a documented Interactions / Google Search model from the dropdown.

**Works on Community Cloud:** yes.

**Docs:** [Gemini Google Search grounding](https://ai.google.dev/gemini-api/docs/google-search)
""",
    ),
    CredentialSection(
        "microsoft_web",
        "Microsoft Foundry Web Search",
        f"""
**Credential type:** Azure AD **access token** (Bearer), **not** the portal Key 1/Key 2 API key.

**Also required**
- **Foundry project endpoint** in the form `{_FOUNDRY_ENDPOINT_EXAMPLE}`
- **Model deployment** = exact deployment name from portal → **Models + endpoints → Deployments**
  (for example `gpt-4.1-mini`, only if that is literally your deployment name)

**Get a Foundry token (no local Azure CLI required)**
1. Open [portal.azure.com](https://portal.azure.com) → **Cloud Shell** (`>_` icon).
2. Select the correct subscription:
   `az account set --subscription <your-subscription-id>`
3. Request a **Foundry-scoped** token (important — not the older Cognitive Services scope):
   `{FOUNDRY_ACCESS_TOKEN_COMMAND}`
4. Copy **only** the token string (not JSON, not `Bearer `) into **Azure access token**.

**Local alternative:** leave the token empty after `az login` on the machine running Streamlit.

**RBAC:** your identity needs **Foundry User** (or equivalent) on the project/account, plus
access to the chosen deployment.

**Works on Community Cloud:** yes, with a freshly pasted token each session.

**Docs:** [Foundry web search](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/web-search)
""",
    ),
    CredentialSection(
        "microsoft_bing",
        "Microsoft Grounding with Bing Search",
        f"""
**Credential type:** Azure AD **access token** (same as Foundry Web Search above).

**Also required**
- **Foundry project endpoint:** `{_FOUNDRY_ENDPOINT_EXAMPLE}`
- **Model deployment:** exact name from **Models + endpoints → Deployments**
- **Bing grounding connection name** *or* **connection resource ID** from your Foundry project
  (portal → project → **Connected resources** / connections). Example connection name:
  `groundingbing7jqe0b`

**Get a Foundry token**
Use Azure Cloud Shell — same command as Foundry Web Search:
`{FOUNDRY_ACCESS_TOKEN_COMMAND}`

Paste only the token string into **Azure access token**.

**RBAC (common reason for HTTP 403 even with a valid token)**
- **Foundry User** — call the project and deployment
- **Foundry Project Manager** — this provider creates and deletes a short-lived agent each run
- Access to the configured **Bing grounding connection**

**Not the same as**
- Portal **Keys and Endpoint → Key 1** (API key — not used by this app today)
- The `/connections/...` ARM path in the **project endpoint** field (that value belongs in
  connection name or connection resource ID)

**Works on Community Cloud:** yes, with a freshly pasted token.

**Docs:** [Bing grounding tools](https://learn.microsoft.com/en-us/azure/foundry/agents/how-to/tools/bing-tools)
""",
    ),
    CredentialSection(
        "microsoft_web_iq",
        "Microsoft Web IQ",
        """
**Credential type:** Web IQ API key (separate from Azure Foundry / Bing).

**Where to get it**
1. Sign up or sign in at [webiq.microsoft.ai](https://webiq.microsoft.ai/).
2. Create an API key from the Web IQ developer portal / documentation flow.
3. Paste into **Web IQ API key**.

**Optional:** **Max results** (1–50).

**Note:** Web IQ is a retrieval API — citations are N/A in this comparison matrix.

**Works on Community Cloud:** yes.

**Docs:** [Web IQ SDK](https://webiq.microsoft.ai/documentation/sdk/)
""",
    ),
)


def provider_ids_with_help() -> tuple[str, ...]:
    return tuple(section.provider_id for section in CREDENTIAL_SECTIONS if section.provider_id != "overview")


def render_credentials_help() -> None:
    import streamlit as st

    with st.expander("How to get provider credentials", expanded=False):
        overview, *providers = CREDENTIAL_SECTIONS
        st.markdown(overview.body.strip())
        st.divider()
        for section in providers:
            with st.expander(section.title, expanded=False):
                st.markdown(section.body.strip())
