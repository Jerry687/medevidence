from __future__ import annotations

import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from evaluation import dev40_acquisition as acquisition

from medevidence.connectors.faers import FaersConnector
from medevidence.connectors.pubmed import PubMedConnector, PubMedConnectorConfig

FAERS_FIXTURES = Path(__file__).parents[2] / "fixtures" / "faers"
EXPECTED_SEARCH_HASHES = (
    "c1241b30b49af706a0ad0db29f9a4a278848fe203a7176336fb99fb03dac058a",
    "35b19c4f94bf4504c05c3564778bf75fb92e6f2b8a3ea9540dd41e41d364f3ee",
    "a2d22dccea155c956c3e7840e70dfb9436217ed0e2acce5c12391690ad0506b4",
)
FIXED_NOW = datetime(2026, 8, 16, 18, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _deterministic_frozen_git_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model the exact Owner-frozen baseline and ten-path candidate."""
    repository = Path(acquisition.__file__).resolve().parents[1]
    baseline_tracked = set(acquisition.SOURCE_STATE_PATHS[:4])
    candidate_status = {
        relative: (b" M" if relative in baseline_tracked else b"??")
        for relative in acquisition.SOURCE_STATE_PATHS
    }
    status_output = b"".join(
        status + b" " + relative.encode("ascii") + b"\0"
        for relative, status in candidate_status.items()
    )
    original = acquisition._run_git

    def deterministic(arguments: tuple[str, ...], *, stdout_limit: int) -> bytes:
        if arguments == ("rev-parse", "--verify", "HEAD"):
            return (acquisition.BASELINE_COMMIT + "\n").encode("ascii")
        if arguments == ("branch", "--show-current"):
            return (acquisition.EXPECTED_BRANCH + "\n").encode("ascii")
        if arguments == ("rev-parse", "--show-toplevel"):
            return (str(repository) + "\n").encode("ascii")
        if arguments == ("status", "--porcelain=v1", "-z", "--untracked-files=all"):
            return status_output
        return original(arguments, stdout_limit=stdout_limit)

    monkeypatch.setattr(acquisition, "_run_git", deterministic)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _search_xml(*pmids: str, count: int | None = None) -> bytes:
    total = len(pmids) if count is None else count
    ids = "".join(f"<Id>{pmid}</Id>" for pmid in pmids)
    return (
        f"<eSearchResult><Count>{total}</Count><RetMax>{len(pmids)}</RetMax>"
        f"<RetStart>0</RetStart><IdList>{ids}</IdList></eSearchResult>"
    ).encode()


def _article(pmid: str) -> str:
    return (
        '<PubmedArticle><MedlineCitation Status="MEDLINE"><PMID>'
        f"{pmid}</PMID><Article><Journal><Title>Test Journal</Title></Journal>"
        f"<ArticleTitle>Test article {pmid}</ArticleTitle><Language>eng</Language>"
        "</Article></MedlineCitation></PubmedArticle>"
    )


def _fetch_xml(*pmids: str) -> bytes:
    value = "<PubmedArticleSet>" + "".join(_article(pmid) for pmid in pmids) + "</PubmedArticleSet>"
    return value.encode()


def _book_article(pmid: str) -> str:
    return (
        "<PubmedBookArticle><BookDocument>"
        f"<PMID>{pmid}</PMID>"
        '<ArticleIdList><ArticleId IdType="bookaccession">NBK123</ArticleId></ArticleIdList>'
        "<Book><Publisher><PublisherName>Source Publisher</PublisherName>"
        "<PublisherLocation>Bethesda (MD)</PublisherLocation></Publisher>"
        "<BookTitle>Source Book</BookTitle><PubDate><Year>2025</Year></PubDate>"
        "<Medium>Internet</Medium></Book><ArticleTitle>Book chapter</ArticleTitle>"
        "<Language>eng</Language><Abstract><AbstractText>Source abstract.</AbstractText>"
        "</Abstract></BookDocument><PubmedBookData><ArticleIdList>"
        f'<ArticleId IdType="pubmed">{pmid}</ArticleId>'
        "</ArticleIdList></PubmedBookData></PubmedBookArticle>"
    )


def _write_bound(path: Path, raw: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = _sha256(raw)
    path.write_bytes(raw)
    path.with_suffix(path.suffix + ".sha256").write_bytes(
        f"{digest}  {path.name}\n".encode("ascii")
    )
    return digest


def _synthetic_stopped_pubmed_c(
    root: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, dict[str, int | str]]:
    article_pmids = tuple(str(10_000_000 + index) for index in range(1, 100))
    requested = ("31644235", *article_pmids)
    raw = (
        "<PubmedArticleSet>"
        + _book_article("31644235")
        + "".join(_article(pmid) for pmid in article_pmids)
        + "</PubmedArticleSet>"
    ).encode()
    raw_path = root / acquisition.PUBMED_C_RAW_RELATIVE_PATH
    raw_sha = _write_bound(raw_path, raw)
    binding = {
        "ordered_unique_pmids": list(requested),
        "query_id": "pubmed-fetch:sha256:" + ("a" * 64),
    }
    binding_raw = acquisition._canonical_json_bytes(binding)
    binding_sha = _write_bound(root / acquisition.PUBMED_C_BINDING_RELATIVE_PATH, binding_raw)
    operation = {
        "binding_sha256": binding_sha,
        "state": "partial_success",
        "not_retrieved_pmids": ["31644235"],
        "raw_responses": [
            {
                "relative_path": acquisition.PUBMED_C_RAW_RELATIVE_PATH.as_posix(),
                "sha256": raw_sha,
                "observed_at_utc": "2026-08-16T17:31:54.550516Z",
            }
        ],
    }
    operation_raw = acquisition._canonical_json_bytes(operation)
    operation_sha = _write_bound(
        root / acquisition.PUBMED_C_OPERATION_RELATIVE_PATH,
        operation_raw,
    )
    stop = {
        "status": "STOP_SOURCE_FAILURE",
        "executed_operation_records": [acquisition.PUBMED_C_OPERATION_RELATIVE_PATH.as_posix()],
    }
    stop_raw = acquisition._canonical_json_bytes(stop)
    stop_sha = _write_bound(root / "stop.json", stop_raw)
    monkeypatch.setattr(acquisition, "PUBMED_C_RAW_BYTES", len(raw))
    monkeypatch.setattr(acquisition, "PUBMED_C_RAW_SHA256", raw_sha)
    monkeypatch.setattr(acquisition, "PUBMED_C_BINDING_SHA256", binding_sha)
    monkeypatch.setattr(acquisition, "PUBMED_C_OPERATION_SHA256", operation_sha)
    monkeypatch.setattr(acquisition, "ORIGINAL_STOP_SHA256", stop_sha)
    return acquisition._evidence_tree_state(root)


def _pubmed_factory(
    handler: Any,
    *,
    constructed_caps: list[int] | None = None,
) -> Any:
    def factory(max_payload_bytes: int) -> PubMedConnector:
        if constructed_caps is not None:
            constructed_caps.append(max_payload_bytes)
        config = PubMedConnectorConfig.m1a_constrained_v1()
        config = PubMedConnectorConfig(
            max_query_characters=config.max_query_characters,
            page_size=config.page_size,
            max_pages=config.max_pages,
            max_records=config.max_records,
            max_payload_bytes=max_payload_bytes,
            connect_timeout_seconds=config.connect_timeout_seconds,
            read_timeout_seconds=config.read_timeout_seconds,
            write_timeout_seconds=config.write_timeout_seconds,
            pool_timeout_seconds=config.pool_timeout_seconds,
            total_deadline_seconds=config.total_deadline_seconds,
            max_attempts=config.max_attempts,
            base_backoff_seconds=config.base_backoff_seconds,
            jitter_seconds=config.jitter_seconds,
            max_backoff_seconds=config.max_backoff_seconds,
            max_retry_after_seconds=config.max_retry_after_seconds,
            max_redirects=config.max_redirects,
            cache_policy=config.cache_policy,
        )
        return PubMedConnector(
            httpx.MockTransport(handler),
            config,
            utc_now=lambda: FIXED_NOW,
            sleep=lambda _: None,
            jitter=lambda: 0.0,
        )

    return factory


def _faers_factory(handler: Any) -> Any:
    def factory() -> FaersConnector:
        return FaersConnector(
            httpx.MockTransport(handler),
            utc_now=lambda: FIXED_NOW,
            sleep=lambda _: None,
            jitter=lambda: 0.0,
        )

    return factory


def _prepare_and_review(tmp_path: Path) -> tuple[acquisition.FreezeResult, Path, str]:
    freeze_root = tmp_path / "freeze"
    freeze_root.mkdir()
    freeze = acquisition.prepare_request_freeze(freeze_root, _allow_test_root=True)
    review_path = freeze_root / acquisition.PRE_NETWORK_REVIEW_NAME
    review = {
        "work_item": acquisition.WORK_ITEM,
        "verdict": "PASS",
        "finding_counts": {"P0": 0, "P1": 0, "P2": 0},
        "request_freeze_sha256": freeze.sha256,
        "source_state_aggregate_sha256": freeze.source_state_aggregate_sha256,
        "runtime_closure_aggregate_sha256": freeze.runtime_closure_aggregate_sha256,
    }
    review_bytes = acquisition._canonical_json_bytes(review)
    review_path.write_bytes(review_bytes)
    return freeze, review_path, _sha256(review_bytes)


def _run(
    tmp_path: Path,
    pubmed_handler: Any,
    *,
    faers_handler: Any | None = None,
    constructed_caps: list[int] | None = None,
) -> acquisition.AcquisitionResult:
    freeze, review_path, review_sha = _prepare_and_review(tmp_path)
    if faers_handler is None:
        faers_body = (FAERS_FIXTURES / "count-empty.json").read_bytes()

        def empty_faers(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, content=faers_body)

        faers_handler = empty_faers
    return acquisition.run_authorized_acquisition(
        acknowledgement=acquisition.LIVE_ACKNOWLEDGEMENT,
        request_freeze_path=freeze.path,
        request_freeze_sha256=freeze.sha256,
        review_record_path=review_path,
        review_record_sha256=review_sha,
        output_root=tmp_path / "live",
        _pubmed_factory=_pubmed_factory(pubmed_handler, constructed_caps=constructed_caps),
        _faers_factory=_faers_factory(faers_handler),
        _allow_test_root=True,
    )


def test_exact_search_preimage_hashes_and_wire_contract() -> None:
    for pair, expected in zip(acquisition.PUBMED_PAIRS, EXPECTED_SEARCH_HASHES, strict=True):
        preimage = acquisition.pubmed_search_preimage(pair.term)
        raw = acquisition._canonical_json_bytes(preimage, terminal_lf=False)
        assert _sha256(raw) == expected == pair.expected_request_preimage_sha256
        assert preimage["query_parameters_in_wire_order"] == [
            ["db", "pubmed"],
            ["term", pair.term],
            ["retmode", "xml"],
            ["retstart", "0"],
            ["retmax", "100"],
            ["sort", "relevance"],
            ["tool", "medevidence"],
        ]
    assert (
        len(
            acquisition._canonical_json_bytes(
                acquisition.pubmed_search_preimage(acquisition.TERM_A), terminal_lf=False
            )
        )
        == 446
    )


def test_offline_pubmed_c_successor_reconciles_book_without_transport_or_raw_copy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_root = tmp_path / "acquisition-001"
    original_before = _synthetic_stopped_pubmed_c(original_root, monkeypatch)
    successor_root = tmp_path / "acquisition-001-successor-001"

    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("offline replay must not construct a connector or transport")

    monkeypatch.setattr(PubMedConnector, "__init__", forbidden)
    result = acquisition.replay_pubmed_c_successor(
        original_root=original_root,
        output_root=successor_root,
        _allow_test_root=True,
    )

    assert result.publication_count == 99
    assert result.book_document_count == 1
    assert result.provider_record_count == 100
    assert acquisition._evidence_tree_state(original_root) == original_before
    evidence_path = successor_root / "pubmed-c-offline-successor-reconciliation.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["offline_replay"]["mapping_disposition"] == (
        "source_native_retained_not_coerced"
    )
    assert evidence["offline_replay"]["normalized_publication_records"] == 99
    assert evidence["offline_replay"]["source_native_book_documents"] == 1
    assert evidence["offline_replay"]["admitted_provider_records"] == 100
    assert evidence["offline_replay"]["book_document"]["has_journal_semantics"] is False
    assert evidence["offline_replay"]["raw_bytes_copied"] is False
    assert evidence["offline_replay"]["network_requests"] == 0
    assert evidence["offline_replay"]["faers_d_executed"] is False
    assert all(path.suffix != ".raw" for path in successor_root.rglob("*"))
    assert _sha256(evidence_path.read_bytes()) == result.evidence_sha256

    with pytest.raises(acquisition.Dev40AcquisitionError, match="already exists"):
        acquisition.replay_pubmed_c_successor(
            original_root=original_root,
            output_root=successor_root,
            _allow_test_root=True,
        )


def test_prepare_writes_exact_freeze_without_constructing_clients(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*_: object, **__: object) -> None:
        raise AssertionError("prepare must not construct a connector")

    monkeypatch.setattr(PubMedConnector, "__init__", forbidden)
    monkeypatch.setattr(FaersConnector, "__init__", forbidden)
    freeze_root = tmp_path / "freeze"
    freeze_root.mkdir()
    result = acquisition.prepare_request_freeze(freeze_root, _allow_test_root=True)
    value = json.loads(result.path.read_text(encoding="utf-8"))
    assert value["status"] == "PRE_NETWORK_REVIEW_REQUIRED"
    assert value["schema_version"].endswith("request-freeze.v4")
    assert value["predecessor_freezes"] == [
        {
            "path": acquisition.FREEZE_V1_PATH.as_posix(),
            "bytes": acquisition.FREEZE_V1_BYTES,
            "sha256": acquisition.FREEZE_V1_SHA256,
            "review_status": "FAIL — P0 0 / P1 1 / P2 0",
            "executable_status": "superseded_as_executable_gate",
            "superseded_by": acquisition.FREEZE_V2_PATH.name,
            "evidence_status": "immutable_historical_evidence",
        },
        {
            "path": acquisition.FREEZE_V2_PATH.as_posix(),
            "bytes": acquisition.FREEZE_V2_BYTES,
            "sha256": acquisition.FREEZE_V2_SHA256,
            "review_status": "FAIL — P0 0 / P1 0 / P2 1",
            "executable_status": "superseded_as_executable_gate",
            "superseded_by": acquisition.FREEZE_V3_PATH.name,
            "evidence_status": "immutable_historical_evidence",
        },
        {
            "path": acquisition.FREEZE_V3_PATH.as_posix(),
            "bytes": acquisition.FREEZE_V3_BYTES,
            "sha256": acquisition.FREEZE_V3_SHA256,
            "review_status": "PASS — P0 0 / P1 0 / P2 0",
            "terminal_audit_status": "FAIL — P0 0 / P1 1 / P2 0",
            "executable_status": "superseded_as_executable_gate",
            "superseded_by": acquisition.FREEZE_PATH.name,
            "evidence_status": "immutable_historical_evidence",
        },
    ]
    assert all("superseded" not in predecessor for predecessor in value["predecessor_freezes"])
    assert value["review_history"][-1]["finding_counts"] == {"P0": 0, "P1": 0, "P2": 0}
    assert value["terminal_audit_history"][-1]["finding_counts"] == {
        "P0": 0,
        "P1": 1,
        "P2": 0,
    }
    assert value["remediation_history"][-1]["cycle"] == 3
    assert value["live_gate"]["required_review_name"] == ("independent-pre-network-review-004.json")
    assert value["access_declarations"]["medical_source_network"] == "not_accessed_during_freeze"
    assert value["bounds"] == {
        "authorized_logical_operations": 7,
        "pubmed_operations": 6,
        "faers_operations": 1,
        "max_http_requests": 26,
        "max_pubmed_http_requests": 24,
        "max_faers_http_requests": 2,
        "pubmed_search_bytes_per_operation": 262144,
        "pubmed_fetch_bytes_per_operation": 5242880,
        "pubmed_combined_raw_bytes": 16515072,
        "faers_raw_bytes": 5242880,
        "combined_raw_bytes": 21757952,
        "logical_operation_deadline_seconds": 30,
        "whole_run_deadline_seconds": 240.0,
        "max_unique_pmids_per_pair": 100,
        "no_automatic_rerun": True,
    }
    assert acquisition.SOURCE_STATE_PATHS[-3:] == (
        "evaluation/dev40_corpus.py",
        "evaluation/run_dev40_corpus.py",
        "tests/unit/evaluation/test_dev40_corpus.py",
    )
    assert len(value["source_state"]["files"]) == 10


def test_wrong_freeze_or_source_state_fails_before_client_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze, review_path, review_sha = _prepare_and_review(tmp_path)
    original = acquisition._source_state

    def drifted() -> dict[str, dict[str, int | str]]:
        value = original()
        value[acquisition.SOURCE_STATE_PATHS[0]]["sha256"] = "0" * 64
        return value

    calls = 0

    def forbidden(_: int) -> PubMedConnector:
        nonlocal calls
        calls += 1
        raise AssertionError("client construction must not occur")

    monkeypatch.setattr(acquisition, "_source_state", drifted)
    with pytest.raises(acquisition.Dev40AcquisitionError, match="request-freeze content"):
        acquisition.run_authorized_acquisition(
            acknowledgement=acquisition.LIVE_ACKNOWLEDGEMENT,
            request_freeze_path=freeze.path,
            request_freeze_sha256=freeze.sha256,
            review_record_path=review_path,
            review_record_sha256=review_sha,
            output_root=tmp_path / "live",
            _pubmed_factory=forbidden,
            _faers_factory=lambda: (_ for _ in ()).throw(AssertionError("no FAERS client")),
            _allow_test_root=True,
        )
    assert calls == 0


def test_loaded_runtime_origin_drift_fails_before_live_root_or_client(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze, review_path, review_sha = _prepare_and_review(tmp_path)
    constructed = 0

    def forbidden(_: int) -> PubMedConnector:
        nonlocal constructed
        constructed += 1
        raise AssertionError("client construction must not occur")

    monkeypatch.setattr(
        acquisition.pubmed_client_module,
        "__file__",
        str(tmp_path / "wrong-checkout" / "client.py"),
    )
    live_root = tmp_path / "live"
    with pytest.raises(acquisition.Dev40AcquisitionError, match="module origin"):
        acquisition.run_authorized_acquisition(
            acknowledgement=acquisition.LIVE_ACKNOWLEDGEMENT,
            request_freeze_path=freeze.path,
            request_freeze_sha256=freeze.sha256,
            review_record_path=review_path,
            review_record_sha256=review_sha,
            output_root=live_root,
            _pubmed_factory=forbidden,
            _faers_factory=lambda: (_ for _ in ()).throw(AssertionError("no FAERS client")),
            _allow_test_root=True,
        )
    assert constructed == 0
    assert not live_root.exists()


def test_coordination_venv_cli_bootstraps_exact_worktree_src_without_pythonpath() -> None:
    repository = Path(acquisition.__file__).resolve().parents[1]
    coordination_python = Path(r"D:\Projects\medevidence\.venv\Scripts\python.exe")
    if not coordination_python.is_file():
        pytest.skip("machine-local coordination interpreter is unavailable")
    cli = repository / "evaluation" / "run_dev40_acquisition.py"
    code = (
        "import inspect,runpy;"
        f"runpy.run_path({str(cli)!r},run_name='coordination_probe');"
        "from medevidence.connectors.pubmed.client import PubMedConnector;"
        "import medevidence.connectors.pubmed.client as loaded;"
        "print(loaded.__file__);"
        "print(inspect.signature(PubMedConnector.search))"
    )
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    completed = subprocess.run(
        (str(coordination_python), "-I", "-c", code),
        cwd=repository,
        env=environment,
        shell=False,
        check=False,
        capture_output=True,
        text=True,
        timeout=10.0,
    )
    assert completed.returncode == 0, completed.stderr
    lines = completed.stdout.splitlines()
    assert (
        Path(lines[0]).resolve()
        == (repository / "src" / "medevidence" / "connectors" / "pubmed" / "client.py").resolve()
    )
    assert "sort:" in lines[1]
    assert "Literal['relevance'] | None" in lines[1]


@pytest.mark.parametrize(
    "relative",
    [
        "src/medevidence/connectors/pubmed/policy.py",
        "src/medevidence/connectors/faers/parsing.py",
        "src/medevidence/domain/identifiers.py",
    ],
)
def test_runtime_policy_parser_or_domain_drift_fails_before_client_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    freeze, review_path, review_sha = _prepare_and_review(tmp_path)
    original = acquisition._runtime_closure_state

    def drifted() -> dict[str, dict[str, int | str]]:
        value = original()
        value[relative]["sha256"] = "0" * 64
        return value

    constructed = 0

    def forbidden(_: int) -> PubMedConnector:
        nonlocal constructed
        constructed += 1
        raise AssertionError("client construction must not occur")

    monkeypatch.setattr(acquisition, "_runtime_closure_state", drifted)
    with pytest.raises(acquisition.Dev40AcquisitionError, match="request-freeze content"):
        acquisition.run_authorized_acquisition(
            acknowledgement=acquisition.LIVE_ACKNOWLEDGEMENT,
            request_freeze_path=freeze.path,
            request_freeze_sha256=freeze.sha256,
            review_record_path=review_path,
            review_record_sha256=review_sha,
            output_root=tmp_path / "live",
            _pubmed_factory=forbidden,
            _faers_factory=lambda: (_ for _ in ()).throw(AssertionError("no FAERS client")),
            _allow_test_root=True,
        )
    assert constructed == 0


@pytest.mark.parametrize("field", ["head", "branch"])
def test_wrong_git_head_or_branch_fails_before_client_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    freeze, review_path, review_sha = _prepare_and_review(tmp_path)
    original = acquisition._git_output

    def wrong(arguments: tuple[str, ...]) -> str:
        if field == "head" and arguments == ("rev-parse", "--verify", "HEAD"):
            return "0" * 40
        if field == "branch" and arguments == ("branch", "--show-current"):
            return "wrong/branch"
        return original(arguments)

    constructed = 0

    def forbidden(_: int) -> PubMedConnector:
        nonlocal constructed
        constructed += 1
        raise AssertionError("client construction must not occur")

    monkeypatch.setattr(acquisition, "_git_output", wrong)
    expected_message = "Git HEAD" if field == "head" else "Git branch"
    with pytest.raises(acquisition.Dev40AcquisitionError, match=expected_message):
        acquisition.run_authorized_acquisition(
            acknowledgement=acquisition.LIVE_ACKNOWLEDGEMENT,
            request_freeze_path=freeze.path,
            request_freeze_sha256=freeze.sha256,
            review_record_path=review_path,
            review_record_sha256=review_sha,
            output_root=tmp_path / "live",
            _pubmed_factory=forbidden,
            _faers_factory=lambda: (_ for _ in ()).throw(AssertionError("no FAERS client")),
            _allow_test_root=True,
        )
    assert constructed == 0


@pytest.mark.parametrize("candidate_drift", ["staged", "outside_allowlist"])
def test_staged_or_outside_allowlist_candidate_fails_before_client_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, candidate_drift: str
) -> None:
    freeze, review_path, review_sha = _prepare_and_review(tmp_path)
    original = acquisition._run_git
    original_status = original(
        ("status", "--porcelain=v1", "-z", "--untracked-files=all"),
        stdout_limit=8_192,
    )

    def drifted(arguments: tuple[str, ...], *, stdout_limit: int) -> bytes:
        if arguments[0] != "status":
            return original(arguments, stdout_limit=stdout_limit)
        if candidate_drift == "outside_allowlist":
            return original_status + b"?? docs/unapproved.txt\0"
        records = original_status.split(b"\0")
        records[0] = b"M " + records[0][2:]
        return b"\0".join(records)

    constructed = 0

    def forbidden(_: int) -> PubMedConnector:
        nonlocal constructed
        constructed += 1
        raise AssertionError("client construction must not occur")

    monkeypatch.setattr(acquisition, "_run_git", drifted)
    with pytest.raises(acquisition.Dev40AcquisitionError, match="Git candidate"):
        acquisition.run_authorized_acquisition(
            acknowledgement=acquisition.LIVE_ACKNOWLEDGEMENT,
            request_freeze_path=freeze.path,
            request_freeze_sha256=freeze.sha256,
            review_record_path=review_path,
            review_record_sha256=review_sha,
            output_root=tmp_path / "live",
            _pubmed_factory=forbidden,
            _faers_factory=lambda: (_ for _ in ()).throw(AssertionError("no FAERS client")),
            _allow_test_root=True,
        )
    assert constructed == 0


@pytest.mark.parametrize("gate", ["freeze_hash", "review"])
def test_wrong_freeze_hash_or_review_fails_before_client_construction(
    tmp_path: Path, gate: str
) -> None:
    freeze, review_path, review_sha = _prepare_and_review(tmp_path)
    if gate == "freeze_hash":
        freeze_sha = "0" * 64
    else:
        freeze_sha = freeze.sha256
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["finding_counts"]["P1"] = 1
        raw = acquisition._canonical_json_bytes(review)
        review_path.write_bytes(raw)
        review_sha = _sha256(raw)
    constructed = 0

    def forbidden(_: int) -> PubMedConnector:
        nonlocal constructed
        constructed += 1
        raise AssertionError("client construction must not occur")

    with pytest.raises(acquisition.Dev40AcquisitionError):
        acquisition.run_authorized_acquisition(
            acknowledgement=acquisition.LIVE_ACKNOWLEDGEMENT,
            request_freeze_path=freeze.path,
            request_freeze_sha256=freeze_sha,
            review_record_path=review_path,
            review_record_sha256=review_sha,
            output_root=tmp_path / "live",
            _pubmed_factory=forbidden,
            _faers_factory=lambda: (_ for _ in ()).throw(AssertionError("no FAERS client")),
            _allow_test_root=True,
        )
    assert constructed == 0


def test_dynamic_fetch_binding_is_numeric_sorted_deduplicated_and_persisted_before_fetch(
    tmp_path: Path,
) -> None:
    live_root = tmp_path / "live"
    observed_fetches = 0

    def pubmed_handler(request: httpx.Request) -> httpx.Response:
        nonlocal observed_fetches
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, content=_search_xml("10", "2", "10", count=3))
        observed_fetches += 1
        operation = acquisition.PUBMED_PAIRS[observed_fetches - 1]
        binding_path = live_root / "bindings" / f"{operation.operation_id}-efetch-binding.json"
        sidecar = binding_path.with_suffix(".json.sha256")
        assert binding_path.exists() and sidecar.exists()
        binding = json.loads(binding_path.read_text(encoding="utf-8"))
        assert binding["ordered_unique_pmids"] == ["2", "10"]
        assert request.url.params["id"] == "2,10"
        assert _sha256(binding_path.read_bytes()) in sidecar.read_text(encoding="ascii")
        return httpx.Response(200, content=_fetch_xml("2", "10"))

    caps: list[int] = []
    result = _run(tmp_path, pubmed_handler, constructed_caps=caps)
    assert result.authorized_logical_operations == result.executed_logical_operations == 7
    assert result.skipped_empty_fetches == 0
    assert result.http_requests == 7
    assert caps == [262144, 5242880, 262144, 5242880, 262144, 5242880]
    manifest = json.loads((live_root / "acquisition-manifest.json").read_text(encoding="utf-8"))
    assert manifest["corpus_created"] is False
    assert manifest["adjudication_packet_created"] is False
    assert manifest["qrels_rankings_scores_created"] is False
    assert not any(
        token in path.name.casefold()
        for path in live_root.rglob("*")
        for token in ("corpus", "packet", "qrels", "ranking")
    )


def test_complete_zero_match_skips_all_empty_fetches_truthfully(tmp_path: Path) -> None:
    observed_paths: list[str] = []

    def pubmed_handler(request: httpx.Request) -> httpx.Response:
        observed_paths.append(request.url.path)
        return httpx.Response(200, content=_search_xml(count=0))

    result = _run(tmp_path, pubmed_handler)
    assert observed_paths == ["/entrez/eutils/esearch.fcgi"] * 3
    assert result.authorized_logical_operations == 7
    assert result.executed_logical_operations == 4
    assert result.skipped_empty_fetches == 3
    for pair in acquisition.PUBMED_PAIRS:
        value = json.loads(
            (
                tmp_path / "live" / "operations" / f"{pair.operation_id}-efetch-skipped.json"
            ).read_text(encoding="utf-8")
        )
        assert value["status"] == "skipped_by_no_match"
        assert value["authorized_but_not_executed"] is True


@pytest.mark.parametrize(
    "pmids, message",
    [
        ((), "1 through 100"),
        (("0",), "noncanonical"),
        (("1", "bad"), "noncanonical"),
        (tuple(str(index + 1) for index in range(101)), "1 through 100"),
    ],
)
def test_empty_malformed_or_too_many_fetch_ids_fail_closed(
    pmids: tuple[str, ...], message: str
) -> None:
    with pytest.raises(acquisition.Dev40AcquisitionError, match=message):
        acquisition._fetch_binding(acquisition.PUBMED_PAIRS[0], pmids)


def test_binding_persistence_failure_stops_before_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    freeze, review_path, review_sha = _prepare_and_review(tmp_path)
    original_write = acquisition._write_json
    constructed_caps: list[int] = []

    def fail_binding(path: Path, value: Any) -> str:
        if path.name.endswith("-efetch-binding.json"):
            raise OSError("synthetic persistence failure")
        return original_write(path, value)

    monkeypatch.setattr(acquisition, "_write_json", fail_binding)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("esearch.fcgi")
        return httpx.Response(200, content=_search_xml("2"))

    with pytest.raises(acquisition.Dev40AcquisitionError, match="persistence failure"):
        acquisition.run_authorized_acquisition(
            acknowledgement=acquisition.LIVE_ACKNOWLEDGEMENT,
            request_freeze_path=freeze.path,
            request_freeze_sha256=freeze.sha256,
            review_record_path=review_path,
            review_record_sha256=review_sha,
            output_root=tmp_path / "live",
            _pubmed_factory=_pubmed_factory(handler, constructed_caps=constructed_caps),
            _faers_factory=_faers_factory(
                lambda _: (_ for _ in ()).throw(AssertionError("FAERS must not execute"))
            ),
            _allow_test_root=True,
        )
    assert constructed_caps == [262144]
    assert (tmp_path / "live" / "stop.json").exists()
    assert not (tmp_path / "live" / "acquisition-manifest.json").exists()


def test_source_failure_retains_stop_and_never_retries_the_logical_operation(
    tmp_path: Path,
) -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(400, content=b"permanent failure")

    with pytest.raises(acquisition.Dev40AcquisitionError, match="ESearch failed"):
        _run(tmp_path, handler)
    assert attempts == 1
    stop = json.loads((tmp_path / "live" / "stop.json").read_text(encoding="utf-8"))
    assert stop["status"] == "STOP_SOURCE_FAILURE"
    assert stop["success_manifest_created"] is False
    assert stop["automatic_rerun_authorized"] is False
    assert not (tmp_path / "live" / "acquisition-manifest.json").exists()


def test_malformed_search_is_indeterminate_and_stops_before_fetch(tmp_path: Path) -> None:
    caps: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("esearch.fcgi")
        return httpx.Response(200, content=b"<eSearchResult><Count>0</Count>")

    with pytest.raises(acquisition.Dev40AcquisitionError, match="ESearch failed"):
        _run(tmp_path, handler, constructed_caps=caps)
    assert caps == [262144]
    assert (tmp_path / "live" / "stop.json").exists()


def test_existing_live_root_blocks_rerun_before_client_construction(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_search_xml(count=0))

    _run(tmp_path, handler)
    freeze_path = tmp_path / "freeze" / acquisition.FREEZE_PATH.name
    review_path = tmp_path / "freeze" / acquisition.PRE_NETWORK_REVIEW_NAME
    constructed = 0

    def forbidden(_: int) -> PubMedConnector:
        nonlocal constructed
        constructed += 1
        raise AssertionError("rerun must stop before client construction")

    with pytest.raises(acquisition.Dev40AcquisitionError, match="no rerun"):
        acquisition.run_authorized_acquisition(
            acknowledgement=acquisition.LIVE_ACKNOWLEDGEMENT,
            request_freeze_path=freeze_path,
            request_freeze_sha256=_sha256(freeze_path.read_bytes()),
            review_record_path=review_path,
            review_record_sha256=_sha256(review_path.read_bytes()),
            output_root=tmp_path / "live",
            _pubmed_factory=forbidden,
            _faers_factory=lambda: (_ for _ in ()).throw(AssertionError("no FAERS client")),
            _allow_test_root=True,
        )
    assert constructed == 0


def test_frozen_faers_query_and_no_holdout_or_refresh_contract() -> None:
    query = acquisition.build_faers_query()
    assert query.query_id == acquisition.FAERS_QUERY_ID
    source = Path(acquisition.__file__).read_text(encoding="utf-8")
    assert "OZEMPIC" not in source
    assert "MOUNJARO" not in source
    assert "Holdout-20" not in source
