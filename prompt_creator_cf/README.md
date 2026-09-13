# Exact Match Prompt Creator (Cloudflare)

A standalone Cloudflare static-assets app that creates page-specific prompts for
testing whether a chatbot's retrieval layer can surface your content.

Generation runs in the visitor's browser. When supported, Chrome's on-device
Prompt API (Gemini Nano) helps phrase the questions. Otherwise the app falls back
to grounded templates. No API keys, hosted LLM calls, or dynamic Worker endpoints
are required. Pasted content never leaves the visitor's browser.

This app is independent from the main Grounding Source Observatory Worker in
`cloudflare/`. Deploy it to its own Worker name and custom domain.

## Deploy

### GitHub Actions

1. Ensure `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` are configured as
   repository secrets.
2. Push changes under `prompt_creator_cf/**` to `main`, or run
   **Deploy Prompt Creator Worker** manually.

The default Worker name is `exact-match-prompt-creator`. Attach a custom domain in
the Cloudflare dashboard after the first deploy.

### Local development

```bash
cd prompt_creator_cf
npm install
npm run dev
```

Open the printed local URL in desktop Chrome. Chrome on-device AI also works on
`localhost` when the Prompt API is enabled in your browser.

The deployed app serves static assets only. There is no page-fetching proxy or
application API to rate-limit or abuse. Cloudflare currently treats static asset
requests as free and unlimited.

## Chrome on-device AI

Supported desktop Chrome builds expose `LanguageModel` (Prompt API). The model
downloads once in the user's browser, not on every visit.

If Chrome AI is unavailable, the app still works using template-based prompts
built from extracted page copy.

## Tests

```bash
cd prompt_creator_cf
npm install
npm test
```
