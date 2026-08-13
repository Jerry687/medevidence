# Data Sources and Source Semantics

## FAERS/openFDA M1B V1 contract

The approved mode is the provider count endpoint at the non-authorizing design
boundary `https://api.fda.gov/drug/event.json`, grouped only by
`patient.reaction.reactionmeddrapt.exact`. No request is authorized or executed
by FAERS-001. Its sole unit is `provider_count_occurrence`; there is no raw
report aggregation, inferred case-version reconstruction, or extra deduplication.
Drug roles are unfiltered and not interpreted.

The exact PT tuple is `DIARRHOEA`, `NAUSEA`, `VOMITING`, mapped only to
`Diarrhoea`, `Nausea`, `Vomiting` using MedDRA Version 29.0, English,
reference-only authority. `CONSTIPATION` and `ABDOMINAL PAIN` are excluded at
this evidence gate. Neither exclusion nor a zero bucket means a GI event is absent.

## 1. Governing principle

MedEvidence uses four source classes with different collection mechanisms,
questions, biases, and permitted conclusions. They must not be flattened into
one undifferentiated evidence tier or combined by majority vote.

| Source | Classification | Primary V1 question |
|---|---|---|
| PubMed | Scientific literature evidence | What do published studies and reviews report? |
| DailyMed | Official labeling evidence | What does a specific official product-label version state? |
| FAERS/openFDA | Descriptive spontaneous-report data | What reporting patterns appear under a bounded query? |
| CADEC | Auxiliary NLP/retrieval corpus | Can the system extract and retrieve ADR language from an approved corpus? |

## 2. PubMed

### 2.1 Permitted use

PubMed supports discovery and source-aware synthesis of biomedical literature
metadata and available abstracts. V1 may report study findings only within the
information actually present in the retrieved record.

### 2.2 Required fields

- PMID, DOI, and PMCID when available;
- title, authors, journal, language, publication date, and publication types;
- available abstract text and explicit abstract-only/full-text scope;
- publication status;
- retraction, correction, expression-of-concern, or related-record links where
  available;
- search query, filters, page/limit, retrieval time, and source URL;
- source snapshot, connector version, schema version, and parse warnings.

### 2.3 Limitations

- An abstract may omit methods, denominators, subgroup results, and adverse-
  event details.
- Publication, indexing, and language bias affect retrieval.
- A term mention is not automatically a measured association.
- Systematic reviews and their included primary studies can cause duplicate
  conceptual weighting.
- Retracted or corrected material must not silently support a positive claim.

V1 does not automatically ingest paywalled or unlicensed full text.

## 3. DailyMed

### 3.1 Permitted use

DailyMed provides official labeling evidence. A conclusion must refer to a
specific product and label version, not merely an ingredient name or an
unqualified “latest label.”

### 3.2 Required fields

- SETID and SPL version;
- label status and version history where available;
- product title, labeler, application identifiers, NDC/RxCUI/UNII when
  available;
- ingredients, strength, dosage form, and route;
- section code, heading, exact text locator, and source URI;
- published/effective and retrieval dates;
- selection query and reason this product/version was chosen;
- source snapshot, connector version, schema version, and parse warnings.

### 3.3 Selection policy

The connector may find candidate labels, but product selection must be
deterministic and reviewable using ingredient, human prescription status,
route, formulation, label status, and reference-scenario configuration.
Ambiguous candidates produce a warning or review requirement; the system must
not silently select an arbitrary label.

### 3.4 Limitations

- Label language reflects regulatory and sponsor processes, not a uniform
  comparative study design.
- Products, formulations, routes, labelers, and versions differ.
- Absence from a retrieved section does not prove absence of a risk.
- A missing DailyMed result is not equivalent to an affirmative no-risk
  statement.

## 4. FAERS/openFDA

### 4.1 Classification and permitted use

FAERS/openFDA is descriptive spontaneous-report data. V1 may describe bounded
reporting counts and distributions only when the statistical unit, filters,
time window, result limit, case-version rule, and limitations are displayed.

V1 must not:

- estimate incidence, prevalence, or absolute/relative risk;
- infer causality;
- rank products by safety;
- claim that a higher report count means a more dangerous product;
- compute ROR, PRR, IC, or other signal-detection measures.

### 4.2 Required query/result fields

- replayable openFDA query and API endpoint version where available;
- drug names and normalized mappings;
- drug role, including suspect/concomitant/interacting where used;
- reaction term and terminology as returned;
- start/end date and date field used;
- grouping dimensions and statistical unit;
- report/case identifier and version semantics when records are retrieved;
- latest-version/follow-up handling and deduplication policy;
- result count, API total, page/limit, truncation, and coverage status;
- seriousness/outcome/reporter/country dimensions when used;
- retrieval time, cache/snapshot identity, connector/schema version;
- mandatory warnings about missing exposure denominators, underreporting,
  stimulated reporting, duplicates/follow-ups, confounding, launch timing,
  usage volume, and unverified causality.

### 4.3 V1 comparison rule

FAERS output may appear in a side-by-side descriptive table, but the heading,
column labels, and generated text must use “reports” or “reporting pattern.”
The output must not use “incidence,” “risk,” “safer,” “more dangerous,” or a
causal construction unless it is explicitly rejecting such an inference.

FAERS is not counted as confirming a labeling statement or published study
merely because the same reaction term appears.

## 5. CADEC

### 5.1 Classification and permitted use

CADEC is an auxiliary NLP/retrieval corpus. V1 uses an approved, versioned
subset for:

- ADR mention extraction;
- terminology and alias mapping experiments;
- retrieval behavior on patient-authored language;
- comparison of gold annotations and prior model predictions.

CADEC must not contribute to product risk ranking, incidence, causal,
regulatory, diagnostic, treatment, or clinical conclusions.

### 5.2 Required fields

- corpus release/version and license record;
- document and annotation identifiers;
- dataset split;
- original text and annotation span;
- original and mapped drug/event terms;
- gold versus predicted origin;
- annotator provenance or model name/version;
- preprocessing, snapshot, connector/loader, and schema versions.

### 5.3 Limitations

- The corpus is not a population denominator or representative surveillance
  sample.
- Patient-authored language, selection effects, and annotation conventions
  affect generalization.
- Gold labels and model predictions must remain permanently distinguishable.
- Only license-approved content may be committed or displayed.

## 6. Shared source contracts

Every source result includes:

- internal ID and schema version;
- source class and stable source identifier;
- source version/status;
- original URI or replayable query;
- retrieval, publication/effective, and source-update times when available;
- `execution_status`: `succeeded` or `failed`;
- `coverage_status`: `complete`, `partial`, or `unavailable`;
- `result_status`: `matches`, `no_match`, or `indeterminate`;
- original drug/reaction terms and mapped concepts;
- exact text span or structured-field locator;
- data-quality, mapping, parsing, duplicate, and source-semantic warnings;
- snapshot ID, content hash, connector version, and transformation lineage.

A `SourceOutcome` exists only after a source actually executes. Sources that
do not execute remain in the plan as `selected`, `skipped_not_applicable`, or
`skipped_by_policy`; skipped sources have no `SourceOutcome`.

The only valid terminal combinations are:

| Execution | Coverage | Result |
|---|---|---|
| `succeeded` | `complete` | `matches` |
| `succeeded` | `complete` | `no_match` |
| `succeeded` | `partial` | `matches` |
| `succeeded` | `partial` | `indeterminate` |
| `failed` | `partial` | `matches` |
| `failed` | `partial` | `indeterminate` |
| `failed` | `unavailable` | `indeterminate` |

All other combinations are invalid. In particular, `no_match` requires both
`execution_status=succeeded` and `coverage_status=complete`; it is invalid with
partial, unavailable, or failed execution. Successful execution is invalid
with unavailable coverage, failed execution is invalid with complete coverage,
and unavailable coverage is invalid with matches.

Truncation, an enforced limit reached before source exhaustion, incomplete
pagination, or partial parsing requires `coverage_status=partial`. A failed or
partial zero-result operation is `indeterminate`, never “no evidence.”
Partial matches remain visible as partial coverage.

Allowed/invalid combinations, attempt transitions, and run-level aggregation
are normative in `ARCHITECTURE.md` Section 7.5.

## 7. Terminology normalization

### 7.1 Drug mappings

Mappings distinguish:

- ingredient, brand, and product;
- single ingredient and combination product;
- formulation, strength, and route;
- original string and canonical concept;
- exact, curated synonym, identifier, fuzzy, and unresolved match.

V1 uses an approved, versioned alias table for its configured reference domain.
The domain contract is extensible, but adding RxNorm or another terminology
service requires a separate source, license, and mapping-policy decision.

### 7.2 Adverse-reaction mappings

The system preserves the original event term and any source-provided coding
system/version. It must not commit a proprietary terminology distribution
without verified permission. Fuzzy or model-derived mappings retain confidence
and never silently become exact identities.

## 8. Snapshot and manifest policy

### 8.1 Git boundary

Git may contain:

- small sanitized connector fixtures;
- fixture and dataset manifests;
- manually adjudicated evaluation data;
- synthetic failure responses;
- schema examples without secrets or restricted content.

Git must not contain:

- complete raw source downloads;
- complete normalized corpora or Qdrant data;
- caches, database volumes, model weights, or generated reports containing
  restricted data;
- secrets, credentials, PHI, or unapproved CADEC content.

### 8.2 Required manifest fields

Every acquisition or corpus-ingestion run creates a versioned manifest with:

- `manifest_schema_version`;
- `snapshot_id`;
- `source_type`;
- replayable query or corpus input identity;
- retrieval/start/completion timestamps in UTC;
- record count and coverage status;
- execution and result status;
- raw file names/locations, byte sizes, and SHA-256 values;
- connector or corpus-loader name and version;
- source-record schema version;
- pagination/result bounds and truncation status;
- upstream version/update information when available;
- parent snapshot or transformation IDs;
- warnings and error summary;
- code revision when available.

The manifest itself is small and may be committed when it contains no secrets
or restricted material. PostgreSQL stores the authoritative metadata and file
location. Raw and normalized files remain outside Git.

### 8.3 Integrity

On replay, SHA-256 values must be verified before normalization. A hash
mismatch, missing file, unexpected record count, incompatible schema, or
incomplete snapshot blocks index publication and produces an auditable failure.

## 9. Deduplication and lineage

Deduplication marks canonical/current records but never erases the source
history required for replay. Every normalized item and chunk references:

- its raw source record and snapshot;
- normalization and mapping versions;
- duplicate/supersession relationship;
- chunker and index versions;
- the code/configuration revision that produced it.

Semantic similarity may identify duplicate candidates but cannot be the only
rule for removing or superseding records.

## 10. Freshness and report reproducibility

Every report records:

- exact research scope and source query;
- source coverage and retrieval-as-of time;
- snapshot and manifest identities;
- source version/effective dates;
- cache status and cached-at time;
- normalization, chunk, embedding/sparse, index, and reranker versions;
- model/prompt versions where synthesis is used.

Later source updates create new snapshots and reports; they do not silently
rewrite an exported report.

## 11. M1B-DM-001 exact DailyMed source contract

The detailed Owner-frozen contract is
[ADR-011](decisions/ADR-011-m1b-dailymed-contracts.md). DailyMed evidence is
authoritative only for one exact selected product identity, canonical SETID,
positive canonical SPL version, and exact LOINC-coded label section.

Discovery, selection, and fetch are separate facts. Complete matching discovery
may select only after exact/equivalent-group resolution. Every positive-count
partial matching discovery is `review_required`; retained count, deterministic
equivalence, or pinned SETID/version never creates an exception. Complete
zero-result no-match alone is `no_candidate`; partial/failed/unavailable
zero-result discovery remains indeterminate and creates no decision row.

`DailyMedCandidateLabel` retains the exact discovery query/snapshot/manifest/
member lineage plus product, formulation, route, strength, labeler, SETID,
available versions, marketing state, dates, and section codes.
`LabelSelectionDecision` retains the complete ordered candidate set, not a
subset. Stable `DailyMedLabelVersion` and `LabelSection` identities are
fetch-independent and content-addressed; observations in a report preserve the
distinct discovery and fetch provenance.

SPL versions sort numerically, and candidate-set ordering is derived from
canonical SETID, numeric versions, candidate identity, and bytewise UTF-8
tie-break rather than caller tuple order. Meaningful differences are computed
from exact candidate fields; caller-supplied resolution cannot override them.
Marketing state includes `unknown`. The label-version ID preimage is exactly
schema/source/SETID/SPL-version/content-hash. `RetainedSplResponse` and
`LabelSelectionWarning` retain the closed fetch and warning associations.

The section registry is exactly the four Active LOINC 2.82 pairs:

- `34084-4` - FDA package insert Adverse reactions section;
- `43685-7` - FDA package insert Warnings and precautions section;
- `34066-1` - FDA package insert Boxed warning section;
- `34067-9` - FDA package insert Indications and usage section.

No fuzzy title matching, code expansion, or name-only/latest label selection is
permitted. Missing a requested section is visible and cannot fabricate label
absence or no-risk evidence.

The six-path DailyMed `connector_trust_allowlist` is frozen design metadata
only. It authorizes no request. M1B-DM-001 performs no source or corpus access;
ordinary/runtime host lists remain empty and exact source bytes remain outside
Git. Future DM-002 ZIP/XML handling must enforce the exact ADR-011 byte/count/
parser/path controls, including all ASCII C0 controls and DEL before member-name
normalization, without filesystem extraction.

## 12. M1B-DM-003 report-use boundary

The DailyMed report tool consumes only evidence that has already crossed the
DM-002 connector, snapshot, parser, and persistence trust boundaries. It does
not retrieve, reinterpret, or repair source data. Every section retains its
discovery reference and, when attempted, its distinct fetch reference. Stable
label text and locators remain available only for a successful complete usable
fetch; degraded discovery and failed fetch states retain limitations and cannot
be presented as authoritative label absence.

This work item performs no medical-source request. Its live test module is a
disabled governance harness, not live-source evidence.

## 13. M1B-FAERS-003 report-use boundary

The FAERS report operation consumes only aggregate results that have already
crossed the FAERS-002 connector, immutable snapshot/replay, and persistence
trust boundaries. It neither retrieves provider data nor interprets or repairs
provider payloads. Only the exact query identity, source outcome, snapshot,
canonical aggregate buckets, bucket locators, and mandatory limitations reach
the report.

The V1 set is exactly `DIARRHOEA`, `NAUSEA`, and `VOMITING` under the frozen
MedDRA 29.0 English reference-only boundary. The unit remains provider count
occurrence and provider roles remain unfiltered. This deliberately bounded set
is not comprehensive GI coverage, and bucket absence is not absence of GI
adverse events. No individual report, narrative, demographic, reporter,
geography, outcome, or other provider record is admitted.

This work item makes no FAERS/openFDA or other medical-source request. The live
module is a disabled authorization harness and supplies no source evidence.

## 14. M1B-CADEC-001 exact asset contract

The external raw archive SHA-256 is
`4045b926a0a5735f00f785f7ad935e5a73731d6ab607d11d88880a334be18c4a`.
The external manifest is 1,699,979 bytes with SHA-256
`1c475ded0e7a2e0d80fe0909f2ccf1131c746da6ffc9c52879bfd9076234abfa`;
the terminal freeze audit is 6,354 bytes with SHA-256
`18928091762df33fc1fc39e9d45a55c86637a0c55c1d5cc987bc12e55a36f753`.
These bind contracts without copying external artifacts or archive bytes.

Canonical/admitted counts are 1,250/1,248; exact sorted exclusions are
`DICLOFENAC-SODIUM.7` and `LIPITOR.221`. Five malformed rows reject and are
never repaired or reinterpreted. All text is UTF-8 except exactly
`cadec/sct/LIPITOR.253.ann`, decoded as CP1252 only at SHA-256
`0deeb944656f03381dd8adb2914570f4759e70cd43c8a7c81a5c56cfefb0da96`.

| `MEDEVIDENCE_CADEC_SPLIT_V1` split | Count | Membership SHA-256 |
|---|---:|---|
| train | 992 | `e533c904637a86b447ce4cee5973b4041ff8de1679fcb073e78a0525835c8329` |
| development | 119 | `dd219af2c42b717fb1df7d24b04de9bb031c099d4deb513091c6d49d4b2b799f` |
| test | 137 | `6bf824a4fe7a708a836cf08b007734622bb02c2fecf0d1441febfb0103a3e26a` |

Only provider gold is admitted; no predicted artifact is admitted. The 91
reference-binding limitations (2 original, 44 MedDRA, 45 SCT) remain visible
and non-malformed. Vocabulary is closed to `MedDRA` and `SNOMED CT`, each with
version `not stated in retained provider/archive metadata` and legal status
`reference-only`; identifiers, terms, hierarchy, and payload emission are all
false. The licence is `CSIRO Data Licence`, ID 1061: attribution required,
non-commercial internal research only, no intellectual-property assertion over
the data, no implied provider accuracy/endorsement, and no redistribution.
REDIST remains raw external/no redistribution/no corpus-derived real fixtures.

Option-A children use the namespaced archive SHA as corpus ID and namespaced
manifest SHA as corpus version, plus the exact manifest, terminal audit, split
membership, and artifact lineage. Document labels must be canonical safe
`cadec/text/<document_id>.txt` paths and cannot be either exact exclusion.
