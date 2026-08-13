"""Unit tests for dataset loading and its strictness guarantees."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from evaluation.datasets import (
    load_beir_directory,
    load_jsonl_dataset,
    relevance_grade_histogram,
)

FIXTURE = Path(__file__).resolve().parents[3] / "tests/fixtures/retrieval/harness_smoke.json"


def write_beir(root: Path, *, qrels_rows: list[str] | None = None) -> Path:
    (root / "qrels").mkdir(parents=True, exist_ok=True)
    (root / "corpus.jsonl").write_text(
        "\n".join(
            json.dumps({"_id": f"d{i}", "title": f"t{i}", "text": f"body {i} nausea"})
            for i in range(1, 4)
        ),
        encoding="utf-8",
    )
    (root / "queries.jsonl").write_text(
        json.dumps({"_id": "q1", "text": "nausea"}), encoding="utf-8"
    )
    rows = qrels_rows if qrels_rows is not None else ["query-id\tcorpus-id\tscore", "q1\td1\t2"]
    (root / "qrels" / "test.tsv").write_text("\n".join(rows), encoding="utf-8")
    return root


class TestBeirLoading:
    def test_loads_the_standard_layout(self, tmp_path: Path) -> None:
        dataset = load_beir_directory(write_beir(tmp_path))
        assert dataset.summary() == {
            "documents": 3,
            "queries": 1,
            "judged_queries": 1,
            "judgments": 1,
            "positive_judgments": 1,
        }

    def test_header_row_is_skipped(self, tmp_path: Path) -> None:
        dataset = load_beir_directory(write_beir(tmp_path))
        assert dataset.qrels["q1"] == {"d1": 2}

    def test_title_and_body_are_joined_for_indexing(self, tmp_path: Path) -> None:
        dataset = load_beir_directory(write_beir(tmp_path))
        assert dataset.document_text("d1").startswith("t1\n")

    def test_missing_file_is_reported(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError):
            load_beir_directory(tmp_path)

    def test_judgment_on_unknown_document_is_rejected(self, tmp_path: Path) -> None:
        root = write_beir(tmp_path, qrels_rows=["query-id\tcorpus-id\tscore", "q1\tmissing\t2"])
        with pytest.raises(ValueError, match="absent from the corpus"):
            load_beir_directory(root)

    def test_zero_grade_judgment_on_unknown_document_is_rejected(self, tmp_path: Path) -> None:
        root = write_beir(tmp_path, qrels_rows=["query-id\tcorpus-id\tscore", "q1\tmissing\t0"])
        with pytest.raises(ValueError, match="absent from the corpus"):
            load_beir_directory(root)

    def test_judgment_on_unknown_query_is_rejected(self, tmp_path: Path) -> None:
        root = write_beir(tmp_path, qrels_rows=["query-id\tcorpus-id\tscore", "qX\td1\t2"])
        with pytest.raises(ValueError, match="unknown query ids"):
            load_beir_directory(root)

    def test_non_integer_grade_is_rejected(self, tmp_path: Path) -> None:
        root = write_beir(tmp_path, qrels_rows=["query-id\tcorpus-id\tscore", "q1\td1\thigh"])
        with pytest.raises(ValueError, match="non-integer grade"):
            load_beir_directory(root)

    @pytest.mark.parametrize("grade", ["-1", "11"])
    def test_out_of_range_grade_is_rejected(self, tmp_path: Path, grade: str) -> None:
        root = write_beir(tmp_path, qrels_rows=["query-id\tcorpus-id\tscore", f"q1\td1\t{grade}"])
        with pytest.raises(ValueError, match="out of range"):
            load_beir_directory(root)

    @pytest.mark.parametrize(
        ("row", "message"),
        [
            ("", "is blank"),
            ("q1\td1", "exactly three"),
            ("q1\td1\t2\textra", "exactly three"),
            ("\td1\t2", "empty field"),
            ("q1\t\t2", "empty field"),
            ("q1\td1\t", "empty field"),
        ],
    )
    def test_malformed_qrel_row_is_rejected(self, tmp_path: Path, row: str, message: str) -> None:
        rows = ["query-id\tcorpus-id\tscore", row]
        if not row:
            rows.append("q1\td1\t2")
        root = write_beir(tmp_path, qrels_rows=rows)
        with pytest.raises(ValueError, match=message):
            load_beir_directory(root)

    def test_header_only_qrels_is_rejected(self, tmp_path: Path) -> None:
        root = write_beir(tmp_path, qrels_rows=["query-id\tcorpus-id\tscore"])
        with pytest.raises(ValueError, match="contains no judgments"):
            load_beir_directory(root)

    @pytest.mark.parametrize("second_grade", ["2", "1"])
    def test_duplicate_judgment_is_rejected(self, tmp_path: Path, second_grade: str) -> None:
        root = write_beir(
            tmp_path,
            qrels_rows=[
                "query-id\tcorpus-id\tscore",
                "q1\td1\t2",
                f"q1\td1\t{second_grade}",
            ],
        )
        with pytest.raises(ValueError, match="duplicates judgment"):
            load_beir_directory(root)

    def test_truncation_keeps_positives_and_warns(self, tmp_path: Path) -> None:
        root = write_beir(tmp_path, qrels_rows=["query-id\tcorpus-id\tscore", "q1\td3\t2"])
        dataset = load_beir_directory(root, max_documents=1)
        assert "d3" in dataset.corpus  # judged document is never dropped
        assert dataset.warnings and "truncated" in dataset.warnings[0]

    def test_truncation_keeps_zero_grade_judged_documents(self, tmp_path: Path) -> None:
        root = write_beir(
            tmp_path,
            qrels_rows=["query-id\tcorpus-id\tscore", "q1\td1\t2", "q1\td3\t0"],
        )
        dataset = load_beir_directory(root, max_documents=1)
        assert "d3" in dataset.corpus

    def test_records_distribution_and_consumed_file_hashes(self, tmp_path: Path) -> None:
        root = write_beir(tmp_path / "dataset")
        archive = tmp_path / "nfcorpus.zip"
        archive.write_bytes(b"frozen distribution")
        dataset = load_beir_directory(
            root,
            dataset_id="NFCorpus",
            dataset_source="https://example.invalid/nfcorpus.zip",
            distribution_archive=archive,
        )
        assert dataset.distribution is not None
        assert dataset.distribution.bytes == len(b"frozen distribution")
        assert dataset.distribution.sha256 == hashlib.sha256(b"frozen distribution").hexdigest()
        assert {identity.path for identity in dataset.consumed_files} == {
            "corpus.jsonl",
            "queries.jsonl",
            "qrels/test.tsv",
        }
        for identity in dataset.consumed_files:
            consumed = root / Path(identity.path)
            assert identity.bytes == consumed.stat().st_size
            assert identity.sha256 == hashlib.sha256(consumed.read_bytes()).hexdigest()

    def test_duplicate_corpus_id_is_rejected(self, tmp_path: Path) -> None:
        root = write_beir(tmp_path)
        (root / "corpus.jsonl").write_text(
            json.dumps({"_id": "d1", "text": "a"}) + "\n" + json.dumps({"_id": "d1", "text": "b"}),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="duplicate corpus id"):
            load_beir_directory(root)

    def test_malformed_json_line_is_reported_with_position(self, tmp_path: Path) -> None:
        root = write_beir(tmp_path)
        (root / "corpus.jsonl").write_text("{not json}", encoding="utf-8")
        with pytest.raises(ValueError, match="line 1 is not valid JSON"):
            load_beir_directory(root)


class TestJsonlDataset:
    def test_loads_the_repository_fixture(self) -> None:
        dataset = load_jsonl_dataset(FIXTURE)
        summary = dataset.summary()
        assert summary["documents"] == 30
        assert summary["judged_queries"] == 8

    def test_fixture_declares_its_synthetic_origin(self) -> None:
        dataset = load_jsonl_dataset(FIXTURE)
        assert "SYNTHETIC" in dataset.notes
        assert "NOT by medical adjudication" in dataset.notes

    def test_zero_grades_do_not_count_as_judged(self) -> None:
        dataset = load_jsonl_dataset(FIXTURE)
        assert all(
            any(grade > 0 for grade in dataset.qrels[query_id].values())
            for query_id in dataset.judged_queries
        )

    def test_duplicate_json_qrel_key_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "duplicate.json"
        path.write_text(
            '{"corpus":[{"_id":"d1","text":"x"}],'
            '"queries":[{"_id":"q1","text":"x"}],'
            '"qrels":{"q1":{"d1":2,"d1":2}}}',
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="duplicate JSON key"):
            load_jsonl_dataset(path)

    def test_non_integer_json_grade_is_rejected(self, tmp_path: Path) -> None:
        path = tmp_path / "bad-grade.json"
        path.write_text(
            json.dumps(
                {
                    "corpus": [{"_id": "d1", "text": "x"}],
                    "queries": [{"_id": "q1", "text": "x"}],
                    "qrels": {"q1": {"d1": 1.5}},
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="non-integer grade"):
            load_jsonl_dataset(path)

    @pytest.mark.parametrize("missing", ["qrels", "queries", "corpus"])
    def test_missing_required_root_field_is_rejected(self, tmp_path: Path, missing: str) -> None:
        payload = {
            "corpus": [{"_id": "d1", "text": "x"}],
            "queries": [{"_id": "q1", "text": "x"}],
            "qrels": {"q1": {"d1": 1}},
        }
        del payload[missing]
        path = tmp_path / "missing.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        with pytest.raises(ValueError, match="missing required"):
            load_jsonl_dataset(path)

    @pytest.mark.parametrize(
        ("qrels", "message"),
        [({}, "no qrels"), ({"q1": {}}, "empty judgment maps"), ({"q1": {"d1": 0}}, "zero judged")],
    )
    def test_empty_or_unevaluable_qrels_are_rejected(
        self, tmp_path: Path, qrels: dict[str, dict[str, int]], message: str
    ) -> None:
        path = tmp_path / "empty-qrels.json"
        path.write_text(
            json.dumps(
                {
                    "corpus": [{"_id": "d1", "text": "x"}],
                    "queries": [{"_id": "q1", "text": "x"}],
                    "qrels": qrels,
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match=message):
            load_jsonl_dataset(path)


class TestHistogram:
    def test_counts_by_grade(self) -> None:
        assert relevance_grade_histogram({"q": {"a": 2, "b": 2, "c": 0}}) == {0: 1, 2: 2}
