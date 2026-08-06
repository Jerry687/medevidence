from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from medevidence.connectors.pubmed.parsing import (
    IncompletePubMedXmlError,
    InvalidPubMedXmlError,
    MalformedRecordCode,
    PubMedXmlErrorCode,
    parse_fetch_response,
    parse_search_page,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "pubmed"
SEARCH_FIXTURE_MAX_ITEMS = 2
FETCH_FIXTURE_MAX_ITEMS = 4


def fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def article(pmid: str, *, title: str = "Title", status: str = "MEDLINE") -> str:
    return f"""
    <PubmedArticle>
      <MedlineCitation Status="{status}">
        <PMID>{pmid}</PMID>
        <Article>
          <Journal><Title>Journal</Title></Journal>
          <ArticleTitle>{title}</ArticleTitle>
          <Language>eng</Language>
        </Article>
      </MedlineCitation>
    </PubmedArticle>
    """


def test_parse_valid_search_page_preserves_pmid_order() -> None:
    page = parse_search_page(
        fixture("valid_search.xml"),
        expected_retstart=0,
        max_items=SEARCH_FIXTURE_MAX_ITEMS,
    )

    assert page.count == 3
    assert page.retmax == 2
    assert page.retstart == 0
    assert page.pmids == ("111", "222")


def test_parse_empty_search_page() -> None:
    payload = b"""
    <eSearchResult>
      <Count>0</Count><RetMax>0</RetMax><RetStart>0</RetStart><IdList />
    </eSearchResult>
    """

    page = parse_search_page(payload, expected_retstart=0, max_items=1)

    assert page.count == 0
    assert page.pmids == ()


@pytest.mark.parametrize(
    "payload",
    [
        b"<eSearchResult>",
        b'<!DOCTYPE eSearchResult [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        b"<eSearchResult><Count>&xxe;</Count></eSearchResult>",
        b'<!DOCTYPE eSearchResult SYSTEM "https://example.invalid/pubmed.dtd"><eSearchResult />',
    ],
)
def test_malformed_dtd_entity_and_external_xml_fail_closed(payload: bytes) -> None:
    with pytest.raises(InvalidPubMedXmlError) as error:
        parse_search_page(payload, expected_retstart=0, max_items=1)

    assert error.value.code is PubMedXmlErrorCode.INVALID_OR_UNSAFE_XML


@pytest.mark.parametrize(
    "payload",
    [
        b"<notESearchResult />",
        b"<eSearchResult><RetMax>0</RetMax><RetStart>0</RetStart><IdList /></eSearchResult>",
        b"<eSearchResult><Count>1</Count><RetMax>0</RetMax>"
        b"<RetStart>0</RetStart><IdList /></eSearchResult>",
        b"<eSearchResult><Count>1</Count><RetMax>1</RetMax>"
        b"<RetStart>1</RetStart><IdList><Id>1</Id></IdList></eSearchResult>",
        b"<eSearchResult><Count>1</Count><RetMax>1</RetMax>"
        b"<RetStart>0</RetStart><IdList><Id>0</Id></IdList></eSearchResult>",
    ],
)
def test_semantically_incomplete_search_payloads_are_distinct(payload: bytes) -> None:
    with pytest.raises(IncompletePubMedXmlError) as error:
        parse_search_page(payload, expected_retstart=0, max_items=1)

    assert error.value.code is PubMedXmlErrorCode.SEMANTICALLY_INCOMPLETE_XML


def test_search_requires_expected_retstart_and_retmax_matches_ids() -> None:
    with pytest.raises(IncompletePubMedXmlError, match="RetStart"):
        parse_search_page(
            fixture("valid_search.xml"),
            expected_retstart=1,
            max_items=SEARCH_FIXTURE_MAX_ITEMS,
        )

    payload = fixture("valid_search.xml").replace(b"<RetMax>2</RetMax>", b"<RetMax>1</RetMax>")
    with pytest.raises(IncompletePubMedXmlError, match="RetMax"):
        parse_search_page(
            payload,
            expected_retstart=0,
            max_items=SEARCH_FIXTURE_MAX_ITEMS,
        )


def test_search_enormous_integer_is_typed_as_incomplete_xml() -> None:
    payload = (
        "<eSearchResult>"
        f"<Count>{'9' * 10_000}</Count>"
        "<RetMax>0</RetMax><RetStart>0</RetStart><IdList />"
        "</eSearchResult>"
    ).encode()

    with pytest.raises(IncompletePubMedXmlError) as error:
        parse_search_page(payload, expected_retstart=0, max_items=1)

    assert error.value.code is PubMedXmlErrorCode.SEMANTICALLY_INCOMPLETE_XML


@pytest.mark.parametrize(
    "payload",
    [
        (
            b'<?xml version="1.0" encoding="x-unknown"?>'
            b"<eSearchResult><Count>0</Count><RetMax>0</RetMax>"
            b"<RetStart>0</RetStart><IdList /></eSearchResult>"
        ),
        (
            '<?xml version="1.0" encoding="UTF-16"?>'
            "<eSearchResult><Count>0</Count><RetMax>0</RetMax>"
            "<RetStart>0</RetStart><IdList /></eSearchResult>"
        ).encode("utf-16"),
        (
            '<?xml version="1.0" encoding="UTF-16LE"?>'
            "<eSearchResult><Count>0</Count><RetMax>0</RetMax>"
            "<RetStart>0</RetStart><IdList /></eSearchResult>"
        ).encode("utf-16-le"),
        (
            '<?xml version="1.0" encoding="UTF-16BE"?>'
            "<eSearchResult><Count>0</Count><RetMax>0</RetMax>"
            "<RetStart>0</RetStart><IdList /></eSearchResult>"
        ).encode("utf-16-be"),
    ],
)
def test_unknown_and_multibyte_xml_encodings_are_invalid(payload: bytes) -> None:
    with pytest.raises(InvalidPubMedXmlError) as error:
        parse_search_page(payload, expected_retstart=0, max_items=1)

    assert error.value.code is PubMedXmlErrorCode.INVALID_OR_UNSAFE_XML


def test_search_provider_item_budget_rejects_overflow() -> None:
    payload = (
        b"<eSearchResult><Count>2</Count><RetMax>2</RetMax><RetStart>0</RetStart>"
        b"<IdList><Id>111</Id><Id>222</Id></IdList></eSearchResult>"
    )

    with pytest.raises(IncompletePubMedXmlError, match="provider-item bound"):
        parse_search_page(payload, expected_retstart=0, max_items=1)


def test_parse_valid_fetch_preserves_exact_provider_fields() -> None:
    response = parse_fetch_response(
        fixture("valid_fetch.xml"),
        expected_pmids=("111",),
        max_items=1,
    )

    assert response.malformed_records == ()
    assert response.duplicate_pmids == ()
    assert response.unexpected_pmids == ()
    assert response.missing_expected_pmids == ()
    record = response.records[0]
    assert record.pmid == "111"
    assert record.title == "Safety of example drug in adults"
    assert tuple(section.text for section in record.abstract_sections) == (
        "First  exact section.",
        "Second section.",
    )
    assert record.abstract_sections[0].label == "BACKGROUND"
    assert record.abstract_sections[0].nlm_category == "BACKGROUND"
    assert tuple(author.display_name for author in record.authors) == (
        "Ada Smith",
        "Evidence Study Group",
    )
    assert record.journal == "Journal of Exact Evidence"
    assert record.languages == ("eng",)
    assert record.publication_types == ("Journal Article", "Randomized Controlled Trial")
    assert record.publication_date is not None
    assert record.publication_date.year == "2025"
    assert record.publication_date.month == "Aug"
    assert record.publication_date.day == "04"
    assert record.doi == "10.1000/example"
    assert record.pmcid == "PMC111"
    assert record.medline_status == "MEDLINE"
    assert record.relationships[0].reference_type == "RetractionIn"
    assert record.relationships[0].related_pmid == "999"
    assert record.relationships[0].reference_source == "Example Journal. 2026."
    assert record.relationships[0].note == "Publisher notice"
    with pytest.raises(FrozenInstanceError):
        record.title = "mutated"


def test_mixed_valid_and_malformed_fetch_preserves_valid_record() -> None:
    payload = (
        "<PubmedArticleSet>" + article("111") + article("222", title=" ") + "</PubmedArticleSet>"
    ).encode()

    response = parse_fetch_response(
        payload,
        expected_pmids=("111", "222"),
        max_items=2,
    )

    assert tuple(record.pmid for record in response.records) == ("111",)
    assert response.missing_expected_pmids == ("222",)
    assert response.malformed_records == (response.malformed_records[0],)
    malformed = response.malformed_records[0]
    assert malformed.article_index == 1
    assert malformed.pmid_hint == "222"
    assert malformed.code is MalformedRecordCode.MISSING_TITLE
    assert "ArticleTitle" in malformed.detail


def test_duplicate_and_unexpected_fetch_records_are_explicit_and_deterministic() -> None:
    payload = (
        "<PubmedArticleSet>"
        + article("111", title="First")
        + article("333", title="Unexpected")
        + article("111", title="Duplicate")
        + article("333", title="Unexpected duplicate")
        + "</PubmedArticleSet>"
    ).encode()

    response = parse_fetch_response(
        payload,
        expected_pmids=("111", "222"),
        max_items=FETCH_FIXTURE_MAX_ITEMS,
    )

    assert response.records == ()
    assert response.duplicate_pmids == ("111", "333")
    assert response.unexpected_pmids == ("333",)
    assert response.missing_expected_pmids == ("111", "222")


def test_duplicate_current_and_retracted_whole_records_fail_closed() -> None:
    retracted = (
        article("111", title="Retracted version")
        .replace(
            "</Article>",
            "<PublicationTypeList><PublicationType>Retracted Publication</PublicationType>"
            "</PublicationTypeList></Article>",
        )
        .replace(
            "</MedlineCitation>",
            '<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">'
            "<PMID>999</PMID></CommentsCorrections></CommentsCorrectionsList>"
            "</MedlineCitation>",
        )
    )
    payload = (
        "<PubmedArticleSet>"
        + article("111", title="Current version")
        + retracted
        + "</PubmedArticleSet>"
    ).encode()

    response = parse_fetch_response(
        payload,
        expected_pmids=("111",),
        max_items=2,
    )

    assert response.records == ()
    assert response.duplicate_pmids == ("111",)
    assert response.missing_expected_pmids == ("111",)
    assert response.malformed_records == ()


def test_fetch_root_and_expected_input_are_validated() -> None:
    with pytest.raises(IncompletePubMedXmlError, match="PubmedArticleSet"):
        parse_fetch_response(b"<eSearchResult />", expected_pmids=(), max_items=1)
    with pytest.raises(ValueError, match="unique"):
        parse_fetch_response(
            b"<PubmedArticleSet />",
            expected_pmids=("1", "1"),
            max_items=2,
        )
    with pytest.raises(ValueError, match="invalid PMID"):
        parse_fetch_response(b"<PubmedArticleSet />", expected_pmids=("0",), max_items=1)


def test_fetch_provider_item_budget_rejects_overflow() -> None:
    payload = (
        "<PubmedArticleSet>" + article("111") + article("222") + "</PubmedArticleSet>"
    ).encode()

    with pytest.raises(IncompletePubMedXmlError, match="provider-item bound"):
        parse_fetch_response(payload, expected_pmids=("111",), max_items=1)


@pytest.mark.parametrize(
    ("duplicate_xml", "expected_code"),
    [
        (
            "<Abstract><AbstractText>First</AbstractText></Abstract>"
            "<Abstract><AbstractText>Second</AbstractText></Abstract>",
            MalformedRecordCode.AMBIGUOUS_ABSTRACT,
        ),
        (
            "<PublicationTypeList><PublicationType>Journal Article</PublicationType>"
            "</PublicationTypeList>"
            "<PublicationTypeList><PublicationType>Retracted Publication</PublicationType>"
            "</PublicationTypeList>",
            MalformedRecordCode.AMBIGUOUS_PUBLICATION_TYPES,
        ),
    ],
)
def test_duplicate_article_singletons_are_record_local_malformed(
    duplicate_xml: str,
    expected_code: MalformedRecordCode,
) -> None:
    malformed_article = article("111").replace("</Article>", f"{duplicate_xml}</Article>")
    payload = f"<PubmedArticleSet>{malformed_article}</PubmedArticleSet>".encode()
    response = parse_fetch_response(
        payload,
        expected_pmids=("111",),
        max_items=1,
    )

    assert response.records == ()
    assert response.missing_expected_pmids == ("111",)
    assert len(response.malformed_records) == 1
    assert response.malformed_records[0].pmid_hint == "111"
    assert response.malformed_records[0].code is expected_code


@pytest.mark.parametrize(
    ("relationship_xml", "expected_code"),
    [
        (
            '<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">'
            "<PMID>999</PMID></CommentsCorrections></CommentsCorrectionsList>"
            '<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">'
            "<PMID>888</PMID></CommentsCorrections></CommentsCorrectionsList>",
            MalformedRecordCode.AMBIGUOUS_RELATIONSHIPS,
        ),
        (
            '<CommentsCorrectionsList><CommentsCorrections RefType="RetractionIn">'
            "<PMID>999</PMID><PMID>888</PMID>"
            "</CommentsCorrections></CommentsCorrectionsList>",
            MalformedRecordCode.INVALID_RELATIONSHIP,
        ),
    ],
)
def test_duplicate_relationship_shapes_are_record_local_malformed(
    relationship_xml: str,
    expected_code: MalformedRecordCode,
) -> None:
    malformed_article = article("111").replace(
        "</MedlineCitation>",
        f"{relationship_xml}</MedlineCitation>",
    )
    response = parse_fetch_response(
        f"<PubmedArticleSet>{malformed_article}</PubmedArticleSet>".encode(),
        expected_pmids=("111",),
        max_items=1,
    )

    assert response.records == ()
    assert response.missing_expected_pmids == ("111",)
    assert len(response.malformed_records) == 1
    assert response.malformed_records[0].pmid_hint == "111"
    assert response.malformed_records[0].code is expected_code


def test_oversized_invalid_pmid_hint_is_not_retained() -> None:
    oversized_pmid = "9" * 100_000
    payload = ("<PubmedArticleSet>" + article(oversized_pmid) + "</PubmedArticleSet>").encode()

    response = parse_fetch_response(payload, expected_pmids=("111",), max_items=1)

    assert response.records == ()
    assert response.missing_expected_pmids == ("111",)
    assert len(response.malformed_records) == 1
    assert response.malformed_records[0].code is MalformedRecordCode.INVALID_PMID
    assert response.malformed_records[0].pmid_hint is None
