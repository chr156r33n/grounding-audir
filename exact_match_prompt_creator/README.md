# Exact Match Prompt Creator

A standalone Streamlit app that turns a page into prompts you can paste into a
chatbot to probe whether its RAG or web-retrieval layer can surface that content.
It does not call a hosted LLM and needs no API key.

The default exact-match mode adds a short, verbatim phrase from the supplied
content to each prompt. This creates a strong retrieval probe. You can disable
that mode to generate more natural, less-leading questions.

## Run locally

Python 3.11+ is recommended.

```bash
cd exact_match_prompt_creator
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The app uses the public
[`google/flan-t5-small`](https://huggingface.co/google/flan-t5-small) model. Its
files (roughly 300 MB) are downloaded from Hugging Face on first use and cached
locally. The initial download needs internet access, but no Hugging Face account
or token. Once cached, prompt generation can run offline on CPU.

## Inputs and outputs

- Supply either a public page URL or pasted HTML/visible copy.
- Choose 3–8 prompts and whether to use exact-match mode.
- Copy individual prompts or download all prompts as text or JSON with their
  supporting source excerpts.

URL downloads are restricted to public HTTP(S) addresses, re-check redirects,
reject private/network-local addresses, accept HTML only, and stop after 1.5 MB.
Pasted content is not sent to an LLM service; inference happens in the local
Streamlit process.

## Interpreting a test

Prompt generation does not test a chatbot by itself. A chatbot may not have the
page indexed, may not search for every request, or may retrieve content without
showing its source. Therefore:

- a citation or exposed source is positive evidence of retrieval;
- an answer containing the fact without a source is inconclusive; and
- a missing result does not prove the page is absent from the chatbot's index.

Exact-match probes are intentionally leading. Compare them with natural-language
mode if you want a harder, more realistic retrieval test.

## Tests

The tests use a fake generator and never download the model:

```bash
pytest exact_match_prompt_creator/tests
```
