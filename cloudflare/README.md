# Grounding Observatory — Cloudflare Workers

This is a second application in the repository. It does **not** replace or
modify the Streamlit deployment. The Worker serves a separate edge-native UI
and JSON API from the `cloudflare/` directory.

## Supported providers

- OpenAI Web Search
- DeepSeek Web Search
- Gemini + Google Search
- Microsoft Foundry Web Search
- Microsoft Web IQ

Microsoft Grounding with Bing Search remains in the Streamlit application.
That integration creates and deletes an ephemeral Foundry agent version through
the Azure SDK. It has deliberately not been approximated in the Worker with an
unverified REST lifecycle.

## One-time Cloudflare setup

1. Create a Cloudflare API token with **Workers Scripts: Edit** permission.
2. Add these GitHub repository secrets:
   - `CLOUDFLARE_API_TOKEN`
   - `CLOUDFLARE_ACCOUNT_ID`
3. Configure provider secrets using Wrangler from a trusted machine:

   ```bash
   cd cloudflare
   npm install
   npx wrangler login
   npx wrangler secret put OBSERVATORY_ACCESS_KEY
   npx wrangler secret put OPENAI_API_KEY
   npx wrangler secret put DEEPSEEK_API_KEY
   npx wrangler secret put GEMINI_API_KEY
   npx wrangler secret put FOUNDRY_PROJECT_ENDPOINT
   npx wrangler secret put AZURE_ACCESS_TOKEN
   npx wrangler secret put WEBIQ_API_KEY
   ```

   Only configure the providers you intend to use. The UI disables providers
   whose required secrets are absent. `OBSERVATORY_ACCESS_KEY` is mandatory:
   users enter it in the edge UI before requests are allowed to consume paid
   provider APIs.

4. Merge to `main` or run **Deploy Cloudflare Worker** from GitHub Actions.

The workflow only runs when `cloudflare/**` or its workflow changes. Existing
Streamlit files and deployment remain independent.

## Models and non-secret configuration

Edit `wrangler.jsonc` to set model deployment names and endpoint defaults:

- `OPENAI_MODEL`
- `DEEPSEEK_MODEL` and `DEEPSEEK_BASE_URL`
- `GEMINI_MODEL` and `GEMINI_API_URL`
- `FOUNDRY_MODEL` (the exact deployment name)
- `FOUNDRY_SEARCH_CONTEXT_SIZE`
- `WEBIQ_API_URL` and `WEBIQ_MAX_RESULTS`

`AZURE_ACCESS_TOKEN` is short-lived. A production deployment should rotate it
before expiry. The Streamlit app can use `DefaultAzureCredential`; Workers
cannot, so the edge app requires an explicit bearer token.

The Web IQ REST base URL is configurable because access programs may issue
tenant-specific endpoints. Confirm `WEBIQ_API_URL` against the Web IQ account
documentation if the default does not match your tenant.

For organization-wide authentication, place the Worker behind Cloudflare
Access as well. The application key remains a second guard against direct API
use; do not commit it to GitHub or put it in `wrangler.jsonc`.

## Local development

Create `cloudflare/.dev.vars` (ignored by Git) with only the credentials you
need:

```dotenv
OPENAI_API_KEY=...
OBSERVATORY_ACCESS_KEY=choose-a-long-random-value
GEMINI_API_KEY=...
FOUNDRY_PROJECT_ENDPOINT=https://resource.services.ai.azure.com/api/projects/project
AZURE_ACCESS_TOKEN=...
```

Then:

```bash
cd cloudflare
npm install
npm run dev
```

Useful endpoints:

- `GET /api/health`
- `GET /api/config`
- `POST /api/discover`
- `POST /api/run`

## Cloudflare Git integration alternative

If you prefer Cloudflare Builds instead of GitHub Actions, connect this GitHub
repository in **Workers & Pages → Create → Import a repository**:

- Root directory: `cloudflare`
- Build command: `npm run deploy`
- Deploy command: leave empty if the dashboard detects Wrangler, otherwise
  `npx wrangler deploy`

Add provider secrets in **Settings → Variables and Secrets**. Do not configure
both automatic Git deployment and the GitHub workflow for the same Worker,
otherwise each push can deploy twice.
