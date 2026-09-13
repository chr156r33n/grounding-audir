# Exact Match Passage Finder — Chrome extension

A standalone Manifest V3 extension that analyzes the currently rendered page,
selects meaningful 20–30 word quotations, and creates exact-text retrieval
prompts. It does not require the Cloudflare app or any API credentials.

The extension:

1. runs only when the user opens the extension and selects **Analyze this page**;
2. reads visible headings, paragraphs, and list items from the rendered DOM;
3. excludes navigation, menus, headers, footers, cookie banners, sidebars, hidden
   elements, and calls to action;
4. asks Chrome's on-device Prompt API to rank unchanged candidate passages;
5. falls back to deterministic scoring if Chrome AI is unavailable; and
6. provides links to open each prompt in ChatGPT, Claude, or standard Gemini.

Gemini does not natively support `?q=` prompt prefilling reliably. A content
script scoped only to `https://gemini.google.com/*` reads the extension's link,
places its prompt in Gemini's conversation box, removes the parameter from the
address bar, and leaves submission to the user.

Page content and model inference remain on the user's device.

## Install unpacked

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Select **Load unpacked**.
4. Choose the `prompt_creator_extension` directory.
5. Pin **Exact Match Passage Finder** if desired.

Open a normal web page, select the extension, and choose **Analyze this page**.
Chrome internal pages, the Chrome Web Store, and other protected pages do not
allow extension DOM access.

## Permissions

- `activeTab`: temporary access to the page the user explicitly analyzes
- `scripting`: execute the rendered-DOM extraction function
- `https://gemini.google.com/*`: transfer a `?q=` prompt into Gemini's composer

There are no other persistent host permissions, background services, analytics,
or network APIs. The Gemini content script runs only on Gemini's own hostname and
does not submit prompts automatically.

## Chatbot links

- ChatGPT: `https://chatgpt.com/?q=...`
- Claude: `https://claude.ai/new?q=...`
- Gemini: `https://gemini.google.com/app?q=...`

These services can change their web routes. Sign-in or manual submission may be
required. The extension supplies Gemini's missing parameter-to-composer behavior.

## Test

```bash
node --test prompt_creator_extension/test/*.test.mjs
```
