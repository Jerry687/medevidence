"""Unit tests for payload-free CADEC annotation parsing."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest

from medevidence.connectors.cadec import CadecParseError, parse_annotation_member
from medevidence.domain import derive_identity

FIXTURES = Path("tests/fixtures/cadec")


def _fixture(name: str) -> dict[str, object]:
    return cast(dict[str, object], json.loads((FIXTURES / name).read_text(encoding="utf-8")))


def _parse(rows: list[str], *, limited: bool = False):  # type: ignore[no-untyped-def]
    payload = ("\n".join(rows) + "\n").encode()
    member_path = "cadec/original/SYNTHETIC.1.ann"
    member_hash = hashlib.sha256(payload).hexdigest()
    limitations: frozenset[tuple[str, int, str, str]] = frozenset()
    if limited:
        limitations = frozenset(
            {
                (
                    member_path,
                    1,
                    member_hash,
                    hashlib.sha256(rows[0].encode()).hexdigest(),
                )
            }
        )
    return parse_annotation_member(
        payload,
        document_text=(FIXTURES / "synthetic-document.txt")
        .read_text(encoding="utf-8")
        .rstrip("\n"),
        document_id="SYNTHETIC.1",
        layer="original",
        member_path=member_path,
        member_sha256=member_hash,
        limited_row_identities=limitations,
    )


def test_original_entities_parse_and_notes_are_skipped_without_payload_retention() -> None:
    fixture = _fixture("synthetic-annotations.json")
    parsed = _parse(fixture["rows"])  # type: ignore[arg-type]

    assert len(parsed.annotations) == 1
    assert parsed.skipped_note_count == 1
    assert parsed.reference_binding_limitation_count == 0
    assert not hasattr(parsed.annotations[0], "term")
    assert not hasattr(parsed.annotations[0], "raw_row")


def test_raw_discontinuous_order_is_counted_then_unchanged_pairs_are_source_sorted() -> None:
    fixture = _fixture("synthetic-discontinuous-annotations.json")
    parsed = _parse(fixture["rows"])  # type: ignore[arg-type]

    assert [(span.start_offset, span.end_offset) for span in parsed.annotations[0].spans] == [
        (0, 5),
        (11, 16),
    ]
    assert parsed.raw_out_of_order_transition_count == 1
    assert parsed.has_raw_out_of_order_transition is True


def test_annotation_identity_is_bound_to_raw_row_and_physical_location() -> None:
    row = "T1\tADR 0 5\tAlpha"
    parsed = _parse([row])
    payload = f"{row}\n".encode()
    member_hash = hashlib.sha256(payload).hexdigest()

    assert parsed.annotations[0].annotation_id == derive_identity(
        "cadec-provider-row",
        {
            "document_id": "SYNTHETIC.1",
            "layer": "original",
            "member_path": "cadec/original/SYNTHETIC.1.ann",
            "physical_line": 1,
            "member_sha256": member_hash,
            "raw_row_sha256": hashlib.sha256(row.encode()).hexdigest(),
        },
    )


def test_exact_reference_binding_limitation_is_visible_but_not_malformed() -> None:
    parsed = _parse(["T1\tADR 0 5\tDifferent"], limited=True)

    assert parsed.annotations[0].reference_binding_limited is True
    assert parsed.reference_binding_limitation_count == 1


@pytest.mark.parametrize(
    "row, message",
    [
        ("T1\tADR 0 5", "three tab-separated"),
        ("TT\tADR 0 5\tAlpha", "identifier"),
        ("T1\tADR 0 5\tAlpha\textra", "three tab-separated"),
        ("T1\tADR 00 5\tAlpha", "canonical ASCII"),
        ("T1\tADR 0 5;0 5\tAlpha Alpha", "duplicate span"),
        ("T1\tADR 0 5;4 10\tAlpha a bet", "overlap"),
        ("T1\tADR 0 5\tDifferent", "reference-binding state"),
    ],
)
def test_rows_fail_closed_without_repair(row: str, message: str) -> None:
    with pytest.raises(CadecParseError, match=message):
        _parse([row])


def test_out_of_bounds_fixture_fails_closed() -> None:
    fixture = _fixture("synthetic-invalid-offsets.json")
    with pytest.raises(CadecParseError, match="code-point bounds"):
        _parse(fixture["rows"])  # type: ignore[arg-type]


def test_normalization_layer_requires_tt_and_uses_right_anchored_spans() -> None:
    payload = b"TT1\tSomeReference 0 5\tAlpha\n"
    member_hash = hashlib.sha256(payload).hexdigest()

    parsed = parse_annotation_member(
        payload,
        document_text="Alpha beta",
        document_id="SYNTHETIC.1",
        layer="meddra",
        member_path="cadec/meddra/SYNTHETIC.1.ann",
        member_sha256=member_hash,
        limited_row_identities=frozenset(),
    )

    assert len(parsed.annotations) == 1
    assert parsed.annotations[0].spans[0].start_offset == 0


def test_cp1252_exception_requires_the_exact_production_member_hash() -> None:
    payload = b"TT\tReference 0 1\t\x80\n"
    with pytest.raises(CadecParseError, match="hash differs"):
        parse_annotation_member(
            payload,
            document_text="€",
            document_id="LIPITOR.253",
            layer="sct",
            member_path="cadec/sct/LIPITOR.253.ann",
            member_sha256=hashlib.sha256(payload).hexdigest(),
            limited_row_identities=frozenset(),
        )
