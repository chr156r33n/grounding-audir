from __future__ import annotations

from uuid import uuid4

import pandas as pd
import streamlit as st

from core.enums import MatchMode, ObservationState
from core.execution import execute_providers
from core.export import export_csv, export_json
from core.matching import normalize_url
from core.models import GroundingRequest, GroundingRun, Target
from providers.registry import PROVIDERS

st.set_page_config(page_title="Grounding Source Observatory", page_icon="🔭", layout="wide")

STATE_LABELS = {
    ObservationState.YES: "YES",
    ObservationState.NO: "NO",
    ObservationState.UNKNOWN: "UNKNOWN",
    ObservationState.NOT_APPLICABLE: "N/A",
}
MATCH_LABELS = {
    "Root domain": MatchMode.ROOT_DOMAIN,
    "Exact hostname": MatchMode.EXACT_HOSTNAME,
    "URL prefix": MatchMode.URL_PREFIX,
}
MARKETS = {
    "United Kingdom (en-GB)": "en-GB",
    "United States (en-US)": "en-US",
    "Australia (en-AU)": "en-AU",
    "Canada (en-CA)": "en-CA",
    "No market requested": None,
}
LANGUAGES = {"English (en)": "en", "French (fr)": "fr", "German (de)": "de", "None": None}


def main() -> None:
    st.title("Grounding Source Observatory")
    st.caption(
        "Compare observable retrieval and citations across AI web-grounding ecosystems. "
        "This is not a rank tracker."
    )
    _methodology_help()

    submitted, values, selected, configs = _configuration_form()
    if submitted:
        _start_run(values, selected, configs)

    if st.session_state.get("grounding_runs"):
        _render_results(
            st.session_state["grounding_request"],
            st.session_state["grounding_runs"],
        )


def _configuration_form():
    with st.form("grounding-run-form"):
        st.subheader("Test configuration")
        query = st.text_input(
            "Grounding/search phrase",
            placeholder="best luxury family hotels in Hong Kong",
        )
        target = st.text_input("Target domain, hostname, or URL prefix", placeholder="fourseasons.com")
        col1, col2, col3 = st.columns(3)
        with col1:
            match_label = st.radio("Match mode", list(MATCH_LABELS), horizontal=False)
        with col2:
            market_label = st.selectbox("Country / market", list(MARKETS))
        with col3:
            language_label = st.selectbox("Language", list(LANGUAGES))

        st.subheader("Providers")
        selected: list[str] = []
        provider_columns = st.columns(2)
        for index, provider in enumerate(PROVIDERS.values()):
            with provider_columns[index % 2]:
                if st.checkbox(provider.name, value=True, key=f"selected_{provider.id}"):
                    selected.append(provider.id)

        st.subheader("Provider credentials / configuration")
        st.caption("Secrets remain in this Streamlit process and are never included in exports.")
        configs: dict[str, dict[str, str]] = {}
        for provider in PROVIDERS.values():
            with st.expander(provider.name, expanded=False):
                config: dict[str, str] = {}
                for field in provider.fields:
                    config[field.key] = st.text_input(
                        field.label,
                        value=field.default,
                        type="password" if field.secret else "default",
                        help=field.help,
                        key=f"config_{provider.id}_{field.key}",
                    )
                configs[provider.id] = config

        submitted = st.form_submit_button("Run test", type="primary", use_container_width=True)
    values = {
        "query": query,
        "target": target,
        "match_mode": MATCH_LABELS[match_label],
        "market": MARKETS[market_label],
        "language": LANGUAGES[language_label],
    }
    return submitted, values, selected, configs


def _start_run(values, selected: list[str], configs: dict[str, dict[str, str]]) -> None:
    if not values["query"].strip():
        st.error("Enter a grounding/search phrase.")
        return
    if not values["target"].strip() or not normalize_url(values["target"]):
        st.error("Enter a valid target domain, hostname, or HTTP(S) URL.")
        return
    if not selected:
        st.error("Select at least one provider.")
        return

    request = GroundingRequest(
        run_id=str(uuid4()),
        input_phrase=values["query"].strip(),
        targets=[Target(values["target"].strip(), values["match_mode"])],
        market=values["market"],
        language=values["language"],
    )
    jobs = [(PROVIDERS[provider_id], configs[provider_id]) for provider_id in selected]
    st.session_state["grounding_request"] = request
    st.session_state["grounding_runs"] = []

    st.subheader("Running test")
    statuses = {
        provider_id: st.empty()
        for provider_id in selected
    }
    for provider_id in selected:
        statuses[provider_id].info(f"⟳ {PROVIDERS[provider_id].name} — running")
    matrix_placeholder = st.empty()
    completed: dict[str, GroundingRun] = {}
    for run in execute_providers(request, jobs):
        completed[run.provider_id] = run
        if run.status.value == "complete":
            statuses[run.provider_id].success(
                f"✓ {run.provider_name} — {((run.latency_ms or 0) / 1000):.1f}s"
            )
        else:
            message = run.error.safe_message if run.error else run.status.value
            statuses[run.provider_id].error(f"{run.provider_name} — {message}")
        ordered = [completed[item] for item in selected if item in completed]
        matrix_placeholder.dataframe(_matrix_data(ordered), use_container_width=True, hide_index=True)
    st.session_state["grounding_runs"] = [
        completed[item] for item in selected if item in completed
    ]


def _render_results(request: GroundingRequest, runs: list[GroundingRun]) -> None:
    st.divider()
    st.header("Results")
    st.caption(f"Run ID: {request.run_id}")
    st.subheader(f"Target citation summary — {request.targets[0].value}")
    columns = st.columns(min(4, len(runs)))
    for index, run in enumerate(runs):
        with columns[index % len(columns)]:
            st.metric(run.provider_name, STATE_LABELS[run.target_cited])

    st.subheader("Comparison matrix")
    st.dataframe(_matrix_data(runs), use_container_width=True, hide_index=True)

    st.subheader("Provider evidence")
    for run in runs:
        _provider_details(run)

    st.subheader("Export")
    include_raw = st.checkbox("Include sanitised raw provider responses in JSON")
    col1, col2 = st.columns(2)
    with col1:
        st.download_button(
            "Download JSON",
            export_json(request, runs, include_raw=include_raw),
            file_name=f"grounding-run-{request.run_id}.json",
            mime="application/json",
            use_container_width=True,
        )
    with col2:
        st.download_button(
            "Download CSV",
            export_csv(request, runs),
            file_name=f"grounding-run-{request.run_id}.csv",
            mime="text/csv",
            use_container_width=True,
        )


def _matrix_data(runs: list[GroundingRun]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "Provider": run.provider_name,
                "Type": run.provider_type.value,
                "Search performed": STATE_LABELS[run.search_performed],
                "Target retrieved": STATE_LABELS[run.target_retrieved],
                "Target cited": STATE_LABELS[run.target_cited],
                "Generated queries": len(run.generated_queries),
                "Sources observed": len(run.sources),
                "Citations": len(run.citations),
                "Latency (ms)": run.latency_ms,
                "Status": run.status.value,
            }
            for run in runs
        ]
    )


def _provider_details(run: GroundingRun) -> None:
    with st.expander(run.provider_name):
        st.markdown("#### Summary")
        st.write(
            {
                "status": run.status.value,
                "model": run.model,
                "api_version": run.api_version,
                "latency_ms": run.latency_ms,
                "search_performed": STATE_LABELS[run.search_performed],
                "target_retrieved": STATE_LABELS[run.target_retrieved],
                "target_cited": STATE_LABELS[run.target_cited],
            }
        )
        if run.error:
            st.error(run.error.safe_message)

        st.markdown("#### Generated queries")
        if run.generated_queries:
            st.dataframe(
                [
                    {
                        "Sequence": item.sequence,
                        "Query": item.query,
                        "Search query URL": item.metadata.get("query_url"),
                    }
                    for item in run.generated_queries
                ],
                column_config={
                    "Search query URL": st.column_config.LinkColumn("Search query URL")
                },
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("Generated queries were not exposed in this response.")

        st.markdown("#### Observed sources")
        if run.sources:
            st.dataframe(
                [
                    {
                        "Order": item.retrieval_position,
                        "Domain": item.registrable_domain,
                        "URL": item.raw_url,
                        "Title": item.title,
                        "Target match": bool(item.target_matches),
                        "Retrieved": STATE_LABELS[item.retrieved],
                        "Cited": STATE_LABELS[item.cited],
                    }
                    for item in run.sources
                ],
                column_config={"URL": st.column_config.LinkColumn("URL")},
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info(
                run.metadata.get("retrieval_note")
                or "No retrieved-source list was exposed by this provider/API."
            )

        st.markdown("#### Grounding content / chunks")
        if run.grounding_content:
            for item in run.grounding_content:
                st.text(item.text or "")
                if item.source_url:
                    st.write(item.source_url)
        else:
            st.info("Grounding content/chunks were not exposed by this provider/API.")

        st.markdown("#### Citations")
        if run.citations:
            st.dataframe(
                [
                    {
                        "URL": item.url,
                        "Title": item.title,
                        "Start": item.start_index,
                        "End": item.end_index,
                        "Cited text": item.cited_text,
                        "Target match": bool(item.target_matches),
                    }
                    for item in run.citations
                ],
                column_config={"URL": st.column_config.LinkColumn("URL")},
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No citation URLs were exposed in this response.")

        st.markdown("#### Final response")
        st.text(run.response_text or "No final response text was exposed.")
        with st.expander("Provider metadata"):
            st.json(run.metadata)
        if st.checkbox("Show sanitised raw response", key=f"raw_{run.run_id}_{run.provider_id}"):
            from core.export import redact_secrets

            st.json(redact_secrets(run.raw_response))


def _methodology_help() -> None:
    with st.expander("How to read these results"):
        st.markdown(
            """
- Citation presence is not the same as retrieval presence.
- **UNKNOWN does not mean NO**: some providers do not expose their retrieved result set.
- Source, retrieval, and citation order must not be treated as conventional organic rank.
- Provider and model choices can change results, and grounding runs are inherently variable.
"""
        )


if __name__ == "__main__":
    main()
