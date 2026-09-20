"""Real local factory across durable source, model, validation and review boundaries."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from pydantic import TypeAdapter
from tests.contract.connectors.test_pubmed_connector import search_xml
from tests.contract.infrastructure.test_qwen_semantic_evaluator import _envelope
from tests.unit.tools.test_generation_v2_service import raw as generation_raw
from tests.unit.tools.test_generation_v2_service import response as generation_response

from medevidence.domain import (
    ComparisonIntent,
    QueryBounds,
    ResearchScope,
    ResultBounds,
    SourceType,
    canonical_json,
    sha256_digest,
)
from medevidence.infrastructure.evidence_provenance import VerifiedEvidenceProvenanceStore
from medevidence.infrastructure.local_export_writer import LocalExportWriter
from medevidence.infrastructure.local_research_catalog import LocalResearchCatalogAdapter
from medevidence.infrastructure.local_runtime_settings import LocalRuntimeSettings
from medevidence.infrastructure.pubmed_material_store import SnapshotPubMedMaterialStore
from medevidence.infrastructure.research_scope_safety import load_local_research_input_catalog
from medevidence.ingestion.snapshots import SnapshotStore
from medevidence.local_runtime import open_local_application
from medevidence.persistence.config import DATABASE_URL_ENV, PersistenceSettings
from medevidence.persistence.repositories import PersistenceRepository
from medevidence.persistence.research_jobs import ResearchJobRepository
from medevidence.tools.generation import GenerationInput
from medevidence.tools.generation_v2 import (
    CandidateCitationV2,
    CandidateClaimV2,
    GenerationCandidateV2,
)
from medevidence.tools.generation_v2_service import parse_deepseek_generation_v2_response
from medevidence.tools.report_validation import (
    ClaimClass,
    EvidenceInput,
    InferenceUse,
    QualitativeCode,
)
from medevidence.tools.research_application import (
    ResearchApplicationFailure,
    ResearchExportFormat,
    ResearchReviewCommand,
    ResearchReviewDecision,
    ResearchRunStatus,
    ResearchSubmission,
)

_QWEN_ENDPOINT = (
    "https://1234567890123456789.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions"
)
_PUBMED_FETCH = b"""<PubmedArticleSet><PubmedArticle>
<MedlineCitation Status="MEDLINE"><PMID>111</PMID><Article>
<Journal><JournalIssue><PubDate><Year>2025</Year></PubDate></JournalIssue>
<Title>Synthetic Evidence Journal</Title></Journal>
<ArticleTitle>Synthetic semaglutide nausea report</ArticleTitle>
<Abstract><AbstractText>Semaglutide nausea was described in this synthetic publication.
</AbstractText></Abstract>
<Language>eng</Language></Article></MedlineCitation>
<PubmedData><ArticleIdList><ArticleId IdType="pubmed">111</ArticleId></ArticleIdList></PubmedData>
</PubmedArticle></PubmedArticleSet>"""


@pytest.fixture(scope="module")
def database() -> PersistenceSettings:
    url = os.environ.get(DATABASE_URL_ENV)
    if url is None:
        pytest.skip(f"{DATABASE_URL_ENV} is required for disposable PostgreSQL tests")
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    return PersistenceSettings(url)


def _scope(multi: bool = False) -> ResearchScope:
    catalog = load_local_research_input_catalog()
    return ResearchScope.create(
        drugs=(catalog.drugs_by_term["semaglutide"],),
        adverse_reactions=tuple(
            catalog.reactions_by_term[name]
            for name in (("nausea", "vomiting", "diarrhoea") if multi else ("nausea",))
        ),
        date_range=None,
        selected_sources=(SourceType.PUBMED, SourceType.DAILYMED, SourceType.FAERS)
        if multi
        else (SourceType.PUBMED,),
        comparison_intent=ComparisonIntent.SUMMARIZE,
        query_bounds=QueryBounds(max_query_characters=512, max_pages=5, max_total_seconds=60),
        result_bounds=ResultBounds(max_records=100, max_payload_bytes=5_242_880),
    )


def _generation_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content)
    assert body["model"] == "deepseek-flash"
    wrapped = body["input"]
    payload = json.loads(wrapped.split("\n", 1)[1].rsplit("\n", 1)[0])
    generation_input = GenerationInput.model_validate_json(
        canonical_json(payload["generation_input"])
    )
    assert len(generation_input.evidence) <= 1
    claims: tuple[CandidateClaimV2, ...] = ()
    if generation_input.evidence:
        evidence = generation_input.evidence[0]
        claims = (
            CandidateClaimV2(
                ordinal=1,
                source=SourceType.PUBMED,
                statement="The bounded publication supplies descriptive evidence.",
                claim_class=ClaimClass.DESCRIPTIVE,
                inference_use=InferenceUse.DESCRIPTIVE,
                qualitative_code=QualitativeCode.PUBMED_DESCRIPTIVE,
                numerical_context=None,
                citations=(
                    CandidateCitationV2(
                        evidence_id=evidence.evidence_id,
                        locator_ref=evidence.locators[0],
                        relationship="supports",
                    ),
                ),
                presented_limitation_ids=(),
                conflict_ids=(),
            ),
        )
    candidate = GenerationCandidateV2(
        source_context_ids=tuple(item.context_id for item in generation_input.source_contexts),
        visible_comparison_ids=(),
        visible_conflict_ids=(),
        claims=claims,
    )
    raw = generation_raw(generation_response(candidate))
    trusted = TypeAdapter(tuple[EvidenceInput, ...]).validate_json(
        canonical_json(payload["trusted_evidence"])
    )
    parse_deepseek_generation_v2_response(raw, generation_input, trusted)
    return httpx.Response(
        200,
        headers={"content-type": "application/json"},
        content=raw,
        extensions={"http_version": b"HTTP/2"},
    )


@pytest.mark.parametrize("multi", (False, True))
def test_pubmed_to_qwen_to_human_review_export(
    database: PersistenceSettings, tmp_path: Path, multi: bool
) -> None:
    calls: list[str] = []

    def source_handler(request: httpx.Request) -> httpx.Response:
        calls.append("source:" + request.url.path)
        if multi and request.url.host == "dailymed.nlm.nih.gov":
            assert request.url.path.endswith("/spls.json")
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                json={
                    "metadata": {"current_page": "1", "pagesize": "100", "total_elements": "0"},
                    "data": [],
                },
            )
        if multi and request.url.host == "api.fda.gov":
            return httpx.Response(
                404,
                headers={"content-type": "application/json"},
                json={"error": {"code": "NOT_FOUND", "message": "No matches found!"}},
            )
        assert request.url.host == "eutils.ncbi.nlm.nih.gov"
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(200, content=search_xml("111", count=1))
        if request.url.path.endswith("efetch.fcgi"):
            return httpx.Response(200, content=_PUBMED_FETCH)
        raise AssertionError("unexpected source request")

    def generation_handler(request: httpx.Request) -> httpx.Response:
        calls.append("generation")
        return _generation_response(request)

    def qwen_handler(request: httpx.Request) -> httpx.Response:
        calls.append("qwen")
        assert request.url.host == "1234567890123456789.cn-beijing.maas.aliyuncs.com"
        return httpx.Response(
            200, headers={"content-type": "application/json"}, content=_envelope()
        )

    settings = LocalRuntimeSettings(
        database=database,
        snapshot_root=tmp_path / "snapshots",
        code_revision=subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            text=True,
        ).strip(),
        qwen_endpoint=_QWEN_ENDPOINT,
        qwen_api_key="sk-" + "q" * 50,
        generation_api_key="synthetic-generation-key",
    )
    idempotency = sha256_digest(str(tmp_path))
    transports = {
        "source_transport_factory": lambda: httpx.MockTransport(source_handler),
        "generation_transport": httpx.MockTransport(generation_handler),
        "qwen_transport": httpx.MockTransport(qwen_handler),
        "export_writer": LocalExportWriter._for_testing(tmp_path / "exports"),
    }
    with open_local_application(settings, **transports) as service:
        submitted = service.submit(
            ResearchSubmission(scope=_scope(multi), idempotency_key=idempotency)
        )
        assert submitted.status is ResearchRunStatus.SUBMITTED
    jobs = ResearchJobRepository(database)
    try:
        row = jobs.load(submitted.run_id)
        assert row is not None
        assert row["phase"] == "pending_review", (row["phase"], row["error_code"], calls)
    finally:
        jobs.close()
    with open_local_application(settings, **transports) as restarted:
        pending = restarted.get_run(submitted.run_id)
        assert pending.status is ResearchRunStatus.PENDING_REVIEW
        assert pending.report_content_hash is not None
        assert pending.render_document_hash is not None
        assert pending.pending_draft_id is not None
        report = restarted.get_report(submitted.run_id)
        assert report.document.report_content_hash == pending.report_content_hash
        assert {row.source for row in report.document.coverage} == set(
            _scope(multi).selected_sources
        )
        source_record = report.document.evidence_provenance[0]
        source_repository = PersistenceRepository(database)
        source_jobs = ResearchJobRepository(database)
        try:
            source_snapshots = SnapshotStore(settings.snapshot_root)
            material = SnapshotPubMedMaterialStore(
                snapshots=source_snapshots,
                repository=source_repository,
                provenance=VerifiedEvidenceProvenanceStore(
                    snapshots=source_snapshots, repository=source_repository
                ),
                local_jobs=source_jobs,
            )
            scope = _scope(multi)
            assert (
                material.load_verified_selection(
                    run_id="run:00000000-0000-4000-8000-000000000003",
                    scope=scope,
                    catalog=LocalResearchCatalogAdapter(scope).resolve(scope.scope_id),
                    publication_version_id=source_record.source_version,
                    snapshot_id=source_record.snapshot_id,
                )
                is None
            )
        finally:
            source_jobs.close()
            source_repository.close()
        reviewed = restarted.review(
            ResearchReviewCommand(
                run_id=pending.run_id,
                report_id=pending.report_id,
                report_content_hash=pending.report_content_hash,
                render_document_hash=pending.render_document_hash,
                pending_draft_id=pending.pending_draft_id,
                destination_id=pending.destination_id,
                reviewer_id="local-reviewer:synthetic",
                decision=ResearchReviewDecision.APPROVE,
                idempotency_key=sha256_digest(str(tmp_path) + ":approval"),
            )
        )
        assert reviewed.status is ResearchRunStatus.EXPORTED
        exported = restarted.download_export(reviewed.run_id, ResearchExportFormat.JSON)
        assert json.loads(exported.content)["marker"] == "MEDEVIDENCE_APPROVED_EXPORT_V1"
    assert sum(row.startswith("source:") for row in calls) == (4 if multi else 2)
    assert calls.count("generation") == 1
    assert calls.count("qwen") == 1


def test_source_failure_exposes_no_unsupported_claim_or_export(
    database: PersistenceSettings, tmp_path: Path
) -> None:
    calls: list[str] = []

    def source_handler(request: httpx.Request) -> httpx.Response:
        calls.append("source")
        assert request.url.host == "eutils.ncbi.nlm.nih.gov"
        return httpx.Response(400, content=b'{"error":"synthetic invalid query"}')

    def generation_handler(request: httpx.Request) -> httpx.Response:
        calls.append("generation")
        return _generation_response(request)

    def forbidden_semantic(_request: httpx.Request) -> httpx.Response:
        calls.append("qwen")
        raise AssertionError("no evidence means no semantic citation assessment")

    settings = LocalRuntimeSettings(
        database=database,
        snapshot_root=tmp_path / "snapshots-failure",
        code_revision=subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            text=True,
        ).strip(),
        qwen_endpoint=_QWEN_ENDPOINT,
        qwen_api_key="sk-" + "q" * 50,
        generation_api_key="synthetic-generation-key",
    )
    transports = {
        "source_transport_factory": lambda: httpx.MockTransport(source_handler),
        "generation_transport": httpx.MockTransport(generation_handler),
        "qwen_transport": httpx.MockTransport(forbidden_semantic),
    }
    with open_local_application(settings, **transports) as service:
        submitted = service.submit(
            ResearchSubmission(
                scope=_scope(), idempotency_key=sha256_digest(str(tmp_path) + ":failure")
            )
        )
    jobs = ResearchJobRepository(database)
    try:
        row = jobs.load(submitted.run_id)
        assert row is not None
        assert row["phase"] in ("blocked", "pending_review"), (row["error_code"], calls)
    finally:
        jobs.close()
    assert calls.count("source") >= 1 and calls.count("generation") == 1
    assert "qwen" not in calls
    with open_local_application(settings, **transports) as restarted:
        if row["phase"] == "pending_review":
            report = restarted.get_report(submitted.run_id)
            assert report.document.claims == ()
            assert report.document.coverage[0].result_status is not None
            assert report.document.coverage[0].result_status.value == "indeterminate"
        with pytest.raises(ResearchApplicationFailure):
            restarted.download_export(submitted.run_id, ResearchExportFormat.JSON)
