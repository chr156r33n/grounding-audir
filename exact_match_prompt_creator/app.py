from __future__ import annotations

import json
import os
from dataclasses import asdict

import streamlit as st

from generator import (
    PromptCreatorError,
    evidence_from_content,
    fetch_page_evidence,
    generate_prompts,
)

MODEL_ID = "google/flan-t5-small"

os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

st.set_page_config(
    page_title="Exact Match Prompt Creator",
    page_icon="🎯",
    layout="centered",
)


@st.cache_resource(show_spinner=False)
def load_local_model():
    from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForSeq2SeqLM.from_pretrained(MODEL_ID)
    model.eval()
    return tokenizer, model


def run_local_model(instructions: list[str]) -> list[str]:
    import torch

    tokenizer, model = load_local_model()
    encoded = tokenizer(
        instructions,
        return_tensors="pt",
        padding=True,
        truncation=True,
        max_length=512,
    )
    with torch.inference_mode():
        generated = model.generate(
            **encoded,
            max_new_tokens=64,
            num_beams=4,
            early_stopping=True,
            no_repeat_ngram_size=3,
        )
    return tokenizer.batch_decode(generated, skip_special_tokens=True)


def main() -> None:
    st.title("Exact Match Prompt Creator")
    st.caption(
        "Create page-specific prompts for checking whether a chatbot's RAG or web "
        "retrieval can surface your content."
    )

    with st.expander("How it works"):
        st.markdown(
            """
1. Add a public page URL or paste its HTML/visible copy.
2. The app extracts high-signal facts and runs a small model on this machine.
3. Paste the resulting prompts into the chatbot you want to test.

An exact-match probe asks the chatbot to use content containing a short verbatim
phrase from your page. This makes it a strong retrieval test, but not a natural
user query. Turn exact-match mode off to create less-leading questions.
"""
        )

    with st.form("prompt-creator"):
        input_method = st.radio(
            "Content source",
            ("Public page URL", "Paste HTML or visible copy"),
            horizontal=True,
        )
        source_url = st.text_input(
            "Page URL",
            placeholder="https://example.com/page-to-test",
            disabled=input_method != "Public page URL",
        )
        pasted_content = st.text_area(
            "Page HTML or visible copy",
            placeholder="Paste several paragraphs from the page…",
            height=220,
            disabled=input_method != "Paste HTML or visible copy",
        )
        col1, col2 = st.columns(2)
        with col1:
            count = st.slider("Number of prompts", min_value=3, max_value=8, value=5)
        with col2:
            exact_match = st.checkbox(
                "Exact-match mode",
                value=True,
                help=(
                    "Adds a verbatim phrase from your content to each prompt. "
                    "Disable it for more natural, less-leading questions."
                ),
            )
        submitted = st.form_submit_button(
            "Create prompts",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        _create_prompts(
            input_method=input_method,
            source_url=source_url,
            pasted_content=pasted_content,
            count=count,
            exact_match=exact_match,
        )

    if st.session_state.get("prompt_results"):
        _render_results()

    st.divider()
    st.caption(
        f"Runs locally with {MODEL_ID}. No API key or account is required. "
        "The model downloads once on first use and is then cached. A missing result "
        "does not prove that a chatbot lacks or cannot retrieve the page."
    )


def _create_prompts(
    *,
    input_method: str,
    source_url: str,
    pasted_content: str,
    count: int,
    exact_match: bool,
) -> None:
    try:
        with st.status("Reading content…", expanded=True) as status:
            if input_method == "Public page URL":
                if not source_url.strip():
                    raise PromptCreatorError("Enter a public page URL.")
                evidence = fetch_page_evidence(source_url)
                status.write("Page downloaded and high-signal copy extracted.")
            else:
                evidence = evidence_from_content(pasted_content, source=source_url)
                status.write("Pasted copy parsed and high-signal facts extracted.")

            status.update(label="Loading the local model…")
            load_local_model()
            status.write(
                "The first run may download the public model; later runs use the cache."
            )

            status.update(label="Creating retrieval prompts…")
            prompts = generate_prompts(
                evidence,
                count=count,
                generator=run_local_model,
                exact_match=exact_match,
            )
            if not prompts:
                raise PromptCreatorError(
                    "No distinct prompts could be created from this content."
                )
            st.session_state["prompt_results"] = {
                "evidence": evidence,
                "prompts": prompts,
                "exact_match": exact_match,
            }
            status.update(
                label=f"Created {len(prompts)} prompts",
                state="complete",
                expanded=False,
            )
    except PromptCreatorError as exc:
        st.session_state.pop("prompt_results", None)
        st.error(str(exc))
    except Exception:
        st.session_state.pop("prompt_results", None)
        st.error(
            "The local model could not be loaded. Check your internet connection for "
            "the first download, then retry."
        )


def _render_results() -> None:
    result = st.session_state["prompt_results"]
    evidence = result["evidence"]
    prompts = result["prompts"]

    st.divider()
    st.subheader("Prompts")
    st.caption(
        f"{'Exact-match' if result['exact_match'] else 'Natural-language'} mode · "
        f"{evidence.title or evidence.source} · {len(evidence.chunks)} evidence chunks"
    )
    for index, candidate in enumerate(prompts, start=1):
        st.markdown(f"**{index}.**")
        st.code(candidate.prompt, language="text")
        with st.expander("Why this prompt is grounded"):
            st.markdown("**Exact phrase**")
            st.write(candidate.exact_phrase)
            st.markdown("**Supporting page copy**")
            st.write(candidate.source_excerpt)
            if candidate.generation_method == "template_fallback":
                st.caption(
                    "The small model's output did not pass the grounding check, so a "
                    "content-based fallback template was used."
                )

    records = [asdict(candidate) for candidate in prompts]
    text_export = "\n\n".join(
        f"{index}. {candidate.prompt}"
        for index, candidate in enumerate(prompts, start=1)
    )
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Download prompts (.txt)",
            text_export,
            file_name="exact-match-prompts.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            "Download evidence (.json)",
            json.dumps(
                {
                    "source": evidence.source,
                    "title": evidence.title,
                    "exact_match": result["exact_match"],
                    "prompts": records,
                },
                ensure_ascii=False,
                indent=2,
            ),
            file_name="exact-match-prompts.json",
            mime="application/json",
            use_container_width=True,
        )

    with st.expander("Extracted page evidence"):
        st.write(
            {
                "source": evidence.source,
                "title": evidence.title,
                "content_type": evidence.content_type,
                "input_method": evidence.input_method,
                "downloaded_bytes": evidence.downloaded_bytes,
            }
        )
        for chunk in evidence.chunks:
            st.caption(f"{chunk.kind} · score {chunk.score}")
            st.write(chunk.text)


if __name__ == "__main__":
    main()
