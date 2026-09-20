"""Local research UI; all application state comes from the loopback API."""

# ruff: noqa: E501, RUF001

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from datetime import date
from urllib.parse import urlsplit

import httpx
import streamlit as st

_DEFAULT_API = "http://127.0.0.1:8000"
_SOURCES = ("pubmed", "dailymed", "faers", "cadec")
_RUN_ID = re.compile(r"run:[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}\Z")
_REPORT_ID = re.compile(r"report:sha256:[0-9a-f]{64}\Z")
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_MAX_EXPORT_BYTES = 2_097_152
_ERROR_TEXT = {
    "invalid_request": "The API rejected the request. Check the terms and selected sources.",
    "not_found": "This run is no longer available.",
    "conflict": "The report state changed. Refresh it before trying again.",
    "unavailable": "The research service is unavailable. Retry when it is running.",
    "invalid_application_result": "The service returned an invalid result.",
    "internal_error": "The research service encountered an error.",
}


def _api_base() -> str | None:
    raw = os.environ.get("MEDEVIDENCE_API_BASE", _DEFAULT_API)
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or port is None
        or not 1 <= port <= 65535
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return raw.rstrip("/")


def _client(base: str) -> httpx.Client:
    return httpx.Client(
        base_url=base,
        trust_env=False,
        follow_redirects=False,
        # A first report read after restart re-verifies the approved local corpus.
        timeout=httpx.Timeout(connect=2.0, read=90.0, write=2.0, pool=2.0),
    )


def _error(response: httpx.Response) -> str:
    try:
        body = response.json()
        code = body.get("error", {}).get("code") if isinstance(body, dict) else None
    except ValueError:
        code = None
    return _ERROR_TEXT.get(
        code if isinstance(code, str) else "",
        f"The research service returned HTTP {response.status_code}.",
    )


def _request_json(
    base: str,
    method: str,
    path: str,
    *,
    payload: dict[str, object] | None = None,
    params: dict[str, str | int] | None = None,
) -> tuple[dict[str, object] | None, str | None]:
    try:
        with _client(base) as client:
            response = client.request(method, path, json=payload, params=params)
    except (httpx.RequestError, OSError):
        return None, "Cannot reach the local research service. Check that the API is running."
    if response.status_code not in {200, 202}:
        return None, _error(response)
    if len(response.content) > _MAX_EXPORT_BYTES:
        return None, "The service response exceeds the display limit."
    try:
        body = response.json()
    except ValueError:
        return None, "The service returned invalid JSON."
    if not isinstance(body, dict):
        return None, "The service returned an unexpected response."
    return body, None


def _canonical(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _digest(value: object) -> str:
    return "sha256:" + hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _terms(raw: str, *, maximum: int, label: str) -> list[str]:
    values = [item.strip() for item in raw.splitlines() if item.strip()]
    if not 1 <= len(values) <= maximum:
        raise ValueError(f"Enter 1–{maximum} {label}, one per line.")
    if len({item.casefold() for item in values}) != len(values):
        raise ValueError(f"Remove duplicate {label}.")
    if any(
        len(item) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in item)
        for item in values
    ):
        raise ValueError(f"Each {label} must be a single line of at most 512 characters.")
    return values


def _concept(kind: str, term: str) -> dict[str, str]:
    identity = hashlib.sha256((kind + "\0" + term.casefold()).encode("utf-8")).hexdigest()
    return {"concept_id": f"input-{kind}:{identity}", "preferred_term": term}


def _scope(
    drugs_raw: str,
    reactions_raw: str,
    sources: list[str],
    intent: str,
    date_enabled: bool,
    start: date,
    end: date,
) -> dict[str, object]:
    drugs = sorted(
        (_concept("drug", value) for value in _terms(drugs_raw, maximum=4, label="drugs")),
        key=lambda item: item["concept_id"],
    )
    reactions = sorted(
        (
            _concept("reaction", value)
            for value in _terms(reactions_raw, maximum=8, label="reactions")
        ),
        key=lambda item: item["concept_id"],
    )
    if not sources or len(set(sources)) != len(sources) or not set(sources).issubset(_SOURCES):
        raise ValueError("Choose at least one approved source.")
    if intent not in {"compare", "summarize"}:
        raise ValueError("Choose a valid research intent.")
    if date_enabled and start > end:
        raise ValueError("The start date must be on or before the end date.")
    content: dict[str, object] = {
        "schema_version": "1.0",
        "drugs": drugs,
        "adverse_reactions": reactions,
        "date_range": (
            {"start_date": start.isoformat(), "end_date": end.isoformat(), "precision": "day"}
            if date_enabled
            else None
        ),
        "selected_sources": sorted(sources),
        "language": "en",
        "comparison_intent": intent,
        "query_bounds": {"max_query_characters": 512, "max_pages": 5, "max_total_seconds": 60},
        "result_bounds": {"max_records": 100, "max_payload_bytes": 5_242_880},
    }
    return {"scope_id": "scope:" + _digest(content), **content}


def _submission_key(scope_id: str) -> str:
    if st.session_state.get("submission_scope_id") != scope_id:
        st.session_state["submission_scope_id"] = scope_id
        st.session_state["submission_key"] = "sha256:" + secrets.token_hex(32)
    return str(st.session_state["submission_key"])


def _safe_source_url(raw: object) -> str | None:
    if (
        not isinstance(raw, str)
        or len(raw) > 2048
        or any(ord(char) < 33 or ord(char) == 127 for char in raw)
        or any(char in raw for char in "<>\"'\\")
    ):
        return None
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or port == 0
        or parsed.fragment
        or "\\" in raw
    ):
        return None
    return raw


def _text(value: object) -> None:
    st.text("Not available" if value is None else str(value))


def _items(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _coverage(row: dict[str, object]) -> None:
    source = row.get("source", "unknown source")
    execution, coverage, result = (
        row.get("execution_status"),
        row.get("coverage_status"),
        row.get("result_status"),
    )
    if execution == "succeeded" and coverage == "complete" and result == "no_match":
        meaning = "Complete bounded search: no match."
    elif coverage == "partial" and result == "matches":
        meaning = "Partial coverage: retained matches are not exhaustive."
    elif execution == "succeeded" and coverage == "complete" and result == "matches":
        meaning = "Complete bounded search: matches retained."
    elif not row.get("selected_for_execution", True):
        meaning = "Not executed; consult the bound source plan."
    else:
        meaning = "Indeterminate coverage: zero retained results do not prove absence."
    _text(f"{source} · {meaning}")
    _text(
        f"Execution: {execution or 'not executed'} · Coverage: {coverage or 'unknown'} · Result: {result or 'indeterminate'}"
    )
    _text(
        f"Query: {row.get('query_id') or 'none'} · Records: {row.get('valid_result_count') if row.get('valid_result_count') is not None else 'unknown'} · Retrieved: {row.get('retrieval_as_of') or 'not available'}"
    )
    for warning in _items(row.get("warning_codes")):
        _text(f"Warning: {warning}")


def _report(document: dict[str, object]) -> None:
    st.subheader("Evidence report draft")
    st.info(
        "Research assistance only. No diagnosis, treatment, dosage, individual medical advice, or product-safety ranking."
    )
    _text(
        f"Generated: {document.get('generated_at') or 'not available'} · Retrieved as of: {document.get('retrieval_as_of') or 'not available'}"
    )
    st.markdown("#### Source coverage")
    rows = document.get("coverage", [])
    if isinstance(rows, list) and rows:
        for row in rows:
            if isinstance(row, dict):
                _coverage(row)
    else:
        st.warning("No source coverage rows were supplied for this draft.")
    st.markdown("#### Claims and citations")
    claims = document.get("claims", [])
    if isinstance(claims, list) and claims:
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            _text(
                f"Claim {claim.get('claim_id') or 'unknown'} · {claim.get('source') or 'unknown source'}"
            )
            _text(claim.get("statement"))
            for citation in _items(claim.get("citations")):
                if not isinstance(citation, dict):
                    continue
                _text(
                    f"Citation {citation.get('citation_id') or 'unknown'} · {citation.get('relationship') or 'unknown'}"
                )
                _text(
                    f"Record: {citation.get('source_record_id') or 'unknown'} · Version: {citation.get('source_version') or 'unknown'}"
                )
                _text(
                    f"Locator: {citation.get('exact_locator') or 'unknown'} · Snapshot: {citation.get('snapshot_id') or 'unknown'}"
                )
                _text(
                    f"Content hash: {citation.get('content_hash') or 'unknown'} · Retrieved: {citation.get('retrieved_at') or 'unknown'}"
                )
                url = _safe_source_url(citation.get("source_url"))
                if url:
                    st.link_button(
                        "Open cited source", url, key=f"source_{citation.get('citation_id')}"
                    )
                elif citation.get("lookup_key"):
                    _text(f"Lookup key: {citation['lookup_key']}")
            for limitation in _items(claim.get("limitations")):
                _text(f"Limitation: {limitation}")
    else:
        st.info("No formal claims were accepted for this report.")
    st.markdown("#### Comparisons and conflicts")
    for comparison in _items(document.get("comparisons")):
        if isinstance(comparison, dict):
            _text(f"Comparison {comparison.get('comparison_id')}: {comparison.get('relation')}")
            for dimension in _items(comparison.get("dimensions")):
                if isinstance(dimension, dict):
                    _text(
                        f"{dimension.get('dimension')}: {dimension.get('left_value')} / {dimension.get('right_value')} (applicable: {dimension.get('applicable')})"
                    )
    for conflict in _items(document.get("conflicts")):
        if isinstance(conflict, dict):
            _text(f"Conflict {conflict.get('conflict_id')}: {conflict.get('outcome')}")
    st.markdown("#### Limitations and warnings")
    for item in _items(document.get("limitations")):
        _text(item)
    for code in _items(document.get("warning_codes")):
        _text(f"Warning code: {code}")


def _review(base: str, run: dict[str, object], document: dict[str, object]) -> None:
    st.subheader("Human export review")
    required = (
        "run_id",
        "report_id",
        "report_content_hash",
        "render_document_hash",
        "pending_draft_id",
        "destination_id",
    )
    if any(not isinstance(run.get(field), str) for field in required):
        st.error("The run lacks required review bindings. Refresh before reviewing.")
        return
    if (
        document.get("run_id") != run["run_id"]
        or document.get("scope_id") != run.get("scope_id")
        or document.get("report_id") != run["report_id"]
        or document.get("report_content_hash") != run["report_content_hash"]
        or document.get("render_document_hash") != run["render_document_hash"]
    ):
        st.error("The report draft differs from the current run. Refresh before reviewing.")
        return
    for field in required:
        _text(f"{field.replace('_', ' ').title()}: {run[field]}")
    _text("Material warnings: " + ", ".join(str(code) for code in _items(run.get("warning_codes"))))
    st.warning(
        "Approval permits export of this exact draft. Review its coverage, citations, conflicts, and limitations first."
    )
    reviewer = st.text_input(
        "Local reviewer ID", value="local-reviewer:researcher", key="reviewer_id"
    )
    acknowledged = st.checkbox("I reviewed this exact draft and its limitations", key="review_ack")
    decision = None
    left, middle, right = st.columns(3)
    with left:
        if st.button("Approve export", key="approve_export"):
            decision = "approve"
    with middle:
        if st.button("Request edit", key="request_edit"):
            decision = "edit"
    with right:
        if st.button("Reject report", key="reject_report"):
            decision = "reject"
    if decision is None:
        return
    if decision == "approve" and not acknowledged:
        st.error("Confirm that you reviewed this exact draft before approving export.")
        return
    if not re.fullmatch(r"local-reviewer:[a-z0-9][a-z0-9_-]{0,63}", reviewer):
        st.error("Enter a valid local reviewer ID.")
        return
    binding = (*[run[field] for field in required], decision, reviewer)
    if st.session_state.get("review_binding") != binding:
        st.session_state["review_binding"] = binding
        st.session_state["review_key"] = "sha256:" + secrets.token_hex(32)
    command = {
        "schema_version": "m3.research-review-command.v1",
        **{field: run[field] for field in required},
        "reviewer_id": reviewer,
        "decision": decision,
        "idempotency_key": st.session_state["review_key"],
    }
    result, error = _request_json(
        base, "POST", f"/v1/research/runs/{run['run_id']}/review", payload=command
    )
    if error:
        st.error(error)
    elif result and result.get("run_id") == run["run_id"]:
        st.session_state["active_run_id"] = run["run_id"]
        st.success(f"Review decision recorded. Current status: {result.get('status', 'unknown')}.")
    else:
        st.error("The review response did not match this run. Refresh its status.")


def _prepare_export(
    base: str, run: dict[str, object], format_name: str
) -> tuple[bytes | None, str | None]:
    run_id = run.get("run_id")
    if (
        run.get("status") != "exported"
        or not isinstance(run_id, str)
        or not _RUN_ID.fullmatch(run_id)
    ):
        return None, "This run has no approved export to download."
    try:
        with _client(base) as client:
            response = client.get(
                f"/v1/research/runs/{run_id}/export", params={"format": format_name}
            )
    except (httpx.RequestError, OSError):
        return None, "Cannot reach the local research service. Retry the download."
    if response.status_code != 200:
        return None, _error(response)
    content = response.content
    expected = response.headers.get("X-Content-SHA256", "")
    actual = "sha256:" + hashlib.sha256(content).hexdigest()
    expected_type = "application/json" if format_name == "json" else "text/markdown"
    returned_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
    if (
        not 0 < len(content) <= _MAX_EXPORT_BYTES
        or not _DIGEST.fullmatch(expected)
        or actual != expected
        or expected_type != returned_type
    ):
        return None, "The export failed its content or format check."
    return content, None


def main() -> None:
    st.set_page_config(page_title="MedEvidence | Research workspace", page_icon="🔎", layout="wide")
    st.title("MedEvidence")
    st.caption("A local workspace for traceable drug-safety research")
    st.info(
        "Research assistance only. This application does not provide diagnosis, treatment, dosage, emergency guidance, or individual medical advice."
    )
    base = _api_base()
    if base is None:
        st.error("MEDEVIDENCE_API_BASE must be a loopback HTTP address with an explicit port.")
        st.stop()
    form_column, results_column = st.columns([2, 3], gap="large")
    with form_column:
        st.subheader("Start a research run")
        st.caption("Search terms are used as entered; no medical vocabulary mapping is implied.")
        date_enabled = st.checkbox("Limit to a date range", key="date_enabled")
        st.caption(
            "DailyMed searches current labels; deselect it to use a date range. "
            "FAERS supports up to 366 calendar dates. Without a date range, "
            "FAERS uses the 366 dates ending on the run's creation date."
        )
        with st.form("research_form"):
            drugs_raw = st.text_area(
                "Drugs · one per line (1–4)", "Semaglutide\nTirzepatide", key="drugs"
            )
            reactions_raw = st.text_area(
                "Adverse reactions · one per line (1–8)",
                "Nausea\nVomiting\nDiarrhoea",
                key="reactions",
            )
            sources = st.multiselect(
                "Sources",
                options=list(_SOURCES),
                default=["pubmed", "dailymed", "faers"],
                key="sources",
            )
            intent = st.selectbox("Research intent", ["compare", "summarize"], key="intent")
            start, end = date(2020, 1, 1), date.today()
            if date_enabled:
                start_column, end_column = st.columns(2)
                with start_column:
                    start = st.date_input("Start date", value=start, key="start_date")
                with end_column:
                    end = st.date_input("End date", value=end, key="end_date")
            submitted = st.form_submit_button(
                "Start research", key="submit_research", use_container_width=True
            )
        if submitted:
            try:
                scope = _scope(drugs_raw, reactions_raw, sources, intent, date_enabled, start, end)
            except ValueError as scope_error:
                st.error(str(scope_error))
            else:
                command: dict[str, object] = {
                    "schema_version": "m3.research-submission.v1",
                    "scope": scope,
                    "idempotency_key": _submission_key(str(scope["scope_id"])),
                }
                result, error = _request_json(base, "POST", "/v1/research/runs", payload=command)
                if error:
                    st.error(error)
                elif (
                    result
                    and result.get("scope_id") == scope["scope_id"]
                    and isinstance(result.get("run_id"), str)
                ):
                    st.session_state["active_run_id"] = result["run_id"]
                    st.success("Research run accepted. Refresh its status as work progresses.")
                else:
                    st.error("The submission response did not match this research scope.")
    with results_column:
        st.subheader("Recent runs")
        st.button("Refresh status", key="refresh_runs")
        listing, list_error = _request_json(
            base, "GET", "/v1/research/runs", params={"limit": 20, "offset": 0}
        )
        if list_error:
            st.warning(list_error)
            recent: list[dict[str, object]] = []
        else:
            items = listing.get("items", []) if listing else []
            recent = (
                [
                    item
                    for item in items
                    if isinstance(item, dict) and isinstance(item.get("run_id"), str)
                ]
                if isinstance(items, list)
                else []
            )
            if not recent:
                st.caption("No research runs are available yet.")
        active_id = st.session_state.get("active_run_id")
        identifiers = [item["run_id"] for item in recent]
        if isinstance(active_id, str) and active_id not in identifiers:
            identifiers.insert(0, active_id)
        if identifiers:
            chosen = st.selectbox(
                "Inspect run",
                identifiers,
                index=identifiers.index(active_id) if active_id in identifiers else 0,
                key="active_run",
            )
            if chosen != active_id:
                st.session_state["active_run_id"] = chosen
                st.session_state.pop("prepared_export", None)
            active_id = chosen
        if not isinstance(active_id, str) or not _RUN_ID.fullmatch(active_id):
            st.caption("Select a run to inspect its source coverage and review state.")
            return
        run, run_error = _request_json(base, "GET", f"/v1/research/runs/{active_id}")
        if run_error:
            st.error(run_error)
            return
        if not run or run.get("run_id") != active_id:
            st.error("The run response did not match the selected run.")
            return
        st.metric("Run status", str(run.get("status", "unknown")).replace("_", " ").title())
        _text(f"Run ID: {active_id} · Report ID: {run.get('report_id') or 'not available'}")
        for code in _items(run.get("warning_codes")):
            _text(f"Run warning: {code}")
        if run.get("status") in {"submitted", "active", "blocked"}:
            st.info("A report draft is not available yet. Refresh this run when work progresses.")
            return
        report, report_error = _request_json(base, "GET", f"/v1/research/runs/{active_id}/report")
        if report_error:
            st.warning(report_error)
            return
        document = report.get("document") if report else None
        if (
            not isinstance(report, dict)
            or not isinstance(document, dict)
            or not isinstance(report.get("run"), dict)
        ):
            st.warning("The service did not provide an inspectable report draft.")
            return
        report_run = report["run"]
        if (
            not isinstance(report_run, dict)
            or report_run.get("run_id") != active_id
            or report_run.get("report_id") != run.get("report_id")
            or report_run.get("report_content_hash") != run.get("report_content_hash")
            or report_run.get("render_document_hash") != run.get("render_document_hash")
        ):
            st.error("The report belongs to another run.")
            return
        _report(document)
        if run.get("status") == "pending_review":
            _review(base, run, document)
        elif run.get("status") == "exported":
            st.subheader("Approved export")
            format_name = st.selectbox("File format", ["json", "markdown"], key="export_format")
            if st.button("Prepare download", key="prepare_download"):
                content, error = _prepare_export(base, run, format_name)
                if error:
                    st.error(error)
                    st.session_state.pop("prepared_export", None)
                else:
                    st.session_state["prepared_export"] = (
                        active_id,
                        run.get("report_content_hash"),
                        run.get("render_document_hash"),
                        format_name,
                        content,
                    )
            prepared = st.session_state.get("prepared_export")
            if (
                isinstance(prepared, tuple)
                and len(prepared) == 5
                and prepared[:4]
                == (
                    active_id,
                    run.get("report_content_hash"),
                    run.get("render_document_hash"),
                    format_name,
                )
                and isinstance(run.get("report_id"), str)
                and _REPORT_ID.fullmatch(str(run["report_id"]))
            ):
                suffix = str(run["report_id"]).removeprefix("report:sha256:")
                extension = "json" if format_name == "json" else "md"
                st.download_button(
                    "Download approved export",
                    data=prepared[4],
                    file_name=f"medevidence-{suffix}.{extension}",
                    mime="application/json" if format_name == "json" else "text/markdown",
                    key="download_export",
                )
        elif run.get("status") in {"approved", "rejected"}:
            st.info(f"Review state: {run['status']}. Refresh for any later export state.")


main()
