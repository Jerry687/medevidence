from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from evaluation import gold10_v2
from evaluation.gold10_v2 import (
    LIVE_ACKNOWLEDGEMENT,
    M2_003_ROOT,
    MOUNJARO_SETID,
    Gold10V2Error,
    derive_for_safe_parsing,
    reconstruct_retained_pubmed,
    run_live_recovery,
)
from evaluation.run_gold10_v2_acquisition import main

from medevidence.connectors.dailymed.parsing import (
    DailyMedParseError,
    parse_source_native_spl_document,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _synthetic_spl(*, setid: str = MOUNJARO_SETID, extra: bytes = b"") -> bytes:
    return (
        b'<?xml version="1.0" encoding="UTF-8"?>'
        b'<document xmlns="urn:hl7-org:v3" '
        b'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        b'xsi:schemaLocation="urn:hl7-org:v3 https://example.invalid/spl.xsd">'
        b'<setId root="'
        + setid.encode()
        + b'"/><versionNumber value="1"/><component><structuredBody><component><section>'
        b'<code code="34084-4" codeSystem="2.16.840.1.113883.6.1"/>'
        b"<title>6 ADVERSE REACTIONS</title><text>Observed adverse reaction text.</text>"
        b"</section></component></structuredBody></component>" + extra + b"</document>"
    )


def _stylesheet(payload: bytes) -> bytes:
    declaration_end = payload.index(b"?>") + 2
    return (
        payload[:declaration_end]
        + b'<?xml-stylesheet href="https://example.invalid/spl.xsl" type="text/xsl"?>\n'
        + payload[declaration_end:]
    )


class _PartialFailureStream(httpx.SyncByteStream):
    def __iter__(self) -> Any:
        yield b"partial-response"
        raise httpx.ReadError("synthetic partial stream failure")


def test_exact_retained_ozempic_derivative_and_pubmed_reconstruction() -> None:
    if not M2_003_ROOT.exists():
        pytest.skip("external retained M2-003 evidence is unavailable")
    stop_bytes = (M2_003_ROOT / "stop.json").read_bytes()
    assert _sha256(stop_bytes) == gold10_v2.M2_003_STOP_SHA256
    stop = json.loads(stop_bytes)
    pubmed, memberships = reconstruct_retained_pubmed(M2_003_ROOT, stop)
    assert len(pubmed) == 50
    assert len(memberships) == 50
    assert {membership for values in memberships.values() for membership in values} == {
        "pubmed-esearch-1",
        "pubmed-esearch-2",
        "pubmed-esearch-3",
        "pubmed-esearch-4",
    }

    raw_path = next((M2_003_ROOT / "raw" / "dailymed").glob("*.raw"))
    raw = raw_path.read_bytes()
    original = bytes(raw)
    derivative = derive_for_safe_parsing(raw)
    assert raw == original
    assert len(raw) == 627_087
    assert _sha256(raw) == gold10_v2.OZEMPIC_RAW_SHA256
    assert [(step.removed_start, step.removed_end) for step in derivative.lineage] == [
        (38, 133),
        (125, 211),
    ]
    assert [step.removed_bytes for step in derivative.lineage] == [95, 86]
    assert derivative.lineage[0].removed_sha256 == gold10_v2.OZEMPIC_PI_REMOVED_SHA256
    assert derivative.lineage[0].output_sha256 == gold10_v2.OZEMPIC_AFTER_PI_SHA256
    assert derivative.lineage[1].removed_sha256 == gold10_v2.OZEMPIC_SCHEMA_REMOVED_SHA256
    assert len(derivative.payload) == 626_906
    assert _sha256(derivative.payload) == gold10_v2.OZEMPIC_FINAL_SHA256
    assert all(step.exact_splice_equality for step in derivative.lineage)
    parsed = parse_source_native_spl_document(
        derivative.payload,
        expected_setid=gold10_v2.OZEMPIC_SETID,
        expected_spl_version="20",
    )
    assert len(parsed.sections) == 13
    assert sum(section.retrieval_eligible for section in parsed.sections) == 12
    assert sum(section.is_structural_container for section in parsed.sections) == 1


def test_complete_pre_network_candidate_rebinds_every_saved_input(tmp_path: Path) -> None:
    if not M2_003_ROOT.exists():
        pytest.skip("external retained M2-003 evidence is unavailable")
    root = tmp_path / "pre-network"
    result = gold10_v2.prepare_pre_network(root, retained_root=M2_003_ROOT, _allow_test_root=True)
    manifest = gold10_v2._load_and_verify_pre_network(root)
    assert result.pubmed_items == 50
    assert result.ozempic_retrieval_items == 12
    assert result.ozempic_structural_occurrences == 1
    assert (
        manifest["artifact_inventory"]["ozempic_transformation_chain"]["sha256"]
        == manifest["ozempic"]["transformation_chain_sha256"]
    )
    sections = json.loads(
        (root / "ozempic-source-native-sections.json").read_text(encoding="utf-8")
    )
    chain_sha = manifest["ozempic"]["transformation_chain_sha256"]
    assert {
        item["transformation_chain_sha256"]
        for item in [*sections["retrieval_items"], *sections["structural_occurrences"]]
    } == {chain_sha}
    policy_relative = "src/medevidence/connectors/dailymed/policy.py"
    policy_path = Path(gold10_v2.__file__).resolve().parents[1] / policy_relative
    assert manifest["source_state"]["files"][policy_relative] == {
        "bytes": policy_path.stat().st_size,
        "sha256": _sha256(policy_path.read_bytes()),
    }


def test_transform_chain_is_exact_deletion_only_and_raw_is_unchanged() -> None:
    raw = _stylesheet(_synthetic_spl())
    original = bytes(raw)
    result = derive_for_safe_parsing(raw)
    assert raw == original
    assert [step.transformation_id for step in result.lineage] == [
        "strip_xml_stylesheet_pi_v1",
        "strip_root_xsi_schema_location_v1",
    ]
    first = result.lineage[0]
    second = result.lineage[1]
    after_first = raw[: first.removed_start] + raw[first.removed_end :]
    assert _sha256(after_first) == first.output_sha256
    assert result.payload == after_first[: second.removed_start] + after_first[second.removed_end :]
    assert (
        parse_source_native_spl_document(
            result.payload, expected_setid=MOUNJARO_SETID, expected_spl_version="1"
        )
        .sections[0]
        .retrieval_eligible
    )


@pytest.mark.parametrize(
    "payload, message",
    [
        (
            b'<?xml version="1.0"?><?xml-stylesheet href="a"?>'
            b'<?xml-stylesheet href="b"?><document/>',
            "at most once",
        ),
        (b'<?xml version="1.0"?><?xml-stylesheet href="a"<document/>', "unterminated"),
        (b'<?xml version="1.0"?><document><?xml-stylesheet href="a"?></document>', "prolog"),
        (
            b'<?xml version="1.0"?><?audit value="x"?><?xml-stylesheet href="a"?><document/>',
            "another processing instruction",
        ),
    ],
)
def test_ambiguous_or_out_of_prolog_stylesheet_pi_fails(payload: bytes, message: str) -> None:
    with pytest.raises(Gold10V2Error, match=message):
        derive_for_safe_parsing(payload)


def test_repeated_or_non_root_schema_location_fails_closed() -> None:
    repeated = (
        b'<document xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        b'xsi:schemaLocation="a b" xsi:schemaLocation="a b"></document>'
    )
    with pytest.raises(Gold10V2Error, match="repeated"):
        derive_for_safe_parsing(repeated)
    outside = b'<document><child xsi:schemaLocation="a b"/></document>'
    assert derive_for_safe_parsing(outside).lineage == ()


def test_lexical_targets_inside_comment_cdata_or_values_are_not_transformed() -> None:
    payload = (
        b'<document xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        b'data="xsi:schemaLocation=&quot;a b&quot;">'
        b'<!-- <?xml-stylesheet href="ignored"?> -->'
        b'<![CDATA[<?xml-stylesheet href="also-ignored"?> '
        b'xsi:schemaLocation="a b"]]>'
        b'&lt;?xml-stylesheet href="escaped-text"?&gt; '
        b"xsi:schemaLocation=&quot;text value&quot;</document>"
    )
    result = derive_for_safe_parsing(payload)
    assert result.payload == payload
    assert result.lineage == ()


def test_nested_and_near_schema_attributes_are_not_root_transform_targets() -> None:
    nested = (
        b'<document xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        b'<child xsi:schemaLocation="a b"/></document>'
    )
    assert derive_for_safe_parsing(nested).lineage == ()
    near = (
        b'<document xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        b'xsi:schemaLocationExtra="a b"></document>'
    )
    assert derive_for_safe_parsing(near).lineage == ()


def test_near_processing_instruction_and_malformed_root_attribute_fail_closed() -> None:
    with pytest.raises(Gold10V2Error, match="another processing instruction"):
        derive_for_safe_parsing(
            b'<?xml version="1.0"?><?xml-stylesheet-extra href="x"?><document/>'
        )
    with pytest.raises(Gold10V2Error, match="equals"):
        derive_for_safe_parsing(b"<document xsi:schemaLocation></document>")


@pytest.mark.parametrize(
    "unsafe",
    [
        b'<!DOCTYPE document [<!ENTITY x "unsafe">]>',
        b'<xi:include xmlns:xi="http://www.w3.org/2001/XInclude" href="file:///x"/>',
        b'<xsl:stylesheet xmlns:xsl="http://www.w3.org/1999/XSL/Transform"/>',
        b'<xsd:schema xmlns:xsd="http://www.w3.org/2001/XMLSchema"/>',
    ],
)
def test_transform_does_not_rescue_remaining_forbidden_constructs(unsafe: bytes) -> None:
    payload = _stylesheet(_synthetic_spl(extra=unsafe))
    derivative = derive_for_safe_parsing(payload)
    with pytest.raises(DailyMedParseError):
        parse_source_native_spl_document(
            derivative.payload, expected_setid=MOUNJARO_SETID, expected_spl_version="1"
        )


def test_tampered_file_identity_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "artifact.raw"
    path.write_bytes(b"expected")
    with pytest.raises(Gold10V2Error, match="identity mismatch"):
        gold10_v2._verified_bytes(path, expected_bytes=8, expected_sha256="0" * 64)


def test_finalized_chain_hash_is_the_one_bound_to_every_section(tmp_path: Path) -> None:
    raw = _stylesheet(_synthetic_spl())
    derivative = derive_for_safe_parsing(raw)
    derivative_path = tmp_path / "derived" / "safe.xml"
    gold10_v2._write_binary_with_sidecar(derivative_path, derivative.payload)
    chain = gold10_v2._transformation_chain(
        brand="MOUNJARO",
        raw_path="external/provider.raw",
        raw=raw,
        derivative=derivative,
        final_derivative_relative_path="derived/safe.xml",
    )
    chain_path = tmp_path / "chain.json"
    retained_chain_sha = gold10_v2._write_json(chain_path, chain)
    assert json.loads(chain_path.read_text(encoding="utf-8"))["final_derivative"] == {
        "bytes": len(derivative.payload),
        "relative_path": "derived/safe.xml",
        "sha256": _sha256(derivative.payload),
    }
    parsed = parse_source_native_spl_document(
        derivative.payload, expected_setid=MOUNJARO_SETID, expected_spl_version="1"
    )
    retrieval, structural = gold10_v2._section_records(
        parsed,
        brand="MOUNJARO",
        raw_sha256=_sha256(raw),
        transformation_chain_sha256=retained_chain_sha,
        operation_id="test",
    )
    assert {item["transformation_chain_sha256"] for item in [*retrieval, *structural]} == {
        _sha256(chain_path.read_bytes())
    }


def test_review_binding_rejects_stale_manifest_candidate_and_artifact_bytes(
    tmp_path: Path,
) -> None:
    manifest_path = tmp_path / "pre-network-manifest.json"
    manifest = {
        "source_state": {"evaluation/gold10_v2.py": {"bytes": 1, "sha256": "a" * 64}},
        "artifact_inventory": {"artifact": {"bytes": 1, "sha256": "b" * 64}},
    }
    gold10_v2._write_json(manifest_path, manifest)
    binding = gold10_v2._pre_network_review_binding(tmp_path, manifest)
    review = {
        "schema_version": f"{gold10_v2.SCHEMA_VERSION}.pre-network-review.v1",
        "work_item": "M2-005-MEDEVIDENCE-GOLD10-V2",
        "status": "PASS",
        "p0": 0,
        "p1": 0,
        "p2": 0,
        "binding": binding,
    }
    review_path = tmp_path / "review.json"
    review_path.write_bytes(gold10_v2._canonical_json_bytes(review))
    digest = _sha256(review_path.read_bytes())
    assert gold10_v2._verify_review_record(tmp_path, review_path, digest, manifest) == review
    binding["pre_network_manifest"]["sha256"] = "0" * 64
    review_path.write_bytes(gold10_v2._canonical_json_bytes(review))
    with pytest.raises(Gold10V2Error, match="exact pre-network candidate"):
        gold10_v2._verify_review_record(
            tmp_path, review_path, _sha256(review_path.read_bytes()), manifest
        )


def test_artifact_inventory_rejects_count_preserving_edit(tmp_path: Path) -> None:
    path = tmp_path / "artifact.json"
    gold10_v2._write_json(path, {"value": "AAAA"})
    record = gold10_v2._artifact_record(tmp_path, path)
    original = path.read_bytes()
    path.write_bytes(original.replace(b"AAAA", b"BBBB"))
    assert path.stat().st_size == int(record["bytes"])
    with pytest.raises(Gold10V2Error, match="identity mismatch"):
        gold10_v2._verify_artifact_record(tmp_path, record)


def test_live_recovery_cannot_reach_transport_before_all_offline_gates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=_synthetic_spl(), request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(gold10_v2, "_load_and_verify_pre_network", lambda root: {})
    review = tmp_path / "review.json"
    review.write_text("{}\n", encoding="utf-8")
    with pytest.raises(Gold10V2Error, match="acknowledgement"):
        run_live_recovery(
            tmp_path,
            acknowledgement="wrong",
            review_record_path=review,
            review_record_sha256=_sha256(review.read_bytes()),
            _client_factory=lambda: client,
        )
    assert calls == 0

    with pytest.raises(Gold10V2Error, match="review"):
        run_live_recovery(
            tmp_path,
            acknowledgement=LIVE_ACKNOWLEDGEMENT,
            review_record_path=review,
            review_record_sha256=_sha256(review.read_bytes()),
            _client_factory=lambda: client,
        )
    assert calls == 0


def test_live_gate_rejects_dailymed_policy_drift_before_client_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if not M2_003_ROOT.exists():
        pytest.skip("external retained M2-003 evidence is unavailable")
    root = tmp_path / "pre-network"
    gold10_v2.prepare_pre_network(root, retained_root=M2_003_ROOT, _allow_test_root=True)
    manifest = gold10_v2._load_and_verify_pre_network(root)
    review = {
        "schema_version": f"{gold10_v2.SCHEMA_VERSION}.pre-network-review.v1",
        "work_item": "M2-005-MEDEVIDENCE-GOLD10-V2",
        "status": "PASS",
        "p0": 0,
        "p1": 0,
        "p2": 0,
        "binding": gold10_v2._pre_network_review_binding(root, manifest),
    }
    review_path = tmp_path / "review.json"
    review_path.write_bytes(gold10_v2._canonical_json_bytes(review))
    original_source_state = gold10_v2._source_state()
    drifted_source_state = json.loads(json.dumps(original_source_state))
    drifted_source_state["files"]["src/medevidence/connectors/dailymed/policy.py"]["sha256"] = (
        "0" * 64
    )
    monkeypatch.setattr(gold10_v2, "_source_state", lambda: drifted_source_state)
    client_constructions = 0

    def client_factory() -> httpx.Client:
        nonlocal client_constructions
        client_constructions += 1
        return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))

    with pytest.raises(Gold10V2Error, match="source-state binding is stale"):
        run_live_recovery(
            root,
            acknowledgement=LIVE_ACKNOWLEDGEMENT,
            review_record_path=review_path,
            review_record_sha256=_sha256(review_path.read_bytes()),
            _client_factory=client_factory,
        )
    assert client_constructions == 0
    assert not (root / "live-started.json").exists()
    assert not (root / "live-stop.json").exists()


def test_mounjaro_request_retries_once_and_never_follows_redirect(tmp_path: Path) -> None:
    statuses = iter((503, 200))
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        status = next(statuses)
        return httpx.Response(
            status,
            content=b"temporary" if status == 503 else _synthetic_spl(),
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    body, operation = gold10_v2._request_mounjaro(
        tmp_path,
        client,
        monotonic=lambda: 0.0,
        utc_now=lambda: datetime(2026, 8, 15, tzinfo=UTC),
        sleep=lambda delay: None,
        jitter=lambda: 0.0,
    )
    assert body == _synthetic_spl()
    assert seen == [gold10_v2.MOUNJARO_URL, gold10_v2.MOUNJARO_URL]
    assert operation["logical_requests"] == 1
    assert operation["attempt_count"] == 2
    assert operation["redirect_count"] == 0


def test_mounjaro_redirect_is_terminal_and_raw_is_retained_first(tmp_path: Path) -> None:
    body = b"redirect evidence"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": gold10_v2.MOUNJARO_URL},
            content=body,
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(Gold10V2Error, match="redirects are forbidden"):
        gold10_v2._request_mounjaro(
            tmp_path,
            client,
            monotonic=lambda: 0.0,
            utc_now=lambda: datetime(2026, 8, 15, tzinfo=UTC),
            sleep=lambda delay: None,
            jitter=lambda: 0.0,
        )
    retained = tmp_path / "raw" / "dailymed" / f"sha256-{_sha256(body)}.raw"
    assert retained.read_bytes() == body


def test_malformed_headers_still_retain_raw_and_transactional_attempt_evidence(
    tmp_path: Path,
) -> None:
    body = b"malformed-header-body"

    def handler(request: httpx.Request) -> httpx.Response:
        headers = httpx.Headers(
            [(b"content-length", str(len(body)).encode()), (b"content-length", b"999")]
        )
        return httpx.Response(200, headers=headers, content=body, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(Gold10V2Error, match="duplicate operational"):
        gold10_v2._request_mounjaro(
            tmp_path,
            client,
            monotonic=lambda: 0.0,
            utc_now=lambda: datetime(2026, 8, 15, tzinfo=UTC),
            sleep=lambda delay: None,
            jitter=lambda: 0.0,
        )
    retained = tmp_path / "raw" / "dailymed" / f"sha256-{_sha256(body)}.raw"
    assert retained.read_bytes() == body
    evidence = json.loads((tmp_path / "mounjaro-attempt-evidence.json").read_text())
    assert evidence["terminal_status"] == "failed"
    assert evidence["attempts"][0]["raw"]["sha256"] == _sha256(body)
    assert evidence["attempts"][0]["raw_response_headers"]


def test_attempt_evidence_omits_secret_headers_and_retains_operational_headers(
    tmp_path: Path,
) -> None:
    body = _synthetic_spl()
    secret = "Bearer SUPERSECRET"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={
                "authorization": secret,
                "set-cookie": "session=SUPERSECRET; Secure",
                "retry-after": "1",
            },
            content=body,
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    gold10_v2._request_mounjaro(
        tmp_path,
        client,
        monotonic=lambda: 0.0,
        utc_now=lambda: datetime(2026, 8, 15, tzinfo=UTC),
        sleep=lambda delay: None,
        jitter=lambda: 0.0,
    )
    evidence_bytes = (tmp_path / "mounjaro-attempt-evidence.json").read_bytes()
    assert b"SUPERSECRET" not in evidence_bytes
    assert b"set-cookie" not in evidence_bytes.lower()
    assert b"authorization" not in evidence_bytes.lower()
    assert secret.encode().hex().encode() not in evidence_bytes.lower()
    evidence = json.loads(evidence_bytes)
    raw_headers = evidence["attempts"][0]["raw_response_headers"]
    assert {header["name"] for header in raw_headers} == {"content-length", "retry-after"}
    assert all(set(header) == {"name", "value_hex", "value_sha256"} for header in raw_headers)
    assert evidence["attempts"][0]["response_headers"]["retry-after"] == ["1"]


def test_partial_stream_failure_retains_partial_bytes_and_stop_evidence(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_PartialFailureStream(), request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(Gold10V2Error, match="partial receipt"):
        gold10_v2._request_mounjaro(
            tmp_path,
            client,
            monotonic=lambda: 0.0,
            utc_now=lambda: datetime(2026, 8, 15, tzinfo=UTC),
            sleep=lambda delay: None,
            jitter=lambda: 0.0,
        )
    partial = b"partial-response"
    retained = tmp_path / "raw" / "dailymed" / f"sha256-{_sha256(partial)}.raw"
    assert retained.read_bytes() == partial
    evidence = json.loads((tmp_path / "mounjaro-attempt-evidence.json").read_text())
    assert evidence["attempts"][0]["body_complete"] is False
    assert evidence["attempts"][0]["retained_bytes"] == len(partial)


def test_retry_exhaustion_retains_both_attempt_records_and_never_succeeds(
    tmp_path: Path,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, content=f"attempt-{calls}".encode(), request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(Gold10V2Error, match="retry budget exhausted"):
        gold10_v2._request_mounjaro(
            tmp_path,
            client,
            monotonic=lambda: 0.0,
            utc_now=lambda: datetime(2026, 8, 15, tzinfo=UTC),
            sleep=lambda delay: None,
            jitter=lambda: 0.0,
        )
    evidence = json.loads((tmp_path / "mounjaro-attempt-evidence.json").read_text())
    assert calls == 2
    assert evidence["attempt_count"] == 2
    assert evidence["terminal_status"] == "failed"
    assert all(attempt["raw"] for attempt in evidence["attempts"])
    assert not (tmp_path / "success.json").exists()


def test_semantic_failure_links_retained_acquisition_and_cannot_create_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = b"<not-document/>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, request=request)

    monkeypatch.setattr(gold10_v2, "_load_and_verify_pre_network", lambda root: {})
    monkeypatch.setattr(gold10_v2, "_verify_review_record", lambda *args: {})
    review = tmp_path / "review.json"
    review.write_text("{}\n", encoding="utf-8")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(Gold10V2Error, match="root"):
        run_live_recovery(
            tmp_path,
            acknowledgement=LIVE_ACKNOWLEDGEMENT,
            review_record_path=review,
            review_record_sha256=_sha256(review.read_bytes()),
            _client_factory=lambda: client,
            _monotonic=lambda: 0.0,
            _utc_now=lambda: datetime(2026, 8, 15, tzinfo=UTC),
            _sleep=lambda delay: None,
            _jitter=lambda: 0.0,
        )
    assert (tmp_path / "mounjaro-acquisition.json").exists()
    stop = json.loads((tmp_path / "live-stop.json").read_text())
    assert set(stop["evidence_links"]) == {"acquisition", "attempt_evidence"}
    assert not (tmp_path / "success.json").exists()
    assert not (tmp_path / "corpus-manifest.json").exists()
    assert not (tmp_path / "blinded-adjudication-packet.json").exists()


def test_client_constructor_failure_consumes_authority_and_writes_stop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gold10_v2, "_load_and_verify_pre_network", lambda root: {})
    monkeypatch.setattr(gold10_v2, "_verify_review_record", lambda *args: {})
    review = tmp_path / "review.json"
    review.write_text("{}\n", encoding="utf-8")
    constructor_calls = 0

    def failing_factory() -> httpx.Client:
        nonlocal constructor_calls
        constructor_calls += 1
        raise RuntimeError("synthetic client constructor failure")

    with pytest.raises(RuntimeError, match="synthetic client constructor failure"):
        run_live_recovery(
            tmp_path,
            acknowledgement=LIVE_ACKNOWLEDGEMENT,
            review_record_path=review,
            review_record_sha256=_sha256(review.read_bytes()),
            _client_factory=failing_factory,
        )
    assert constructor_calls == 1
    assert (tmp_path / "live-started.json").exists()
    stop = json.loads((tmp_path / "live-stop.json").read_text(encoding="utf-8"))
    assert stop["status"] == "STOP"
    assert stop["failure_type"] == "RuntimeError"
    assert stop["failure_reason"] == "synthetic client constructor failure"
    assert stop["authorization_consumed"] is True
    assert stop["rerun_authorized"] is False
    assert stop["evidence_links"] == {}
    assert not (tmp_path / "mounjaro-attempt-evidence.json").exists()
    assert not (tmp_path / "raw").exists()
    assert not (tmp_path / "mounjaro-acquisition.json").exists()
    assert not (tmp_path / "success.json").exists()
    assert not (tmp_path / "corpus-manifest.json").exists()
    assert not (tmp_path / "blinded-adjudication-packet.json").exists()


@pytest.mark.parametrize(
    "forbidden",
    ["bm25_score", "medcpt_rank", "rrf", "retriever_identity", "nomination_source"],
)
def test_blinded_packet_rejects_rank_score_retriever_and_nomination_fields(
    forbidden: str,
) -> None:
    with pytest.raises(Gold10V2Error, match="forbidden field"):
        gold10_v2._validate_packet_blindness({forbidden: "leak"})


def test_blinded_packet_has_ten_questions_and_no_qrels() -> None:
    item: dict[str, Any] = {
        "retrieval_unit_id": "pubmed:1",
        "source": "pubmed",
        "stable_source_id": "1",
        "source_version_identity": "pmid:1:content-sha256:x",
        "source_locator": "https://pubmed.ncbi.nlm.nih.gov/1/",
        "title": "Title",
        "text": "Text",
        "text_sha256": _sha256(b"Text"),
    }
    packet = gold10_v2._packet([item], "a" * 64)
    assert len(packet["questions"]) == 10
    assert packet["authoritative_qrels_status"] == "not_created_owner_adjudication_required"
    assert "qrels" not in packet
    assert all("qrels" not in question for question in packet["questions"])


def test_cli_requires_stage_and_exact_live_acknowledgement() -> None:
    with pytest.raises(SystemExit):
        main(["--output-root", str(gold10_v2.CANONICAL_OUTPUT_ROOT)])
    with pytest.raises(SystemExit, match="acknowledgement"):
        main(
            [
                "--output-root",
                str(gold10_v2.CANONICAL_OUTPUT_ROOT),
                "--execute-authorized-live-recovery",
            ]
        )
