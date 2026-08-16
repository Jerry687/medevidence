"""Hardened, provider-specific parsers for bounded PubMed XML responses."""

from __future__ import annotations

import re
import xml.etree.ElementTree as stdlib_etree
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from itertools import islice
from typing import cast
from urllib.parse import urlsplit

from defusedxml import ElementTree as safe_etree  # type: ignore[import-untyped]
from defusedxml.common import DefusedXmlException  # type: ignore[import-untyped]

_MAX_PMID_CHARACTERS = 16
_MAX_RESPONSE_INTEGER_DIGITS = 20
_PMID_PATTERN = re.compile(rf"[1-9][0-9]{{0,{_MAX_PMID_CHARACTERS - 1}}}\Z")
_NONNEGATIVE_INTEGER_PATTERN = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_XML_ENCODING_PATTERN = re.compile(
    rb"""<\?xml[^>]{0,200}\bencoding\s*=\s*(['"])([^'"]+)\1""",
    re.IGNORECASE,
)
_SUPPORTED_XML_ENCODINGS = frozenset({b"ascii", b"us-ascii", b"utf-8", b"utf8"})
_MAX_DOCTYPE_BYTES = 1024
_ALLOWED_DTD_HOSTS = frozenset({"dtd.nlm.nih.gov", "eutils.ncbi.nlm.nih.gov"})
_DOCTYPE_PATTERN = re.compile(
    rb"""<!DOCTYPE[\x20\t\r\n]+(?P<root>[A-Za-z_:][A-Za-z0-9_.:-]*)
    [\x20\t\r\n]+(?:
        SYSTEM[\x20\t\r\n]+(?P<system_quote>['"])
        (?P<system_url>[^'"]+)(?P=system_quote)
        |
        PUBLIC[\x20\t\r\n]+(?P<public_quote>['"])
        (?P<public_id>[^'"]+)(?P=public_quote)
        [\x20\t\r\n]+(?P<public_url_quote>['"])
        (?P<public_url>[^'"]+)(?P=public_url_quote)
    )[\x20\t\r\n]*>\Z""",
    re.VERBOSE,
)
_CANONICAL_NLM_PUBLIC_ID_PATTERN = re.compile(
    r"-//NLM//DTD [A-Za-z0-9](?:[A-Za-z0-9 .,'()+_:-]*[A-Za-z0-9)])?//EN\Z"
)


class PubMedXmlErrorCode(StrEnum):
    """Stable failure classes for whole-response XML failures."""

    INVALID_OR_UNSAFE_XML = "invalid_or_unsafe_xml"
    SEMANTICALLY_INCOMPLETE_XML = "semantically_incomplete_xml"


class PubMedXmlError(ValueError):
    """Base class for XML that cannot be accepted as a PubMed response."""

    code: PubMedXmlErrorCode


class InvalidPubMedXmlError(PubMedXmlError):
    """The payload is syntactically malformed or uses unsafe XML features."""

    code = PubMedXmlErrorCode.INVALID_OR_UNSAFE_XML


class IncompletePubMedXmlError(PubMedXmlError):
    """The payload is XML but does not satisfy the required PubMed shape."""

    code = PubMedXmlErrorCode.SEMANTICALLY_INCOMPLETE_XML


class MalformedRecordCode(StrEnum):
    """Stable record-local reasons for excluding one PubMed provider record."""

    MISSING_PMID = "missing_pmid"
    INVALID_PMID = "invalid_pmid"
    MISSING_TITLE = "missing_title"
    MISSING_JOURNAL = "missing_journal"
    MISSING_BOOK = "missing_book"
    MISSING_BOOK_TITLE = "missing_book_title"
    MISSING_LANGUAGE = "missing_language"
    MISSING_MEDLINE_STATUS = "missing_medline_status"
    INVALID_AUTHOR = "invalid_author"
    INVALID_PUBLICATION_DATE = "invalid_publication_date"
    INVALID_RELATIONSHIP = "invalid_relationship"
    AMBIGUOUS_ARTICLE_IDENTIFIER = "ambiguous_article_identifier"
    AMBIGUOUS_ABSTRACT = "ambiguous_abstract"
    AMBIGUOUS_PUBLICATION_TYPES = "ambiguous_publication_types"
    AMBIGUOUS_RELATIONSHIPS = "ambiguous_relationships"


@dataclass(frozen=True, slots=True)
class PubMedSearchPage:
    """One validated ESearch page in provider terms."""

    count: int
    retmax: int
    retstart: int
    pmids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PubMedAbstractSection:
    """One abstract section in exact source order."""

    text: str
    label: str | None
    nlm_category: str | None


@dataclass(frozen=True, slots=True)
class PubMedAuthor:
    """Provider author metadata without source-neutral interpretation."""

    display_name: str
    last_name: str | None
    fore_name: str | None
    initials: str | None
    suffix: str | None
    collective_name: str | None


@dataclass(frozen=True, slots=True)
class PubMedPublicationDate:
    """Exact PubMed date components, including unstructured Medline dates."""

    year: str | None
    month: str | None
    day: str | None
    medline_date: str | None


@dataclass(frozen=True, slots=True)
class PubMedRelationship:
    """One CommentsCorrections relationship from a PubMed record."""

    reference_type: str
    related_pmid: str | None
    reference_source: str | None
    note: str | None


@dataclass(frozen=True, slots=True)
class PubMedArticle:
    """A validated provider DTO for one PubMed article."""

    pmid: str
    title: str
    abstract_sections: tuple[PubMedAbstractSection, ...]
    authors: tuple[PubMedAuthor, ...]
    journal: str
    languages: tuple[str, ...]
    publication_types: tuple[str, ...]
    publication_date: PubMedPublicationDate | None
    doi: str | None
    pmcid: str | None
    medline_status: str
    relationships: tuple[PubMedRelationship, ...]


@dataclass(frozen=True, slots=True)
class PubMedBookDocument:
    """Validated source-native PubMed book document, distinct from an article."""

    pmid: str
    title: str
    abstract_sections: tuple[PubMedAbstractSection, ...]
    authors: tuple[PubMedAuthor, ...]
    book_title: str
    book_accession: str | None
    publisher_name: str | None
    publisher_location: str | None
    medium: str | None
    languages: tuple[str, ...]
    publication_types: tuple[str, ...]
    publication_date: PubMedPublicationDate | None


@dataclass(frozen=True, slots=True)
class MalformedPubMedRecord:
    """A deterministic, payload-free description of one rejected provider record."""

    article_index: int
    pmid_hint: str | None
    code: MalformedRecordCode
    detail: str


@dataclass(frozen=True, slots=True)
class PubMedFetchResponse:
    """Validated fetch records plus explicit record-level coverage defects."""

    records: tuple[PubMedArticle, ...]
    book_documents: tuple[PubMedBookDocument, ...]
    article_occurrence_count: int
    book_document_occurrence_count: int
    malformed_records: tuple[MalformedPubMedRecord, ...]
    duplicate_pmids: tuple[str, ...]
    unexpected_pmids: tuple[str, ...]
    missing_expected_pmids: tuple[str, ...]


class _RecordError(ValueError):
    def __init__(self, code: MalformedRecordCode, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


def parse_search_page(
    payload: bytes,
    expected_retstart: int,
    *,
    max_items: int,
) -> PubMedSearchPage:
    """Parse and semantically validate one bounded ESearch response page."""

    _validate_item_budget(max_items)
    if (
        isinstance(expected_retstart, bool)
        or not isinstance(expected_retstart, int)
        or expected_retstart < 0
    ):
        raise ValueError("expected_retstart must be nonnegative")

    root = _parse_root(payload, expected_root="eSearchResult")
    if root.tag != "eSearchResult":
        raise IncompletePubMedXmlError("expected eSearchResult document root")

    count = _required_nonnegative_integer(root, "Count")
    retmax = _required_nonnegative_integer(root, "RetMax")
    retstart = _required_nonnegative_integer(root, "RetStart")
    id_list = _require_single_child(root, "IdList")
    if len(id_list) > max_items:
        raise IncompletePubMedXmlError("IdList exceeds the configured provider-item bound")
    pmids = tuple(_parse_pmid(_element_text(element), "IdList/Id") for element in id_list)

    if any(element.tag != "Id" for element in id_list):
        raise IncompletePubMedXmlError("IdList contains an unexpected child element")
    if retstart != expected_retstart:
        raise IncompletePubMedXmlError("RetStart does not match the requested result window")
    if retmax != len(pmids):
        raise IncompletePubMedXmlError("RetMax does not equal the returned PMID count")
    if retstart > count or retstart + retmax > count:
        raise IncompletePubMedXmlError("returned result window exceeds Count")
    if count == 0 and (retstart != 0 or retmax != 0):
        raise IncompletePubMedXmlError("an empty search must return the zero result window")
    if count > retstart and retmax == 0:
        raise IncompletePubMedXmlError("a nonempty remaining result window cannot be empty")

    return PubMedSearchPage(count=count, retmax=retmax, retstart=retstart, pmids=pmids)


def parse_fetch_response(
    payload: bytes,
    expected_pmids: Sequence[str],
    *,
    max_items: int,
) -> PubMedFetchResponse:
    """Parse EFetch articles independently and expose every coverage defect."""

    _validate_item_budget(max_items)
    if isinstance(expected_pmids, (str, bytes)) or not isinstance(expected_pmids, Sequence):
        raise TypeError("expected_pmids must be a bounded sequence")
    if len(expected_pmids) > max_items:
        raise ValueError("expected_pmids exceeds the provider-item bound")
    expected = tuple(islice(expected_pmids, max_items + 1))
    if len(expected) > max_items:
        raise ValueError("expected_pmids exceeds the provider-item bound")
    if len(set(expected)) != len(expected):
        raise ValueError("expected_pmids must be unique")
    for pmid in expected:
        _validate_expected_pmid(pmid)
    expected_set = set(expected)

    root = _parse_root(payload, expected_root="PubmedArticleSet")
    if root.tag != "PubmedArticleSet":
        raise IncompletePubMedXmlError("expected PubmedArticleSet document root")

    records: list[PubMedArticle] = []
    book_documents: list[PubMedBookDocument] = []
    malformed: list[MalformedPubMedRecord] = []
    duplicate_pmids: list[str] = []
    unexpected_pmids: list[str] = []
    seen_occurrences: set[str] = set()
    accepted_pmids: set[str] = set()
    conflicted_pmids: set[str] = set()

    provider_records: list[tuple[str, stdlib_etree.Element]] = []
    for child in root:
        if child.tag not in {"PubmedArticle", "PubmedBookArticle"}:
            raise IncompletePubMedXmlError(
                "PubmedArticleSet contains an unsupported top-level record kind"
            )
        if len(provider_records) >= max_items:
            raise IncompletePubMedXmlError(
                "PubmedArticleSet exceeds the configured provider-item bound"
            )
        provider_records.append((child.tag, child))
    for article_index, (record_kind, element) in enumerate(provider_records):
        pmid_hint = (
            _pmid_hint(element) if record_kind == "PubmedArticle" else _book_pmid_hint(element)
        )
        canonical_hint = pmid_hint if pmid_hint is not None and _is_valid_pmid(pmid_hint) else None
        if canonical_hint is not None:
            if canonical_hint in seen_occurrences and canonical_hint not in duplicate_pmids:
                duplicate_pmids.append(canonical_hint)
                conflicted_pmids.add(canonical_hint)
                accepted_pmids.discard(canonical_hint)
                records = [record for record in records if record.pmid != canonical_hint]
                book_documents = [
                    record for record in book_documents if record.pmid != canonical_hint
                ]
            seen_occurrences.add(canonical_hint)
            if canonical_hint not in expected_set and canonical_hint not in unexpected_pmids:
                unexpected_pmids.append(canonical_hint)

        try:
            record = (
                _parse_article(element)
                if record_kind == "PubmedArticle"
                else _parse_book_document(element)
            )
        except _RecordError as error:
            malformed.append(
                MalformedPubMedRecord(
                    article_index=article_index,
                    pmid_hint=pmid_hint,
                    code=error.code,
                    detail=error.detail,
                )
            )
            continue

        if (
            record.pmid not in expected_set
            or record.pmid in accepted_pmids
            or record.pmid in conflicted_pmids
        ):
            continue
        if isinstance(record, PubMedArticle):
            records.append(record)
        else:
            book_documents.append(record)
        accepted_pmids.add(record.pmid)

    missing = tuple(pmid for pmid in expected if pmid not in accepted_pmids)
    return PubMedFetchResponse(
        records=tuple(records),
        book_documents=tuple(book_documents),
        article_occurrence_count=sum(
            record_kind == "PubmedArticle" for record_kind, _ in provider_records
        ),
        book_document_occurrence_count=sum(
            record_kind == "PubmedBookArticle" for record_kind, _ in provider_records
        ),
        malformed_records=tuple(malformed),
        duplicate_pmids=tuple(duplicate_pmids),
        unexpected_pmids=tuple(unexpected_pmids),
        missing_expected_pmids=missing,
    )


def _parse_root(payload: bytes, *, expected_root: str) -> stdlib_etree.Element:
    if not isinstance(payload, bytes):
        raise TypeError("PubMed XML payload must be bytes")
    _reject_unsupported_xml_encoding(payload)
    declared_root = _validated_external_doctype_root(payload, expected_root=expected_root)
    root = _parse_defused_root(payload)
    if root is None:
        raise InvalidPubMedXmlError("PubMed XML is malformed or unsafe")
    if declared_root is not None and root.tag != declared_root:
        raise InvalidPubMedXmlError("PubMed XML document roots do not match")
    return root


def _parse_defused_root(payload: bytes) -> stdlib_etree.Element | None:
    try:
        return cast(
            stdlib_etree.Element,
            safe_etree.fromstring(
                payload,
                forbid_dtd=False,
                forbid_entities=True,
                forbid_external=True,
            ),
        )
    except (
        DefusedXmlException,
        LookupError,
        ValueError,
        stdlib_etree.ParseError,
    ):
        return None


def _validated_external_doctype_root(payload: bytes, *, expected_root: str) -> str | None:
    marker = b"<!DOCTYPE"
    marker_index = payload.find(marker)
    if marker_index < 0:
        return None
    if payload.find(marker, marker_index + len(marker)) >= 0:
        raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")
    if not _doctype_is_in_document_prolog(payload, marker_index):
        raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")

    declaration_end = payload.find(b">", marker_index, marker_index + _MAX_DOCTYPE_BYTES)
    if declaration_end < 0:
        raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")
    declaration = payload[marker_index : declaration_end + 1]
    if len(declaration) > _MAX_DOCTYPE_BYTES:
        raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")
    declaration_is_ascii = True
    try:
        declaration.decode("ascii")
    except UnicodeDecodeError:
        declaration_is_ascii = False
    if not declaration_is_ascii:
        raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")

    match = _DOCTYPE_PATTERN.fullmatch(declaration)
    if match is None:
        raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")
    declared_root = match.group("root").decode("ascii")
    if declared_root != expected_root:
        raise InvalidPubMedXmlError("PubMed XML document roots do not match")

    public_id_bytes = match.group("public_id")
    if public_id_bytes is not None:
        public_id = public_id_bytes.decode("ascii")
        if _CANONICAL_NLM_PUBLIC_ID_PATTERN.fullmatch(public_id) is None:
            raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")

    url_bytes = match.group("system_url") or match.group("public_url")
    if url_bytes is None:
        raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")
    _validate_external_dtd_url(url_bytes.decode("ascii"))
    return declared_root


def _doctype_is_in_document_prolog(payload: bytes, marker_index: int) -> bool:
    prefix = payload[:marker_index]
    if prefix.startswith(b"\xef\xbb\xbf"):
        prefix = prefix[3:]
    prefix = re.sub(rb"\A[\x20\t\r\n]+", b"", prefix)
    xml_declaration = re.match(rb"<\?xml\b[^?]{0,256}\?>", prefix)
    if xml_declaration is not None:
        prefix = prefix[xml_declaration.end() :]
    while True:
        prefix = re.sub(rb"\A[\x20\t\r\n]+", b"", prefix)
        comment = re.match(rb"<!--[\s\S]*?-->", prefix)
        if comment is not None:
            prefix = prefix[comment.end() :]
            continue
        processing_instruction = re.match(rb"<\?(?!xml\b)[\s\S]*?\?>", prefix)
        if processing_instruction is not None:
            prefix = prefix[processing_instruction.end() :]
            continue
        return not prefix


def _validate_external_dtd_url(value: str) -> None:
    if any(
        character.isspace() or ord(character) < 0x21 or ord(character) == 0x7F
        for character in value
    ):
        raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")
    parsed = None
    port = None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        pass
    if parsed is None:
        raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")
    if (
        parsed.scheme != "https"
        or parsed.hostname not in _ALLOWED_DTD_HOSTS
        or parsed.netloc != parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.fragment
    ):
        raise InvalidPubMedXmlError("PubMed XML contains an unsupported DOCTYPE")


def _reject_unsupported_xml_encoding(payload: bytes) -> None:
    if payload.startswith((b"\xff\xfe", b"\xfe\xff", b"\x00\x00\xfe\xff")):
        raise InvalidPubMedXmlError("PubMed XML encoding is not supported")
    if b"\x00" in payload[:256]:
        raise InvalidPubMedXmlError("PubMed XML encoding is not supported")
    declaration = _XML_ENCODING_PATTERN.search(payload[:256])
    if declaration is None:
        return
    encoding = declaration.group(2).strip().lower()
    if encoding not in _SUPPORTED_XML_ENCODINGS:
        raise InvalidPubMedXmlError("PubMed XML encoding is not supported")


def _parse_article(element: stdlib_etree.Element) -> PubMedArticle:
    citation = _record_child(element, "MedlineCitation", MalformedRecordCode.MISSING_PMID)
    article = _record_child(citation, "Article", MalformedRecordCode.MISSING_TITLE)
    pmid = _record_pmid(citation)
    title = _record_required_text(article, "ArticleTitle", MalformedRecordCode.MISSING_TITLE)
    journal_element = _record_child(article, "Journal", MalformedRecordCode.MISSING_JOURNAL)
    journal = _record_required_text(
        journal_element,
        "Title",
        MalformedRecordCode.MISSING_JOURNAL,
    )
    languages = _record_languages(article)
    status = citation.attrib.get("Status")
    if status is None or not status.strip():
        raise _RecordError(
            MalformedRecordCode.MISSING_MEDLINE_STATUS,
            "MedlineCitation Status is required",
        )

    doi, pmcid = _article_identifiers(element, article)
    return PubMedArticle(
        pmid=pmid,
        title=title,
        abstract_sections=_abstract_sections(article),
        authors=_authors(article),
        journal=journal,
        languages=languages,
        publication_types=_publication_types(article),
        publication_date=_publication_date(journal_element),
        doi=doi,
        pmcid=pmcid,
        medline_status=status,
        relationships=_relationships(citation),
    )


def _parse_book_document(element: stdlib_etree.Element) -> PubMedBookDocument:
    book_document = _record_child(
        element,
        "BookDocument",
        MalformedRecordCode.MISSING_BOOK,
    )
    book_data = _record_child(
        element,
        "PubmedBookData",
        MalformedRecordCode.INVALID_PMID,
    )
    primary_pmid = _record_direct_pmid(book_document, "BookDocument")
    secondary_pmid = _book_data_pmid(book_data)
    if primary_pmid != secondary_pmid:
        raise _RecordError(
            MalformedRecordCode.INVALID_PMID,
            "BookDocument and PubmedBookData PubMed identifiers do not match",
        )

    book = _record_child(book_document, "Book", MalformedRecordCode.MISSING_BOOK)
    book_title = _record_required_text(
        book,
        "BookTitle",
        MalformedRecordCode.MISSING_BOOK_TITLE,
    )
    publisher_name: str | None = None
    publisher_location: str | None = None
    publishers = [child for child in book if child.tag == "Publisher"]
    if len(publishers) > 1:
        raise _RecordError(
            MalformedRecordCode.MISSING_BOOK,
            "Book Publisher must occur at most once",
        )
    if publishers:
        publisher_name = _record_optional_child_text(
            publishers[0],
            "PublisherName",
            MalformedRecordCode.MISSING_BOOK,
        )
        publisher_location = _record_optional_child_text(
            publishers[0],
            "PublisherLocation",
            MalformedRecordCode.MISSING_BOOK,
        )

    return PubMedBookDocument(
        pmid=primary_pmid,
        title=_record_required_text(
            book_document,
            "ArticleTitle",
            MalformedRecordCode.MISSING_TITLE,
        ),
        abstract_sections=_abstract_sections(book_document),
        authors=_book_authors(book_document),
        book_title=book_title,
        book_accession=_book_accession(book_document),
        publisher_name=publisher_name,
        publisher_location=publisher_location,
        medium=_record_optional_child_text(
            book,
            "Medium",
            MalformedRecordCode.MISSING_BOOK,
        ),
        languages=_record_languages(book_document),
        publication_types=_book_publication_types(book_document),
        publication_date=_book_publication_date(book),
    )


def _record_pmid(citation: stdlib_etree.Element) -> str:
    children = [child for child in citation if child.tag == "PMID"]
    if not children:
        raise _RecordError(MalformedRecordCode.MISSING_PMID, "MedlineCitation PMID is required")
    if len(children) != 1:
        raise _RecordError(MalformedRecordCode.INVALID_PMID, "MedlineCitation PMID is ambiguous")
    value = _element_text(children[0]).strip()
    if not _is_valid_pmid(value):
        raise _RecordError(MalformedRecordCode.INVALID_PMID, "MedlineCitation PMID is invalid")
    return value


def _record_direct_pmid(parent: stdlib_etree.Element, location: str) -> str:
    children = [child for child in parent if child.tag == "PMID"]
    if len(children) != 1:
        raise _RecordError(
            MalformedRecordCode.INVALID_PMID,
            f"{location} PMID must occur exactly once",
        )
    value = _element_text(children[0]).strip()
    if not _is_valid_pmid(value):
        raise _RecordError(
            MalformedRecordCode.INVALID_PMID,
            f"{location} PMID is invalid",
        )
    return value


def _book_data_pmid(book_data: stdlib_etree.Element) -> str:
    identifier_list = _record_child(
        book_data,
        "ArticleIdList",
        MalformedRecordCode.INVALID_PMID,
    )
    values = [
        _optional_element_text(element)
        for element in identifier_list
        if element.tag == "ArticleId" and element.attrib.get("IdType") == "pubmed"
    ]
    if len(values) != 1 or values[0] is None or not _is_valid_pmid(values[0].strip()):
        raise _RecordError(
            MalformedRecordCode.INVALID_PMID,
            "PubmedBookData requires exactly one valid ArticleId with IdType=pubmed",
        )
    return values[0].strip()


def _record_languages(article: stdlib_etree.Element) -> tuple[str, ...]:
    languages = tuple(
        value
        for element in article.findall("Language")
        if (value := _optional_element_text(element)) is not None
    )
    if not languages:
        raise _RecordError(
            MalformedRecordCode.MISSING_LANGUAGE,
            "at least one Article Language is required",
        )
    return languages


def _abstract_sections(article: stdlib_etree.Element) -> tuple[PubMedAbstractSection, ...]:
    abstracts = [child for child in article if child.tag == "Abstract"]
    if not abstracts:
        return ()
    if len(abstracts) != 1:
        raise _RecordError(
            MalformedRecordCode.AMBIGUOUS_ABSTRACT,
            "Article Abstract must occur at most once",
        )
    abstract = abstracts[0]
    return tuple(
        PubMedAbstractSection(
            text=text,
            label=element.attrib.get("Label"),
            nlm_category=element.attrib.get("NlmCategory"),
        )
        for element in abstract.findall("AbstractText")
        if (text := _optional_element_text(element)) is not None
    )


def _authors(article: stdlib_etree.Element) -> tuple[PubMedAuthor, ...]:
    author_list = article.find("AuthorList")
    if author_list is None:
        return ()

    authors: list[PubMedAuthor] = []
    for element in author_list.findall("Author"):
        last_name = _optional_child_text(element, "LastName")
        fore_name = _optional_child_text(element, "ForeName")
        initials = _optional_child_text(element, "Initials")
        suffix = _optional_child_text(element, "Suffix")
        collective_name = _optional_child_text(element, "CollectiveName")
        if collective_name is not None:
            display_name = collective_name
        elif last_name is not None:
            display_name = " ".join(
                part for part in (fore_name or initials, last_name, suffix) if part is not None
            )
        else:
            raise _RecordError(
                MalformedRecordCode.INVALID_AUTHOR,
                "Author requires CollectiveName or LastName",
            )
        authors.append(
            PubMedAuthor(
                display_name=display_name,
                last_name=last_name,
                fore_name=fore_name,
                initials=initials,
                suffix=suffix,
                collective_name=collective_name,
            )
        )
    return tuple(authors)


def _book_authors(book_document: stdlib_etree.Element) -> tuple[PubMedAuthor, ...]:
    author_lists = [child for child in book_document if child.tag == "AuthorList"]
    if len(author_lists) > 1:
        raise _RecordError(
            MalformedRecordCode.INVALID_AUTHOR,
            "BookDocument AuthorList must occur at most once",
        )
    return _authors(book_document)


def _book_publication_types(book_document: stdlib_etree.Element) -> tuple[str, ...]:
    return tuple(
        value
        for element in book_document
        if element.tag == "PublicationType"
        and (value := _optional_element_text(element)) is not None
    )


def _publication_types(article: stdlib_etree.Element) -> tuple[str, ...]:
    publication_type_lists = [child for child in article if child.tag == "PublicationTypeList"]
    if not publication_type_lists:
        return ()
    if len(publication_type_lists) != 1:
        raise _RecordError(
            MalformedRecordCode.AMBIGUOUS_PUBLICATION_TYPES,
            "Article PublicationTypeList must occur at most once",
        )
    publication_type_list = publication_type_lists[0]
    return tuple(
        value
        for element in publication_type_list.findall("PublicationType")
        if (value := _optional_element_text(element)) is not None
    )


def _publication_date(journal: stdlib_etree.Element) -> PubMedPublicationDate | None:
    pub_date = journal.find("./JournalIssue/PubDate")
    return _publication_date_element(pub_date)


def _book_publication_date(book: stdlib_etree.Element) -> PubMedPublicationDate | None:
    dates = [child for child in book if child.tag == "PubDate"]
    if len(dates) > 1:
        raise _RecordError(
            MalformedRecordCode.INVALID_PUBLICATION_DATE,
            "Book PubDate must occur at most once",
        )
    return _publication_date_element(dates[0] if dates else None)


def _publication_date_element(
    pub_date: stdlib_etree.Element | None,
) -> PubMedPublicationDate | None:
    if pub_date is None:
        return None
    year = _optional_child_text(pub_date, "Year")
    month = _optional_child_text(pub_date, "Month")
    day = _optional_child_text(pub_date, "Day")
    medline_date = _optional_child_text(pub_date, "MedlineDate")
    if year is None and medline_date is None:
        raise _RecordError(
            MalformedRecordCode.INVALID_PUBLICATION_DATE,
            "PubDate requires Year or MedlineDate",
        )
    if year is not None and (not year.isascii() or not year.isdigit() or len(year) != 4):
        raise _RecordError(
            MalformedRecordCode.INVALID_PUBLICATION_DATE,
            "PubDate Year must contain four ASCII digits",
        )
    return PubMedPublicationDate(
        year=year,
        month=month,
        day=day,
        medline_date=medline_date,
    )


def _book_accession(book_document: stdlib_etree.Element) -> str | None:
    lists = [child for child in book_document if child.tag == "ArticleIdList"]
    if len(lists) > 1:
        raise _RecordError(
            MalformedRecordCode.AMBIGUOUS_ARTICLE_IDENTIFIER,
            "BookDocument ArticleIdList must occur at most once",
        )
    if not lists:
        return None
    values = [
        value
        for element in lists[0]
        if element.tag == "ArticleId"
        and element.attrib.get("IdType") == "bookaccession"
        and (value := _optional_element_text(element)) is not None
    ]
    return _single_optional_identifier("book accession", values)


def _article_identifiers(
    article_element: stdlib_etree.Element,
    article: stdlib_etree.Element,
) -> tuple[str | None, str | None]:
    identifiers: dict[str, list[str]] = {}
    for element in article_element.findall("./PubmedData/ArticleIdList/ArticleId"):
        identifier_type = element.attrib.get("IdType", "").lower()
        value = _optional_element_text(element)
        if identifier_type and value is not None:
            identifiers.setdefault(identifier_type, []).append(value)

    doi_values = identifiers.get("doi", [])
    if not doi_values:
        doi_values = [
            value
            for element in article.findall("ELocationID")
            if element.attrib.get("EIdType", "").lower() == "doi"
            and (value := _optional_element_text(element)) is not None
        ]
    pmcid_values = identifiers.get("pmc", []) + identifiers.get("pmcid", [])
    return (
        _single_optional_identifier("DOI", doi_values),
        _single_optional_identifier("PMCID", pmcid_values),
    )


def _single_optional_identifier(label: str, values: Sequence[str]) -> str | None:
    unique = tuple(dict.fromkeys(values))
    if len(unique) > 1:
        raise _RecordError(
            MalformedRecordCode.AMBIGUOUS_ARTICLE_IDENTIFIER,
            f"{label} contains conflicting values",
        )
    return unique[0] if unique else None


def _relationships(citation: stdlib_etree.Element) -> tuple[PubMedRelationship, ...]:
    relationship_lists = [child for child in citation if child.tag == "CommentsCorrectionsList"]
    if not relationship_lists:
        return ()
    if len(relationship_lists) != 1:
        raise _RecordError(
            MalformedRecordCode.AMBIGUOUS_RELATIONSHIPS,
            "MedlineCitation CommentsCorrectionsList must occur at most once",
        )
    relationship_list = relationship_lists[0]
    relationships: list[PubMedRelationship] = []
    for element in relationship_list.findall("CommentsCorrections"):
        reference_type = element.attrib.get("RefType")
        if reference_type is None or not reference_type.strip():
            raise _RecordError(
                MalformedRecordCode.INVALID_RELATIONSHIP,
                "CommentsCorrections RefType is required",
            )
        related_pmid = _record_optional_child_text(
            element,
            "PMID",
            MalformedRecordCode.INVALID_RELATIONSHIP,
        )
        if related_pmid is not None and not _is_valid_pmid(related_pmid):
            raise _RecordError(
                MalformedRecordCode.INVALID_RELATIONSHIP,
                "CommentsCorrections PMID is invalid",
            )
        relationships.append(
            PubMedRelationship(
                reference_type=reference_type,
                related_pmid=related_pmid,
                reference_source=_record_optional_child_text(
                    element,
                    "RefSource",
                    MalformedRecordCode.INVALID_RELATIONSHIP,
                ),
                note=_record_optional_child_text(
                    element,
                    "Note",
                    MalformedRecordCode.INVALID_RELATIONSHIP,
                ),
            )
        )
    return tuple(relationships)


def _pmid_hint(article: stdlib_etree.Element) -> str | None:
    element = article.find("./MedlineCitation/PMID")
    value = _optional_element_text(element) if element is not None else None
    if value is None or len(value) > _MAX_PMID_CHARACTERS:
        return None
    canonical = value.strip()
    return canonical if _is_valid_pmid(canonical) else None


def _book_pmid_hint(book_article: stdlib_etree.Element) -> str | None:
    element = book_article.find("./BookDocument/PMID")
    value = _optional_element_text(element) if element is not None else None
    if value is None or len(value) > _MAX_PMID_CHARACTERS:
        return None
    canonical = value.strip()
    return canonical if _is_valid_pmid(canonical) else None


def _required_nonnegative_integer(root: stdlib_etree.Element, tag: str) -> int:
    value = _element_text(_require_single_child(root, tag)).strip()
    if (
        len(value) > _MAX_RESPONSE_INTEGER_DIGITS
        or _NONNEGATIVE_INTEGER_PATTERN.fullmatch(value) is None
    ):
        raise IncompletePubMedXmlError(f"{tag} must be a nonnegative integer")
    return int(value)


def _require_single_child(
    parent: stdlib_etree.Element,
    tag: str,
) -> stdlib_etree.Element:
    children = [child for child in parent if child.tag == tag]
    if len(children) != 1:
        raise IncompletePubMedXmlError(f"{tag} must occur exactly once")
    return children[0]


def _record_child(
    parent: stdlib_etree.Element,
    tag: str,
    code: MalformedRecordCode,
) -> stdlib_etree.Element:
    children = [child for child in parent if child.tag == tag]
    if len(children) != 1:
        raise _RecordError(code, f"{tag} must occur exactly once")
    return children[0]


def _record_required_text(
    parent: stdlib_etree.Element,
    tag: str,
    code: MalformedRecordCode,
) -> str:
    element = _record_child(parent, tag, code)
    value = _optional_element_text(element)
    if value is None:
        raise _RecordError(code, f"{tag} must contain nonblank text")
    return value


def _optional_child_text(parent: stdlib_etree.Element, tag: str) -> str | None:
    element = parent.find(tag)
    return _optional_element_text(element) if element is not None else None


def _record_optional_child_text(
    parent: stdlib_etree.Element,
    tag: str,
    code: MalformedRecordCode,
) -> str | None:
    children = [child for child in parent if child.tag == tag]
    if len(children) > 1:
        raise _RecordError(code, f"{tag} must occur at most once")
    return _optional_element_text(children[0]) if children else None


def _optional_element_text(element: stdlib_etree.Element) -> str | None:
    value = _element_text(element)
    return value if value.strip() else None


def _element_text(element: stdlib_etree.Element) -> str:
    return "".join(element.itertext())


def _parse_pmid(value: str, location: str) -> str:
    canonical = value.strip()
    if not _is_valid_pmid(canonical):
        raise IncompletePubMedXmlError(f"{location} contains an invalid PMID")
    return canonical


def _validate_expected_pmid(pmid: str) -> None:
    if not _is_valid_pmid(pmid):
        raise ValueError("expected_pmids contains an invalid PMID")


def _is_valid_pmid(value: str) -> bool:
    return _PMID_PATTERN.fullmatch(value) is not None


def _validate_item_budget(max_items: int) -> None:
    if isinstance(max_items, bool) or not isinstance(max_items, int) or max_items < 1:
        raise ValueError("max_items must be a positive integer")


__all__ = [
    "IncompletePubMedXmlError",
    "InvalidPubMedXmlError",
    "MalformedPubMedRecord",
    "MalformedRecordCode",
    "PubMedAbstractSection",
    "PubMedArticle",
    "PubMedAuthor",
    "PubMedBookDocument",
    "PubMedFetchResponse",
    "PubMedPublicationDate",
    "PubMedRelationship",
    "PubMedSearchPage",
    "PubMedXmlError",
    "PubMedXmlErrorCode",
    "parse_fetch_response",
    "parse_search_page",
]
