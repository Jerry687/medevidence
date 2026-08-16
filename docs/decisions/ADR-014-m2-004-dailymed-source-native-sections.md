# ADR-014: M2 DailyMed source-native section occurrences

- Status: Accepted by Project Owner; implementation validation pending
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-08-15
- Approval reference: `M2-004-DAILYMED-SOURCE-NATIVE-SECTIONS`
- Revision: 1
- Independent review reference: Pending
- Independent review role: Validation only; not an approving authority

## Context

The stopped M2-003 Gold-10 acquisition proved that two earlier parser
assumptions do not describe the retained OZEMPIC SPL. Provider display titles
are source-authored headings, not generic LOINC names, and an SPL may repeat an
allowlisted LOINC code across a structural parent and its independently
authored child sections. The stopped run and its raw evidence remain immutable
with terminal reason `DAILYMED_SECTION_SEMANTICS_INCOMPATIBLE`. Its unexecuted
MOUNJARO authorization is closed and non-transferable.

## Decision

M2 adds `DailyMedSourceNativeSectionV1` and
`parse_source_native_spl_document` without changing the M1B
`LabelSection`/`parse_spl_document` contract.

An occurrence is admitted only when its one direct `code` child contains an
exact allowlisted LOINC code and exact HL7 LOINC code-system OID
`2.16.840.1.113883.6.1`. The code selects the frozen generic LOINC name in
`normalized_section_name`. The one direct provider `title` is retained
separately as `provider_title`; it is not compared with, rewritten to, or used
as a fuzzy alias for the generic name. Unknown codes and wrong code systems are
excluded.

Every admitted source occurrence is retained independently in source order.
It binds exact SETID, SPL version, code system, code, normalized name, provider
title, source ordinal, immediate parent source ordinal, replayable XML path,
direct-child extracted text, and UTF-8 text SHA-256. Its identity is derived
from the complete source-location/content record, not the LOINC code. Repeated
codes are never deduplicated, concatenated, or reduced to a canonical first
occurrence.

A source occurrence with no nonblank direct `text` child remains visible as a
structural container with empty text and the SHA-256 of empty bytes. It is
explicitly not retrieval-eligible. This preserves the source hierarchy without
inventing searchable content.

The additive parser reuses the existing bounded `defusedxml` root, identity,
expanded-name, schema-resolution, DTD/entity, XInclude/XSLT, depth, element,
attribute, decoded-character, text-node, and retained-section controls. It
performs no external resolution or network I/O. This ADR does not authorize a
production XML transformation, change the strict parser policy, modify public
API/persistence schemas, or admit raw source bytes to Git.

## Retained OZEMPIC inventory

Offline inspection of the immutable 627,087-byte retained artifact
`cc9ecba8cce6eec215db9a0db28ef3c1c63dce3ba746aaf3caa5c3e9cd956626`
found SETID `adec4fd2-6858-4c99-91d4-531f5f2a2d79`, SPL version `20`, 62
source sections, and 13 exact allowlisted-code occurrences. The three
`34084-4` occurrences are one text-bearing `6 ADVERSE REACTIONS` parent and
two independently located/text-bearing children. The eight `43685-7`
occurrences are one non-text structural `5 WARNINGS AND PRECAUTIONS` parent
and seven independently located/text-bearing children. These are source
structure, not duplicate records. The external inventory binds all ordinals,
paths, provider titles, and text hashes without copying body text into Git.

The raw provider artifact contains constructs prohibited by the production
parser. The inventory is an offline, non-authoritative semantic inspection; it
does not assert that raw bytes passed the production parser and does not weaken
any XML control.

## Alternatives considered

- Require provider headings to equal generic LOINC names.
- Retain only the first occurrence of each code.
- Concatenate all same-code occurrences.
- Infer section types from provider-title similarity.
- Change M1B stable/public/persistence contracts in place.

Each alternative loses source-native meaning, permits ambiguous inference, or
expands this bounded work item.

## Consequences

M2 can represent the observed source hierarchy exactly while leaving legacy
M1B behavior byte-compatible. A future Gold-10 work item must explicitly
choose which retrieval-eligible occurrences enter its corpus and must obtain a
new exact live authorization. This work item authorizes no source request and
does not complete Gold-10.

## Validation

Focused unit tests cover exact code-system admission, normalized/provider-title
separation, repeated occurrences, stable source path/ordinal/content identity,
structural-container disposition, no deduplication or concatenation, and the
unchanged XML fail-closed controls. Full offline validation, independent
evidence-semantics review, and terminal audit are required before closure.

## Supersedes / Superseded by

This ADR does not supersede ADR-011. It adds an M2 evaluation representation
beside the frozen M1B section contract.
