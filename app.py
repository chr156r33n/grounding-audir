from __future__ import annotations

import json
from uuid import uuid4

import pandas as pd
import streamlit as st

from core.enums import MatchMode, ObservationState, TargetCategory
from core.execution import execute_providers
from core.diagnostics import build_state_notes, unknown_observation_fields
from core.export import export_csv, export_json
from core.models import GroundingRequest, GroundingRun, ProviderField, Target
from core.phrases import split_input_phrases
from core.query_discovery import QueryDiscoveryResult, discover_queries
from core.query_discovery_compat import QueryDiscoveryCompatibilityError, call_discover_queries
from core.query_discovery_config import DEFAULT_FETCH_PROFILE, FETCH_PROFILES
from core.credentials_help import render_credentials_help
from core.targets import CATEGORY_LABELS, MAX_MONITOR_PROPERTIES, display_label, validate_targets
from providers.registry import PROVIDERS
from providers.responses_parsing import extract_query_text

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
CATEGORY_OPTIONS = {
    "Owned": TargetCategory.OWNED,
    "Of interest": TargetCategory.OF_INTEREST,
    "Competition": TargetCategory.COMPETITION,
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

    action, values, selected, configs = _configuration_form()
    if action == "discover":
        _start_query_discovery(values, configs)
    elif action == "run":
        _start_run(values, selected, configs)

    runs = st.session_state.get("grounding_runs") or []
    discovery = st.session_state.get("query_discovery")
    if runs:
        _render_results(
            st.session_state["grounding_request"],
            runs,
        )
    elif discovery:
        st.divider()
        st.header("Results")
        _render_query_discovery(discovery)


def _render_provider_field(provider_id: str, field: ProviderField) -> str:
    key = f"config_{provider_id}_{field.key}"
    if field.choices:
        options = list(field.choices)
        default_index = options.index(field.default) if field.default in options else 0
        return st.selectbox(
            field.label,
            options,
            index=default_index,
            help=field.help,
            key=key,
        )
    return st.text_input(
        field.label,
        value=field.default,
        type="password" if field.secret else "default",
        help=field.help,
        key=key,
    )


def _debug_mode_enabled(request: GroundingRequest | None) -> bool:
    return bool(request and request.provider_options.get("debug_mode"))


def _render_debug_panel(run: GroundingRun, *, expanded: bool = False) -> None:
    debug = run.metadata.get("debug") or {}
    if not debug and run.raw_response is None:
        return
    with st.expander("Debug trace", expanded=expanded):
        execution_trace = debug.get("execution_trace") or []
        if execution_trace:
            st.markdown("**Execution timeline**")
            st.dataframe(execution_trace, hide_index=True, use_container_width=True)
        trace = debug.get("trace") or []
        if trace:
            st.markdown("**Provider request timeline**")
            st.dataframe(trace, hide_index=True, use_container_width=True)
        if debug.get("context"):
            st.markdown("**Run context**")
            st.json(debug["context"])
        if debug.get("request_body"):
            st.markdown("**API request body (sanitised)**")
            st.json(debug["request_body"])
        if debug.get("requests"):
            st.markdown("**API requests (sanitised)**")
            st.json(debug["requests"])
        if debug.get("response_summary"):
            st.markdown("**Response summary**")
            st.json(debug["response_summary"])
        if debug.get("exception"):
            st.markdown("**Exception details**")
            st.json(debug["exception"])
        if debug.get("api"):
            st.caption(f"API: {debug.get('api')} · operation: {debug.get('operation')}")
        if debug.get("notes"):
            st.caption(debug["notes"])
        from core.export import redact_secrets

        st.markdown("**Raw provider response (sanitised)**")
        st.json(redact_secrets(run.raw_response))


def _configuration_form():
    with st.form("grounding-run-form"):
        st.subheader("Test configuration")
        query = st.text_area(
            "Grounding/search phrase",
            placeholder="One phrase per line, or comma-separated",
            help="Enter one or more phrases separated by new lines or commas. Select multiple discovered queries with Use to add them here.",
            height=100,
            key="input_query",
        )
        discovery_url = st.text_input(
            "Optional source URL for query discovery",
            placeholder="https://example.com/page-to-test",
            help=(
                "Used as page context for query generation. When pasted copy is provided below, "
                "the URL is optional but still helps anchor suggestions to the right page."
            ),
        )
        discovery_paste = st.text_area(
            "Or paste visible page copy (skips fetch)",
            placeholder=(
                "Paste what you see on the page — titles, headings, promos, and body copy. "
                "The LLM interprets unstructured paste and ignores addresses, phones, and nav boilerplate."
            ),
            height=160,
            help=(
                "If this field is filled, the app will not download the URL. Paste visible page "
                "copy as you would copy it from the browser; raw HTML also works."
            ),
        )
        discovery_fetch_profile = st.selectbox(
            "URL fetch profile",
            options=list(FETCH_PROFILES.keys()),
            format_func=lambda key: FETCH_PROFILES[key],
            index=0,
            help=(
                "Browser-like requests use a mainstream User-Agent and typical document headers. "
                "Use transparent only if you prefer an identifiable bot string."
            ),
        )
        discovery_count = st.slider(
            "Query suggestions",
            min_value=3,
            max_value=10,
            value=6,
            help="Maximum number of merged suggestions to keep across Gemini and OpenAI.",
        )
        property_count = st.number_input(
            "Number of properties",
            min_value=1,
            max_value=MAX_MONITOR_PROPERTIES,
            value=1,
            step=1,
            help="Monitor up to five URLs or domains, each tagged owned, of interest, or competition.",
        )
        targets: list[Target] = []
        for index in range(int(property_count)):
            st.markdown(f"**Property {index + 1}**")
            cols = st.columns([2, 1, 1])
            with cols[0]:
                prop_value = st.text_input(
                    "URL or domain",
                    key=f"prop_value_{index}",
                    placeholder="fourseasons.com",
                )
            with cols[1]:
                prop_category = st.selectbox(
                    "Category",
                    list(CATEGORY_OPTIONS),
                    key=f"prop_category_{index}",
                )
            with cols[2]:
                prop_match = st.selectbox(
                    "Match mode",
                    list(MATCH_LABELS),
                    key=f"prop_match_{index}",
                )
            detail_cols = st.columns(2)
            with detail_cols[0]:
                prop_label = st.text_input(
                    "Label (optional)",
                    key=f"prop_label_{index}",
                    placeholder="Four Seasons",
                )
            with detail_cols[1]:
                prop_brand = st.text_input(
                    "Brand regex (optional)",
                    key=f"prop_brand_{index}",
                    placeholder=r"\bFour Seasons\b",
                )
            targets.append(
                Target(
                    value=prop_value.strip(),
                    match_mode=MATCH_LABELS[prop_match],
                    label=prop_label.strip(),
                    category=CATEGORY_OPTIONS[prop_category],
                    brand_regex=prop_brand.strip(),
                )
            )
        col1, col2 = st.columns(2)
        with col1:
            market_label = st.selectbox("Country / market", list(MARKETS))
        with col2:
            language_label = st.selectbox("Language", list(LANGUAGES))
        timeout_seconds = st.slider(
            "Per-provider timeout (seconds)",
            min_value=30,
            max_value=180,
            value=90,
            step=15,
            help=(
                "Each provider runs on its own timer. Web search calls often need 60–120 seconds, "
                "especially OpenAI with consulted sources."
            ),
        )
        debug_mode = st.checkbox(
            "Debug mode",
            value=False,
            help=(
                "Capture request payloads, execution traces, response summaries, and raw provider "
                "responses for every provider run. Secrets are still redacted."
            ),
        )
        resolve_citation_redirects = st.checkbox(
            "Resolve Gemini citation redirects",
            value=any(target.match_mode is MatchMode.URL_PREFIX for target in targets),
            help=(
                "Follow Gemini grounding redirect links to obtain the final cited URL. "
                "Recommended for URL prefix matching when annotation titles only show a domain."
            ),
        )

        st.subheader("Providers")
        selected: list[str] = []
        provider_columns = st.columns(2)
        for index, provider in enumerate(PROVIDERS.values()):
            with provider_columns[index % 2]:
                if st.checkbox(provider.name, value=True, key=f"selected_{provider.id}"):
                    selected.append(provider.id)

        st.subheader("Provider credentials / configuration")
        st.caption("Secrets remain in this Streamlit process and are never included in exports.")
        render_credentials_help()
        configs: dict[str, dict[str, str]] = {}
        for provider in PROVIDERS.values():
            with st.expander(provider.name, expanded=False):
                config: dict[str, str] = {}
                for field in provider.fields:
                    config[field.key] = _render_provider_field(provider.id, field)
                configs[provider.id] = config

        discovery_col, run_col = st.columns(2)
        with discovery_col:
            discover_submitted = st.form_submit_button(
                "Discover queries from URL",
                use_container_width=True,
            )
        with run_col:
            run_submitted = st.form_submit_button(
                "Run test",
                type="primary",
                use_container_width=True,
            )
    values = {
        "query": query,
        "targets": targets,
        "market": MARKETS[market_label],
        "language": LANGUAGES[language_label],
        "timeout_seconds": timeout_seconds,
        "debug_mode": debug_mode,
        "resolve_citation_redirects": resolve_citation_redirects,
        "discovery_url": discovery_url.strip(),
        "discovery_paste": discovery_paste.strip(),
        "discovery_fetch_profile": discovery_fetch_profile,
        "discovery_count": discovery_count,
    }
    action = "discover" if discover_submitted else "run" if run_submitted else None
    return action, values, selected, configs


def _start_query_discovery(
    values,
    configs: dict[str, dict[str, str]],
) -> QueryDiscoveryResult | None:
    if not values["discovery_url"] and not values.get("discovery_paste"):
        st.error("Enter a source URL to fetch, or paste page HTML/text below.")
        return None
    status = st.empty()
    if values.get("discovery_paste"):
        status.info("⟳ Query discovery — analysing pasted page copy")
    else:
        status.info("⟳ Query discovery — fetching and analysing page")
    accept_language = values.get("market") or values.get("language") or "en-GB"
    try:
        discovery = call_discover_queries(
            values["discovery_url"],
            openai_config=configs.get("openai_web"),
            gemini_config=configs.get("gemini"),
            count=values["discovery_count"],
            debug=values["debug_mode"],
            page_content=values.get("discovery_paste") or None,
            fetch_profile=values.get("discovery_fetch_profile") or DEFAULT_FETCH_PROFILE,
            accept_language=accept_language,
        )
    except QueryDiscoveryCompatibilityError as exc:
        st.error(str(exc))
        return None
    st.session_state["query_discovery"] = discovery
    st.session_state["selected_discovery_queries"] = []
    for index in range(len(discovery.candidates)):
        st.session_state.pop(f"discover_pick_{index}", None)
    st.session_state["grounding_runs"] = []
    st.session_state.pop("grounding_request", None)
    if discovery.candidates:
        status.success(
            f"✓ Query discovery — {len(discovery.candidates)} suggestions generated"
        )
    else:
        status.error(
            f"Query discovery — {discovery.error or 'No suggestions were generated.'}"
        )
    return discovery


def _start_run(values, selected: list[str], configs: dict[str, dict[str, str]]) -> None:
    try:
        targets = validate_targets(values["targets"])
    except ValueError as exc:
        st.error(str(exc))
        return
    if not selected:
        st.error("Select at least one provider.")
        return

    phrases = split_input_phrases(values["query"])
    if values["discovery_url"] or values.get("discovery_paste"):
        discovery = _start_query_discovery(values, configs)
        if discovery and discovery.candidates and not phrases:
            phrases = [discovery.candidates[0].query]
            st.session_state["input_query"] = phrases[0]
        if not phrases:
            st.error(
                "Enter a grounding/search phrase, or provide page content that yields "
                "query suggestions."
            )
            return
    elif not phrases:
        st.error("Enter a grounding/search phrase.")
        return

    all_runs: list[GroundingRun] = []
    last_request: GroundingRequest | None = None
    st.subheader("Running test")
    statuses = {provider_id: st.empty() for provider_id in selected}
    matrix_placeholder = st.empty()

    for phrase_index, phrase in enumerate(phrases):
        if len(phrases) > 1:
            st.markdown(f"**Phrase {phrase_index + 1} of {len(phrases)}:** `{phrase}`")
        request = GroundingRequest(
            run_id=str(uuid4()),
            input_phrase=phrase,
            targets=targets,
            market=values["market"],
            language=values["language"],
            provider_options={
                "timeout_seconds": values["timeout_seconds"],
                "debug_mode": values["debug_mode"],
                "resolve_citation_redirects": values["resolve_citation_redirects"],
            },
            queries=[phrase],
        )
        last_request = request
        jobs = [(PROVIDERS[provider_id], configs[provider_id]) for provider_id in selected]
        completed: dict[str, GroundingRun] = {}
        for provider_id in selected:
            statuses[provider_id].info(f"⟳ {PROVIDERS[provider_id].name} — running `{phrase}`")
        for run in execute_providers(request, jobs):
            completed[run.provider_id] = run
            all_runs.append(run)
            if run.status.value == "complete":
                statuses[run.provider_id].success(
                    f"✓ {run.provider_name} — {((run.latency_ms or 0) / 1000):.1f}s · `{phrase}`"
                )
            else:
                message = run.error.safe_message if run.error else run.status.value
                statuses[run.provider_id].error(f"{run.provider_name} — {message} · `{phrase}`")
        ordered = [completed[item] for item in selected if item in completed]
        matrix_placeholder.dataframe(
            _property_matrix_data(ordered, targets),
            use_container_width=True,
            hide_index=True,
        )

    st.session_state["grounding_request"] = last_request
    st.session_state["grounding_runs"] = all_runs
    st.session_state["grounding_phrases"] = phrases


def _sync_selected_discovery_queries() -> None:
    discovery = st.session_state.get("query_discovery")
    if not discovery:
        return
    selected: list[str] = []
    for index, item in enumerate(discovery.candidates):
        if st.session_state.get(f"discover_pick_{index}", False):
            selected.append(item.query)
    st.session_state["selected_discovery_queries"] = selected
    st.session_state["input_query"] = "\n".join(selected)


def _render_results(request: GroundingRequest, runs: list[GroundingRun]) -> None:
    st.divider()
    st.header("Results")
    st.caption(f"Run ID: {request.run_id}")
    discovery = st.session_state.get("query_discovery")
    if discovery:
        _render_query_discovery(discovery)
    phrases = st.session_state.get("grounding_phrases") or sorted({run.input_phrase for run in runs})
    st.subheader("Property comparison matrix")
    st.caption(
        "Each row is a monitored property. Columns show retrieved, cited, and brand mention "
        "states per provider. UNKNOWN is not NO."
    )
    if len(phrases) > 1:
        for phrase in phrases:
            phrase_runs = [run for run in runs if run.input_phrase == phrase]
            st.markdown(f"**Phrase:** `{phrase}`")
            st.dataframe(
                _property_matrix_data(phrase_runs, request.targets),
                use_container_width=True,
                hide_index=True,
            )
            st.markdown("**Provider overview**")
            st.dataframe(_matrix_data(phrase_runs), use_container_width=True, hide_index=True)
            st.markdown("**Provider evidence**")
            debug_mode = _debug_mode_enabled(request)
            for run in phrase_runs:
                _provider_details(run, debug_mode=debug_mode)
    else:
        st.dataframe(
            _property_matrix_data(runs, request.targets),
            use_container_width=True,
            hide_index=True,
        )

        st.subheader("Provider overview")
        st.dataframe(_matrix_data(runs), use_container_width=True, hide_index=True)

        st.subheader("Provider evidence")
        debug_mode = _debug_mode_enabled(request)
        if debug_mode:
            st.caption("Debug mode is on — each provider includes an expanded debug trace.")
        for run in runs:
            _provider_details(run, debug_mode=debug_mode)

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


def _render_query_discovery(discovery: QueryDiscoveryResult) -> None:
    st.subheader("URL query discovery")
    if discovery.error:
        st.warning(discovery.error)
    if discovery.evidence:
        evidence = discovery.evidence
        source_note = (
            "Pasted page copy"
            if evidence.input_source == "paste"
            else f"Fetched ({evidence.fetch_profile or 'browser'} profile)"
        )
        st.caption(
            f"{source_note} · {evidence.final_url or evidence.requested_url} · "
            f"{evidence.downloaded_bytes:,} bytes · {len(evidence.chunks)} DOM chunks selected"
        )
        if evidence.key_terms:
            st.caption(f"Distinctive terms: {', '.join(evidence.key_terms)}")
    if discovery.candidates:
        st.dataframe(
            [
                {
                    "Query": item.query,
                    "Why this page fits": item.rationale,
                    "DOM evidence": item.evidence,
                    "Generated by": ", ".join(item.generators),
                }
                for item in discovery.candidates
            ],
            hide_index=True,
            use_container_width=True,
        )
        st.caption(
            "Use toggles selection. Selected queries are added to the search phrase box, "
            "one per line. Run the test to check every line or comma-separated phrase."
        )
        for index, item in enumerate(discovery.candidates):
            st.checkbox(
                item.query,
                key=f"discover_pick_{index}",
                on_change=_sync_selected_discovery_queries,
            )
            if item.rationale:
                st.caption(item.rationale)

    with st.expander("Page evidence"):
        if not discovery.evidence:
            st.info("No page evidence was extracted.")
        else:
            evidence = discovery.evidence
            st.write(
                {
                    "requested_url": evidence.requested_url,
                    "final_url": evidence.final_url,
                    "canonical_url": evidence.canonical_url,
                    "title": evidence.title,
                    "description": evidence.description,
                    "language": evidence.language,
                    "input_source": evidence.input_source,
                    "fetch_profile": evidence.fetch_profile,
                    "key_terms": evidence.key_terms,
                    "http_status": evidence.http_status,
                    "content_type": evidence.content_type,
                    "downloaded_bytes": evidence.downloaded_bytes,
                    "redirects": evidence.redirects,
                }
            )
            st.dataframe(
                [
                    {"Kind": chunk.kind, "Score": chunk.score, "Text": chunk.text}
                    for chunk in evidence.chunks
                ],
                hide_index=True,
                use_container_width=True,
            )

    st.markdown("#### Query generators")
    if discovery.generators:
        st.dataframe(
            [
                {
                    "Provider": item.provider_name,
                    "Model": item.model,
                    "Status": item.status,
                    "Suggestions": len(item.queries),
                    "Latency (ms)": item.latency_ms,
                    "Error": item.error,
                }
                for item in discovery.generators
            ],
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.info("No query-generation API was called.")

    st.download_button(
        "Download query suggestions JSON",
        json.dumps(
            discovery.to_dict(include_raw=False),
            indent=2,
            ensure_ascii=False,
        ),
        file_name="query-discovery.json",
        mime="application/json",
    )

    if discovery.debug_mode:
        with st.expander("Query discovery debug", expanded=True):
            if discovery.debug:
                st.markdown("**Discovery diagnostics**")
                st.json(discovery.debug)
            if discovery.evidence:
                st.markdown("**Fetch diagnostics**")
                st.json(
                    {
                        "requested_url": discovery.evidence.requested_url,
                        "final_url": discovery.evidence.final_url,
                        "redirects": discovery.evidence.redirects,
                        "resolved_addresses": discovery.evidence.resolved_addresses,
                        "request_headers": discovery.evidence.request_headers,
                        "response_headers": discovery.evidence.response_headers,
                        "http_status": discovery.evidence.http_status,
                        "content_type": discovery.evidence.content_type,
                        "downloaded_bytes": discovery.evidence.downloaded_bytes,
                    }
                )
            for generator in discovery.generators:
                st.markdown(f"**{generator.provider_name} / {generator.model}**")
                st.json(generator.debug)
                if generator.raw_response is not None:
                    from core.export import redact_secrets

                    st.markdown("Raw response (sanitised)")
                    st.json(redact_secrets(generator.raw_response))
            st.download_button(
                "Download query discovery debug JSON",
                json.dumps(
                    discovery.to_dict(include_raw=True),
                    indent=2,
                    ensure_ascii=False,
                ),
                file_name="query-discovery-debug.json",
                mime="application/json",
            )


def _property_result_for(run: GroundingRun, target_value: str) -> dict[str, object] | None:
    props = run.metadata.get("property_results") or []
    return next((item for item in props if item.get("value") == target_value), None)


def _property_matrix_data(runs: list[GroundingRun], targets: list[Target]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for target in targets:
        row: dict[str, object] = {
            "Property": display_label(target),
            "Category": CATEGORY_LABELS[target.category],
        }
        for run in runs:
            prefix = run.provider_name
            match = _property_result_for(run, target.value)
            if match:
                row[f"{prefix} · retrieved"] = str(match.get("retrieved", "?")).upper()
                row[f"{prefix} · cited"] = str(match.get("cited", "?")).upper()
                row[f"{prefix} · brand"] = str(match.get("brandMentioned", "?")).upper()
            else:
                row[f"{prefix} · retrieved"] = STATE_LABELS[run.target_retrieved]
                row[f"{prefix} · cited"] = STATE_LABELS[run.target_cited]
                row[f"{prefix} · brand"] = "N/A"
        rows.append(row)
    return pd.DataFrame(rows)


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


def _partition_sources(sources):
    opened = [
        item for item in sources if item.metadata.get("source_origin") == "open_page"
    ]
    listed = [
        item for item in sources if item.metadata.get("source_origin") != "open_page"
    ]
    return opened, listed


def _source_table_rows(sources):
    return [
        {
            "Order": item.retrieval_position,
            "Origin": item.metadata.get("source_origin", "source_list"),
            "Domain": item.registrable_domain,
            "URL": item.raw_url,
            "Title": item.title,
            "Call status": item.metadata.get("call_status"),
            "Properties matched": ", ".join(item.target_matches) or "—",
            "Retrieved": STATE_LABELS[item.retrieved],
            "Cited in answer": STATE_LABELS[item.cited],
        }
        for item in sources
    ]


def _provider_details(run: GroundingRun, *, debug_mode: bool = False) -> None:
    with st.expander(run.provider_name):
        st.markdown("#### Summary")
        summary = {
            "status": run.status.value,
            "model": run.model,
            "api_version": run.api_version,
            "latency_ms": run.latency_ms,
            "search_performed": STATE_LABELS[run.search_performed],
            "target_retrieved": STATE_LABELS[run.target_retrieved],
            "target_cited": STATE_LABELS[run.target_cited],
        }
        st.write(summary)
        property_rows = run.metadata.get("property_results") or []
        if property_rows:
            st.markdown("#### Property results")
            st.dataframe(
                [
                    {
                        "Property": item.get("label") or item.get("value"),
                        "Category": CATEGORY_LABELS.get(
                            TargetCategory(str(item.get("category", TargetCategory.OWNED.value))),
                            str(item.get("category", "")),
                        ),
                        "Retrieved": str(item.get("retrieved", "?")).upper(),
                        "Cited": str(item.get("cited", "?")).upper(),
                        "Brand": str(item.get("brandMentioned", "?")).upper(),
                    }
                    for item in property_rows
                ],
                hide_index=True,
                use_container_width=True,
            )
        if run.error:
            st.error(run.error.safe_message)
            error_details = run.metadata.get("error_details")
            if error_details:
                with st.expander("API error details"):
                    st.json(error_details)
            if run.status.value == "timed_out":
                timeout = run.metadata.get("timeout_seconds")
                retries = run.metadata.get("retry_count")
                st.caption(
                    f"Timed out after {run.latency_ms} ms"
                    + (f" (configured limit: {timeout:g}s)" if timeout else "")
                    + (f"; retries attempted: {retries}" if retries else "")
                    + ". Web search providers often need 90–120 seconds."
                )

        state_notes = run.metadata.get("state_notes") or build_state_notes(run)
        unknown_fields = unknown_observation_fields(run)
        if unknown_fields or any(
            getattr(run, field) in {ObservationState.NO, ObservationState.NOT_APPLICABLE}
            for field, _ in (
                ("search_performed", "Search performed"),
                ("target_retrieved", "Target retrieved"),
                ("target_cited", "Target cited"),
            )
        ):
            st.markdown("#### Why these states?")
            if unknown_fields:
                st.warning(
                    "One or more observation states are UNKNOWN. UNKNOWN does not mean NO — "
                    "it means the provider response did not expose enough evidence to decide."
                )
            for field, label in (
                ("search_performed", "Search performed"),
                ("target_retrieved", "Target retrieved"),
                ("target_cited", "Target cited"),
            ):
                note = state_notes.get(field)
                if note:
                    st.info(f"**{label} ({STATE_LABELS[getattr(run, field)]})** — {note}")

        st.markdown("#### Generated queries")
        if run.generated_queries:
            st.caption(
                "Queries emitted by the provider's search tool. Internal `ws_call_id` suffixes "
                "are stripped when present."
            )
            st.dataframe(
                [
                    {
                        "Sequence": item.sequence,
                        "Query": extract_query_text(item.query) or item.query,
                        "Action": item.metadata.get("action_type"),
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

        opened_pages, listed_sources = _partition_sources(run.sources)

        st.markdown("#### Opened pages")
        st.caption(
            "Pages the search tool opened during the run. These are retrieval/tool evidence "
            "and are not the same as inline URL citations in the final answer."
        )
        if opened_pages:
            st.dataframe(
                _source_table_rows(opened_pages),
                column_config={"URL": st.column_config.LinkColumn("URL")},
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info("No `open_page` URLs were exposed in the provider response.")

        st.markdown("#### Consulted source URLs")
        st.caption(
            "URLs returned in explicit consulted-source lists such as "
            "`web_search_call.action.sources` when the provider exposes them."
        )
        if listed_sources:
            st.dataframe(
                _source_table_rows(listed_sources),
                column_config={"URL": st.column_config.LinkColumn("URL")},
                hide_index=True,
                use_container_width=True,
            )
        elif not opened_pages:
            st.info(
                state_notes.get("target_retrieved")
                or run.metadata.get("retrieval_note")
                or "No retrieved-source list was exposed by this provider/API."
            )
        else:
            st.info(
                "No explicit consulted-source list was returned. Use Opened pages above for "
                "tool-level URL evidence."
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
                        "Resolved URL": item.metadata.get("resolved_url"),
                        "Title": item.title,
                        "Start": item.start_index,
                        "End": item.end_index,
                        "Cited text": item.cited_text,
                        "Properties matched": ", ".join(item.target_matches) or "—",
                        "Redirect resolution": item.metadata.get("redirect_resolution"),
                    }
                    for item in run.citations
                ],
                column_config={"URL": st.column_config.LinkColumn("URL")},
                hide_index=True,
                use_container_width=True,
            )
        else:
            st.info(
                "No inline URL citations were exposed in the final answer. Check Opened pages "
                "above if the provider opened target URLs during search."
            )
        anchor_references = run.metadata.get("anchor_references") or []
        if anchor_references:
            st.markdown("#### Anchor references without URLs")
            st.caption(
                "Some providers return inline anchor text or titles without exposing the "
                "underlying citation URL. These cannot be used for target-domain matching."
            )
            st.dataframe(anchor_references, hide_index=True, use_container_width=True)

        st.markdown("#### Final response")
        st.text(run.response_text or "No final response text was exposed.")
        suggestions = run.metadata.get("search_suggestions") or []
        if run.provider_id == "gemini" and suggestions:
            st.markdown("#### Google Search suggestions")
            st.caption(
                "Rendered in isolated iframes using the exact provider-supplied "
                "Search Suggestions markup."
            )
            for markup in suggestions:
                st.components.v1.html(markup, height=80, scrolling=False)
        with st.expander("Provider metadata"):
            st.json(run.metadata)
        if debug_mode:
            _render_debug_panel(run, expanded=True)
        elif st.checkbox(
            "Show sanitised raw response",
            key=f"raw_{run.run_id}_{run.provider_id}",
        ):
            from core.export import redact_secrets

            st.json(redact_secrets(run.raw_response))


def _methodology_help() -> None:
    with st.expander("How to read these results"):
        st.markdown(
            """
- Citation presence is not the same as retrieval presence.
- **UNKNOWN does not mean NO**: some providers do not expose their retrieved result set.
- **Target retrieved** uses four states, not two:
  - **YES** — the provider returned a consulted-source list and your target domain appears in it.
  - **NO** — the provider returned a complete consulted-source list and your target is absent.
  - **UNKNOWN** — search may have run, but the API did not expose enough retrieval evidence to
    prove YES or NO (for example Gemini citations without a SERP list, or Bing without raw
    grounding output).
  - **N/A** — retrieval is not applicable for that provider type.
- **Target cited** also requires an exposed **citation URL**. Anchor text or page titles alone
  are shown separately and do not count as URL citations.
- Source, retrieval, and citation order must not be treated as conventional organic rank.
- Provider and model choices can change results, and grounding runs are inherently variable.
"""
        )


if __name__ == "__main__":
    main()
