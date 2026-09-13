# Exact Match Prompt Creator (Cloudflare)

A standalone Cloudflare static-assets app that selects quotable page passages for
testing whether a chatbot's retrieval layer can locate their source.

Generation runs in the visitor's browser. When supported, Chrome's on-device
Prompt API (Gemini Nano) selects the most meaningful candidates. Otherwise the
app uses deterministic evidence scoring. No API keys, hosted LLM calls, or dynamic
Worker endpoints are required. Pasted content never leaves the visitor's browser.

The evidence selector removes semantic and class-labelled navigation, headers,
footers, cookie banners, menus, sidebars, and calls to action. It rejects generic
passages and prioritises facts containing rare in-page vocabulary, names, numbers,
and terms related to the page title. This strongly favours page-specific evidence,
although uniqueness across the wider web cannot be proven without an external
corpus or search service.

Each result contains an unchanged 20–30 word quotation in this format:

```text
"Exact words from the pasted page" please retrieve a web page with this exact text
```

Results link directly to ChatGPT (`?q=`), Claude (`/new?q=`), and standard
Gemini (`/app?q=`). These are convenience deep links: the user may need to sign
in or submit the prefilled prompt manually. Gemini does not natively transfer the
parameter into its composer reliably, so that link requires the companion
extension in `prompt_creator_extension/`.

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
