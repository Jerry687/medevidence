from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from evaluation import dev40_corpus
from evaluation.dev40_corpus import Dev40CorpusError


def _book_item() -> dict[str, Any]:
    text = "Retained book abstract"
    return {
        "retrieval_unit_kind": "pubmed_book_document",
        "provider_record_kind": "PubmedBookArticle",
        "mapping_disposition": "source_native_retained_not_coerced",
        "retrieval_unit_id": dev40_corpus.BOOK_RETRIEVAL_ID,
        "source": "pubmed",
        "stable_source_id": "31644235",
        "pmid": "31644235",
        "book_accession": "NBK548929",
        "title": "LiverTox book document",
        "book_title": "LiverTox",
        "text": text,
        "text_sha256": dev40_corpus._sha256(text.encode()),
        "source_locator": "https://pubmed.ncbi.nlm.nih.gov/31644235/",
        "source_version_identity": "pmid:31644235:book-content-sha256:x",
        "content_identity": "sha256:x",
        "source_identity": "pubmed-book-document:31644235:NBK548929",
        "lineage": {},
    }


def test_book_variant_is_distinct_and_has_no_journal() -> None:
    item = _book_item()
    dev40_corpus._validate_book_unit(item)
    assert item["title"] != item["book_title"]
    assert "journal" not in item


def test_book_variant_rejects_journal_coercion_and_wrong_identity() -> None:
    item = _book_item()
    item["journal"] = "LiverTox"
    with pytest.raises(Dev40CorpusError, match="coerced"):
        dev40_corpus._validate_book_unit(item)
    item = _book_item()
    item["book_accession"] = "wrong"
    with pytest.raises(Dev40CorpusError, match="identity"):
        dev40_corpus._validate_book_unit(item)


def test_retrieval_union_rejects_identity_collision_before_count_acceptance() -> None:
    item = _book_item()
    with pytest.raises(Dev40CorpusError, match="duplicated"):
        dev40_corpus.validate_retrieval_units([item, item])


def test_packet_blindness_rejects_all_prohibited_field_families() -> None:
    for key in (
        "qrels",
        "owner_grade",
        "rank",
        "score",
        "retriever",
        "bm25",
        "medcpt",
        "rrf",
        "nomination",
    ):
        with pytest.raises(Dev40CorpusError, match="forbidden field"):
            dev40_corpus._validate_packet_blindness({"nested": [{key: 1}]})


def test_frozen_layer_mapping_selects_only_exact_23_retrieval_questions() -> None:
    if not dev40_corpus.GAP_PATH.exists():
        pytest.skip("external frozen Dev-40 question evidence unavailable")
    questions, layers = dev40_corpus._question_records()
    selected = [
        row["question_id"]
        for row in questions
        if row["question_id"] in {f"Q{index}" for index in range(1, 11)}
        or layers.get(row["question_id"]) == "retrieval"
    ]
    assert tuple(selected) == dev40_corpus.RETRIEVAL_QUESTION_IDS
    assert "Q35" not in selected
    assert "Q36" not in selected


def test_actual_retained_sources_reconcile_book_once_and_gold_unchanged() -> None:
    if not dev40_corpus.ACQUISITION_ROOT.exists():
        pytest.skip("external retained Dev-40 acquisition unavailable")
    gold_before = dev40_corpus.GOLD_MANIFEST_PATH.read_bytes()
    items, pair_counts = dev40_corpus._parse_pubmed_extensions()
    books = [item for item in items if item.get("retrieval_unit_kind") == "pubmed_book_document"]
    assert len(books) == 1
    assert books[0]["retrieval_unit_id"] == "pubmed-book:31644235"
    assert books[0]["book_accession"] == "NBK548929"
    assert "journal" not in books[0]
    assert pair_counts["pubmed-C-tirzepatide-gi-2020-2025"] == {
        "requested": 100,
        "pubmed_articles": 99,
        "pubmed_book_documents": 1,
        "operation_sha256": "03dc8f4a3ab40b75448afe5add68b814dab0469cf40ee8c11e3f53783579a4d8",
        "binding_sha256": "4d5f926bfbc46481ad0ae09938e5f40ab8fb66edafa053b65ff01bff2bd39d48",
        "raw_sha256": "b02aec0b657566f31f5bc86f481e74847b8f7615a4192a12946124f49024b0f8",
    }
    assert dev40_corpus.GOLD_MANIFEST_PATH.read_bytes() == gold_before


def test_freeze_and_loader_fail_closed_on_tamper(tmp_path: Path) -> None:
    if not dev40_corpus.ACQUISITION_ROOT.exists():
        pytest.skip("external retained Dev-40 acquisition unavailable")
    root = tmp_path / "freeze"
    result = dev40_corpus.freeze_dev40(root, _allow_test_root=True)
    assert result.corpus_units == 214
    assert result.adjudication_questions == 23
    manifest = json.loads((root / "corpus-manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"] == {
        "dailymed_section": 15,
        "pubmed_article": 198,
        "pubmed_book_document": 1,
        "pubmed_total": 199,
        "total": 214,
    }
    assert (
        sum(item.get("retrieval_unit_kind") == "pubmed_book_document" for item in manifest["items"])
        == 1
    )
    frozen_by_id = {item["retrieval_unit_id"]: item for item in manifest["items"]}
    gold = json.loads(dev40_corpus.GOLD_MANIFEST_PATH.read_text(encoding="utf-8"))
    assert all(frozen_by_id[item["retrieval_unit_id"]] == item for item in gold["items"])
    packet = json.loads((root / "blinded-adjudication-packet.json").read_text(encoding="utf-8"))
    assert len(packet["questions"]) == 23
    assert all(len(row["candidates"]) == 214 for row in packet["questions"])
    assert packet["excluded_non_retrieval_questions"]
    assert "Q35" in {row["question_id"] for row in packet["excluded_non_retrieval_questions"]}
    state = json.loads((root / "source-state-inventory.json").read_text(encoding="utf-8"))
    assert state["cadec"]["status"] == "unavailable_not_materialized"
    assert state["cadec"]["corpus_units"] == 0
    assert state["faers_d"]["corpus_units"] == 0
    dev40_corpus.load_and_validate_freeze(root)
    path = root / "corpus-manifest.json"
    path.write_bytes(path.read_bytes().replace(b'"total":214', b'"total":213'))
    with pytest.raises(Dev40CorpusError, match="sidecar mismatch"):
        dev40_corpus.load_and_validate_freeze(root)


def test_loader_rejects_resigned_candidate_set_substitution(tmp_path: Path) -> None:
    if not dev40_corpus.ACQUISITION_ROOT.exists():
        pytest.skip("external retained Dev-40 acquisition unavailable")
    root = tmp_path / "freeze"
    dev40_corpus.freeze_dev40(root, _allow_test_root=True)
    packet_path = root / "blinded-adjudication-packet.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["questions"][0]["candidates"][0]["retrieval_unit_id"] = packet["questions"][0][
        "candidates"
    ][1]["retrieval_unit_id"]
    dev40_corpus._write_json(packet_path, packet)
    with pytest.raises(Dev40CorpusError, match="exact corpus"):
        dev40_corpus.load_and_validate_freeze(root)


def test_loader_rejects_resigned_manifest_provider_content_substitution(
    tmp_path: Path,
) -> None:
    if not dev40_corpus.ACQUISITION_ROOT.exists():
        pytest.skip("external retained Dev-40 acquisition unavailable")
    root = tmp_path / "freeze"
    dev40_corpus.freeze_dev40(root, _allow_test_root=True)
    manifest_path = root / "corpus-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    article = next(
        item for item in manifest["items"] if item["retrieval_unit_id"] == "pubmed:26358288"
    )
    article["title"] = "re-signed provider-content substitution"
    article["text"] = "re-signed provider-content substitution"
    article["text_sha256"] = dev40_corpus._sha256(article["text"].encode())
    manifest_sha = dev40_corpus._write_json(manifest_path, manifest)
    packet_path = root / "blinded-adjudication-packet.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["corpus_manifest_sha256"] = manifest_sha
    dev40_corpus._write_json(packet_path, packet)
    with pytest.raises(Dev40CorpusError, match="exact corpus"):
        dev40_corpus.load_and_validate_freeze(root)


def test_loader_rejects_resigned_packet_candidate_content_divergence(tmp_path: Path) -> None:
    if not dev40_corpus.ACQUISITION_ROOT.exists():
        pytest.skip("external retained Dev-40 acquisition unavailable")
    root = tmp_path / "freeze"
    dev40_corpus.freeze_dev40(root, _allow_test_root=True)
    packet_path = root / "blinded-adjudication-packet.json"
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    packet["questions"][0]["candidates"][0]["title"] = "stale packet divergence"
    dev40_corpus._write_json(packet_path, packet)
    with pytest.raises(Dev40CorpusError, match="exact corpus"):
        dev40_corpus.load_and_validate_freeze(root)


def test_loader_rejects_resigned_run_plan_authority_substitution(tmp_path: Path) -> None:
    if not dev40_corpus.ACQUISITION_ROOT.exists():
        pytest.skip("external retained Dev-40 acquisition unavailable")
    root = tmp_path / "freeze"
    dev40_corpus.freeze_dev40(root, _allow_test_root=True)
    run_plan_path = root / "run-plan.json"
    run_plan = json.loads(run_plan_path.read_text(encoding="utf-8"))
    run_plan["medical_source_requests"] = 99
    run_plan["holdout_accessed"] = True
    dev40_corpus._write_json(run_plan_path, run_plan)
    with pytest.raises(Dev40CorpusError, match="exact corpus"):
        dev40_corpus.load_and_validate_freeze(root)


def test_loader_rejects_resigned_source_state_authority_substitution(tmp_path: Path) -> None:
    if not dev40_corpus.ACQUISITION_ROOT.exists():
        pytest.skip("external retained Dev-40 acquisition unavailable")
    root = tmp_path / "freeze"
    dev40_corpus.freeze_dev40(root, _allow_test_root=True)
    state_path = root / "source-state-inventory.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["network_operations"] = 99
    state["holdout_accessed"] = True
    state["faers_d"]["raw_sha256"] = "0" * 64
    state["cadec"]["status"] = "materialized"
    state["cadec"]["corpus_units"] = 99
    dev40_corpus._write_json(state_path, state)
    with pytest.raises(Dev40CorpusError, match="exact corpus"):
        dev40_corpus.load_and_validate_freeze(root)


def test_cli_is_explicit_and_has_no_network_mode() -> None:
    from evaluation.run_dev40_corpus import build_parser

    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["--output-root", str(dev40_corpus.OUTPUT_ROOT)])
    actions = {option for action in parser._actions for option in action.option_strings}
    assert "--freeze" in actions
    assert "--verify" in actions
    assert all("network" not in action for action in actions)
