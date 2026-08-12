from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from medevidence.connectors.dailymed.parsing import (
    DailyMedParseError,
    parse_candidate_page,
    parse_historical_zip,
    parse_history_page,
    parse_spl_document,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "dailymed"
SETID = "11111111-1111-1111-1111-111111111111"
VERSION = "3"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def _zip(entries: list[tuple[str, bytes]], *, symlink: bool = False) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for index, (name, body) in enumerate(entries):
            info = zipfile.ZipInfo(name)
            if symlink and index == 0:
                info.create_system = 3
                info.external_attr = 0o120777 << 16
            archive.writestr(info, body)
    payload = buffer.getvalue()
    for name, _ in entries:
        if "\\" in name:
            normalized = name.replace("\\", "/").encode()
            payload = payload.replace(normalized, name.encode())
    return payload


@pytest.mark.parametrize(
    ("fixture", "count"),
    [
        ("candidates-no-match.json", 0),
        ("candidates-exact.json", 1),
        ("candidates-equivalent.json", 2),
        ("candidates-ambiguous.json", 2),
    ],
)
def test_parses_frozen_candidate_selection_inputs(fixture: str, count: int) -> None:
    page = parse_candidate_page(_fixture(fixture))
    assert len(page.candidates) == count
    assert page.total == count
    if page.candidates:
        assert page.candidates[0].spl_versions == tuple(
            sorted(page.candidates[0].spl_versions, key=int)
        )


def test_parses_exact_setid_history() -> None:
    page = parse_history_page(_fixture("setid-history.json"), expected_setid=SETID)
    assert [record.spl_version for record in page.records] == ["2", "3"]
    assert all(record.setid == SETID for record in page.records)


@pytest.mark.parametrize("parser_kind", ["candidate", "history"])
@pytest.mark.parametrize(
    ("rows", "metadata"),
    [
        ([{}], {"page": 1, "pagesize": 1, "total": 0}),
        ([{}, {}], {"page": 1, "pagesize": 1, "total": 2}),
        ([{}, {}], {"page": 1, "pagesize": 2, "total": 1}),
        ([], {"page": 1, "pagesize": 1, "total": 2}),
        ([{}], {"page": 2, "pagesize": 1, "total": 1}),
    ],
)
def test_pagination_rejects_every_observed_tuple_contradiction(
    parser_kind: str, rows: list[object], metadata: dict[str, int]
) -> None:
    if parser_kind == "candidate":
        populated = [
            {
                "setid": SETID,
                "spl_version": "3",
                "ingredients": ["synthetic"],
            }
            for _ in rows
        ]
    else:
        populated = [
            {"setid": SETID, "spl_version": "3", "marketing_state": "active"} for _ in rows
        ]
    payload = json.dumps({"data": populated, "metadata": metadata}).encode()
    with pytest.raises(DailyMedParseError, match=r"contradict|exceeds"):
        if parser_kind == "candidate":
            parse_candidate_page(payload, expected_page=metadata["page"])
        else:
            parse_history_page(payload, expected_setid=SETID, expected_page=metadata["page"])


@pytest.mark.parametrize("parser_kind", ["candidate", "history"])
def test_page_five_retains_provider_more_pages_state(parser_kind: str) -> None:
    metadata = {"page": 5, "pagesize": 1, "total": 100}
    row = {"setid": SETID, "spl_version": "3", "marketing_state": "active"}
    payload = json.dumps(
        {"data": [row | {"ingredients": ["synthetic"]}], "metadata": metadata}
    ).encode()
    page = (
        parse_candidate_page(payload, expected_page=5)
        if parser_kind == "candidate"
        else parse_history_page(payload, expected_setid=SETID, expected_page=5)
    )
    assert page.next_page == 6


@pytest.mark.parametrize("parser_kind", ["candidate", "history"])
def test_pagination_rejects_typed_request_pagesize_drift(parser_kind: str) -> None:
    row = {
        "setid": SETID,
        "spl_version": "3",
        "ingredients": ["synthetic"],
        "marketing_state": "active",
    }
    payload = json.dumps(
        {"data": [row], "metadata": {"page": 1, "pagesize": 2, "total": 1}}
    ).encode()
    with pytest.raises(DailyMedParseError, match="typed request"):
        if parser_kind == "candidate":
            parse_candidate_page(payload, expected_pagesize=1)
        else:
            parse_history_page(payload, expected_setid=SETID, expected_pagesize=1)


def test_parses_valid_spl_identity_and_canonical_sections() -> None:
    parsed = parse_spl_document(
        _fixture("spl-valid.xml"), expected_setid=SETID, expected_spl_version=VERSION
    )
    assert (parsed.setid, parsed.spl_version) == (SETID, VERSION)
    assert [section.section_code for section in parsed.sections] == ["34084-4", "43685-7"]
    assert all(section.text_end > section.text_start for section in parsed.sections)
    assert parsed.canonical_text[parsed.sections[0].text_start : parsed.sections[0].text_end] == (
        parsed.sections[0].text
    )


@pytest.mark.parametrize(
    "fixture",
    [
        "spl-malformed.xml",
        "spl-dtd.xml",
        "spl-entity.xml",
        "spl-wrong-namespace.xml",
        "spl-truncated.xml",
    ],
)
def test_spl_parser_fails_closed(fixture: str) -> None:
    with pytest.raises(DailyMedParseError):
        parse_spl_document(_fixture(fixture), expected_setid=SETID, expected_spl_version=VERSION)


def test_spl_rejects_duplicate_nested_and_namespaced_identity_lookalikes() -> None:
    duplicate = _fixture("spl-valid.xml").replace(
        b'<versionNumber value="3" displayName="synthetic"/>',
        b'<versionNumber value="3"/><versionNumber value="3"/>',
    )
    with pytest.raises(DailyMedParseError):
        parse_spl_document(duplicate, expected_setid=SETID, expected_spl_version=VERSION)
    nested = (
        _fixture("spl-valid.xml")
        .replace(b"<setId ", b"<component><setId ", 1)
        .replace(b"/>\n  <versionNumber", b"/></component>\n  <versionNumber", 1)
    )
    with pytest.raises(DailyMedParseError):
        parse_spl_document(nested, expected_setid=SETID, expected_spl_version=VERSION)


@pytest.mark.parametrize(
    "construct",
    [
        '<evil:include xmlns:evil="http://www.w3.org/2001/XInclude" href="file:///x"/>',
        '<evil:stylesheet xmlns:evil="http://www.w3.org/1999/XSL/Transform"/>',
        '<evil:schema xmlns:evil="http://www.w3.org/2001/XMLSchema"/>',
        '<component xmlns:x="http://www.w3.org/2001/XMLSchema-instance" '
        'x:schemaLocation="urn:hl7-org:v3 https://evil.invalid/schema.xsd"/>',
    ],
)
def test_spl_rejects_forbidden_constructs_by_expanded_name(construct: str) -> None:
    payload = (
        f'<document xmlns="urn:hl7-org:v3"><setId root="{SETID}"/>'
        f'<versionNumber value="{VERSION}"/>{construct}</document>'
    ).encode()
    with pytest.raises(DailyMedParseError, match="forbidden"):
        parse_spl_document(payload, expected_setid=SETID, expected_spl_version=VERSION)


def test_spl_counts_decoded_attribute_values_at_exact_total_boundary() -> None:
    identity_characters = len(SETID) + len(VERSION)

    def payload(extra: int) -> bytes:
        filler = "x" * (5_000_000 - identity_characters + extra)
        return (
            f'<document xmlns="urn:hl7-org:v3" safe="{filler}">'
            f'<setId root="{SETID}"/><versionNumber value="{VERSION}"/></document>'
        ).encode()

    assert (
        parse_spl_document(
            payload(0), expected_setid=SETID, expected_spl_version=VERSION
        ).canonical_text
        == ""
    )
    with pytest.raises(DailyMedParseError, match="decoded-character"):
        parse_spl_document(payload(1), expected_setid=SETID, expected_spl_version=VERSION)


def test_nested_sections_have_replayable_paths_and_exact_parent_identity() -> None:
    xml = f"""<document xmlns="urn:hl7-org:v3">
      <setId root="{SETID}"/><versionNumber value="{VERSION}"/>
      <component><structuredBody><component><section>
        <code code="34066-1" codeSystem="2.16.840.1.113883.6.1"/>
        <title>FDA package insert Boxed warning section</title><text>parent</text>
        <component><section>
          <code code="34084-4" codeSystem="2.16.840.1.113883.6.1"/>
          <title>FDA package insert Adverse reactions section</title><text>child</text>
        </section></component>
      </section></component></structuredBody></component>
    </document>""".encode()
    parsed = parse_spl_document(xml, expected_setid=SETID, expected_spl_version=VERSION)
    parent, child = parsed.sections
    assert parent.xml_path == "/document/component[1]/structuredBody[1]/component[1]/section[1]"
    assert child.xml_path == f"{parent.xml_path}/component[1]/section[1]"
    assert parent.parent_section_ordinal is None
    assert child.parent_section_ordinal == parent.section_ordinal

    promoted_xml = xml.replace(
        b'<component><section>\n          <code code="34084-4"',
        b'</section></component><component><section>\n          <code code="34084-4"',
    ).replace(
        b"</section></component>\n      </section></component></structuredBody>",
        b"</section></component></structuredBody>",
    )
    promoted = parse_spl_document(promoted_xml, expected_setid=SETID, expected_spl_version=VERSION)
    assert promoted.sections[1].parent_section_ordinal is None
    assert promoted.sections[1].xml_path != child.xml_path


def test_historical_zip_accepts_exactly_one_safe_spl_without_extraction(tmp_path: Path) -> None:
    before = tuple(tmp_path.iterdir())
    parsed = parse_historical_zip(
        _zip([("labels/synthetic.XML", _fixture("spl-valid.xml")), ("readme.txt", b"safe")]),
        expected_setid=SETID,
        expected_spl_version=VERSION,
    )
    assert parsed.source_member_name == "labels/synthetic.XML"
    assert tuple(tmp_path.iterdir()) == before


@pytest.mark.parametrize("codepoint", [*range(32), 127])
def test_historical_zip_rejects_all_c0_and_del_before_normalization(codepoint: int) -> None:
    with pytest.raises(DailyMedParseError):
        parse_historical_zip(
            _zip([(f"safe{chr(codepoint)}label.xml", _fixture("spl-valid.xml"))]),
            expected_setid=SETID,
            expected_spl_version=VERSION,
        )


@pytest.mark.parametrize(
    "name",
    [
        "/label.xml",
        "../label.xml",
        "a//label.xml",
        "a/./label.xml",
        "a\\label.xml",
        "C:label.xml",
        "NUL.xml",
    ],
)
def test_historical_zip_rejects_unsafe_paths(name: str) -> None:
    with pytest.raises(DailyMedParseError):
        parse_historical_zip(
            _zip([(name, _fixture("spl-valid.xml"))]),
            expected_setid=SETID,
            expected_spl_version=VERSION,
        )


def test_historical_zip_rejects_symlink_malformed_xml_and_multiple_spl_candidates() -> None:
    for payload in (
        _zip([("label.xml", _fixture("spl-valid.xml"))], symlink=True),
        _zip([("label.xml", _fixture("spl-malformed.xml"))]),
        _zip([("a.xml", _fixture("spl-valid.xml")), ("b.xml", _fixture("spl-valid.xml"))]),
    ):
        with pytest.raises(DailyMedParseError):
            parse_historical_zip(payload, expected_setid=SETID, expected_spl_version=VERSION)
