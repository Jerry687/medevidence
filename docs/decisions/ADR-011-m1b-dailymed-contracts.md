# ADR-011: M1B DailyMed domain and public contracts

- Status: Accepted decision; Review 016 and Audit 001 PASS; final-byte rebind pending
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-08-11
- Approval reference: `M1B-OWNER-PLANNING-FREEZE-v7-owner-resolution-final-r1`
- Approval artifact SHA-256:
  `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Work item: `M1B-DM-001`
- Revision: 1
- Independent review reference:
  [M1B-DM-001-INDEPENDENT-REVIEW-008](../reviews/M1B-DM-001-INDEPENDENT-REVIEW-008.md)
- Independent review role: Validation only; not an approving authority

## Context

M1A is complete at the Owner-approved baseline
`ebcd11eb91aa02ae9a7115188ea10604e9f335d1`. M1B-DM-001 is the first
authorized M1B implementation node. It freezes DailyMed identity, deterministic
selection, stable label-version and section, public request/report/locator, and
future connector/parser security contracts. It does not implement a connector,
parser, snapshot store, persistence adapter, tool, API route, or live request.

DailyMed is official product-label evidence. Its content cannot be generalized
across product, formulation, route, strength, labeler, SETID, SPL version, or
section without an exact contract and visible ambiguity handling.

## Decision

### 1. Additive compatibility boundary

M1B uses explicit parallel versions:

- `M1BResearchRequestV1` has discriminator `m1b.request.v1`;
- `M1BResearchReportV1` has discriminator `m1b.report.v1` and remains a
  research-only, non-exportable draft;
- M1B planning uses the distinct additive `M1BSourcePlanEntryV1` contract with
  `schema_version="m1b.source-plan.v1"`;
- the existing `ResearchScope`, M1A `ResearchReport`, default
  `SourcePlanEntry(schema_version="1.0")`, its JSON Schema/OpenAPI component,
  and their serialized behavior remain unchanged.

The caller supplies requested source identities and typed DailyMed selection
requests, never durable planning status or skip reasons. The report retains
source-indexed acquisition outcome references. A skipped source has no outcome
or section.

### 2. Canonical label identity

SETID is exactly 36 lowercase ASCII characters in canonical UUID form
`8-4-4-4-12`. The exact input must parse as a UUID and equal the normalized
UUID string; the nil UUID is forbidden. UUID version and variant are not
restricted. Uppercase, braces, URN form, whitespace, percent encoding,
noncanonical hyphenation, and prefixes or suffixes reject.

SPL version is a positive canonical ASCII integer string matching
`^[1-9][0-9]*$`. Exact SETID/version parity is required across request,
discovery/history, selected decision, fetch metadata, and the parsed SPL
selectors. A pin remains request state until discovery executes and does not
override any discovery outcome.

### 3. Exhaustive DailyMed discovery decision matrix

The authoritative inherited `SourceOutcome` triple, candidate count, and
deterministic resolution form one exhaustive, disjoint matrix:

| Outcome | Count | Resolution | Decision |
|---|---:|---|---|
| `succeeded/complete/matches` | `>=1` | `resolved_equivalent` | `selected` |
| `succeeded/complete/matches` | `>=2` | `unresolved_non_equivalent` | `review_required` |
| `succeeded/partial/matches` | `>=1` | either | `review_required` |
| `failed/partial/matches` | `>=1` | either | `review_required` |
| `succeeded/complete/no_match` | `0` | none | `no_candidate` |
| `succeeded/partial/indeterminate` | `0` | none | no decision row |
| `failed/partial/indeterminate` | `0` | none | no decision row |
| `failed/unavailable/indeterminate` | `0` | none | no decision row |

Every other combination rejects. In particular, partial discovery always
requires review for positive retained candidates, including count one,
resolved-equivalent candidates, and an exact pinned SETID/version. Partial
discovery can never produce `selected` because it cannot exclude an unseen,
non-equivalent eligible label.

`LabelSelectionDecision` is the sole persisted candidate-set envelope. It
binds one exact executed discovery, its complete ordered candidate IDs/member
bindings, source outcome reference, manifest identity, selection status, and
selected member scalars only for `selected`. The sole observational timestamp
is `decided_at_utc`; no `decided_at` alias exists. A no-candidate decision has
empty candidate arrays and the exact warning `no_candidate`. Indeterminate
zero-result discovery has no decision row.

### 4. Candidate, stable version, and section contracts

`DailyMedCandidateLabel` retains clinically meaningful identity and exact
discovery provenance. Candidate SPL versions sort numerically and the candidate
set uses the frozen normalized SETID, numeric SPL version, candidate identity,
and bytewise UTF-8 tie-break order independently of caller tuple order. Conflicts
in NDC, product name, ingredient set, dosage form, route, strength, or labeler
are computed from the candidates rather than trusted from the caller. Ranking
occurs only inside one meaningfully equivalent group: active before archived,
later effective/published date before earlier, and higher SPL version before
lower.

`DailyMedLabelVersion` is fetch-independent. Marketing state is the closed
`active/archived/unknown` set. Its stable identity preimage is exactly source,
SETID, SPL version, content hash, and schema version; marketing state, dates,
and SPL artifact identity remain full-row verified fields but do not change the
stable ID. `LabelSection` is a stable exact half-open span within that version
and carries code/title, ordinal, XML path, offsets, text hash, and SPL artifact
identity. Neither stable model stores a discovery or fetch tuple.

`RetainedSplResponse` closes the selected/fetch/stable-label/section bindings
for the complete retained response. `LabelSelectionWarning` closes the warning
code, exact candidate identities, and exact differing dimensions and validates
against its decision without creating a circular identity dependency.

The exact section-code registry is LOINC release 2.82, code system
`http://loinc.org`, steward Regenstrief Institute, Inc.:

| Code | Exact title | Status | Evidence |
|---|---|---|---|
| `34084-4` | FDA package insert Adverse reactions section | Active | `https://loinc.org/34084-4` |
| `43685-7` | FDA package insert Warnings and precautions section | Active | `https://loinc.org/43685-7` |
| `34066-1` | FDA package insert Boxed warning section | Active | `https://loinc.org/34066-1` |
| `34067-9` | FDA package insert Indications and usage section | Active | `https://loinc.org/34067-9` |

Codes and titles are exact pairs. No fuzzy alias, expansion, fifth code, or
silent retitling is permitted. The typed LOINC oracle also freezes authority
`LOINC`, steward `Regenstrief Institute, Inc.`, release `2.82`, exact ordered
mapping mode, and expansion disabled.

### 5. Source section and locator truthfulness

`DailyMedLabelSectionV1` binds one typed request to one discovery reference and
zero or one later fetch reference. `no_candidate`, `review_required`, and the
three decisionless indeterminate zero-result shapes remain truthful
discovery-only sections with a null stable result, visible limitation, and no
label locator. A selected decision may retain a failed fetch, but its stable
result remains null and the failure limitation stays visible.

`DailyMedLocatorV1` exists only after `selected` plus a distinct
`succeeded/complete/matches` fetch with complete retained bytes and usable
normalization. Its common acquisition/snapshot/query fields are exact aliases
of the fetch fields. It repeats the discovery selection identity, fetch
observation, stable version, and stable section span. It cannot be emitted for
a degraded discovery or failed fetch. Locator validation can bind every
discovery attempt/intent/ordinal/query/snapshot/manifest/outcome field to the
selection decision and every fetch field to `RetainedSplResponse`. Requested
LOINC sections absent after a usable fetch remain explicit
`section_absent:<code>` limitations and receive no invented locator.

### 6. Non-authorizing connector and parser security metadata

`connector_trust_allowlist` is design metadata, not permission to perform
network I/O. It freezes only HTTPS `dailymed.nlm.nih.gov:443`, method `GET`, at
most one redirect to the identical origin, and these six typed path/query
templates:

1. `/dailymed/services/v2/spls.json` with its closed discovery query keys;
2. `/dailymed/services/v2/spls/{SETID}/history.json` with `pagesize,page`;
3. `/dailymed/services/v2/spls/{SETID}/ndcs.json` with `pagesize,page`;
4. `/dailymed/services/v2/spls/{SETID}/packaging.json` with `pagesize,page`;
5. `/dailymed/services/v2/spls/{SETID}.xml` with no query;
6. `/dailymed/getFile.cfm` with exactly
   `type=zip,setid={SETID},version={SPL_VERSION}`.

For M1B-DM-001, `ordinary_validation_hosts=[]`, runtime permitted hosts are
empty, and `medical_source_network_execution_authorized=false`.

The same typed, non-executing oracle freezes the 13 denied request classes;
5/10/5/5-second connect/read/write/pool timeouts with a 30-second total;
two attempts; 250 ms exponential backoff capped at 4 seconds with 100 ms
jitter; Retry-After capped at 10 seconds; retryable/permanent classes;
discovery limits of five pages, 100 candidates, and 5,242,880 cumulative bytes;
a 5,242,880-byte payload limit; immutable fixed-version caching; and no
discovery or stale cache. These values remain metadata and execute no I/O.

The future parser profile is typed contract metadata only. It freezes
`defusedxml` fail-closed parsing, root `{urn:hl7-org:v3}document`, byte/depth/
element/attribute/text/section bounds `5242880/64/50000/64/5000000/262144/128`,
and zero external resolution or I/O. Identity uses only one direct HL7 `setId`
unqualified `root` and one direct HL7 `versionNumber` unqualified `value`.
Additional safe selector attributes are permitted but semantically inert;
namespaced/local-name lookalikes do not count.

Historical ZIP handling never extracts to the filesystem. Compressed HTTP,
total uncompressed, and per-member bytes are each bounded to 5,242,880, with
at most 128 entries. The full central directory is validated before evidence
acceptance. Encryption, symlinks/special files, unsafe paths, duplicate
normalized names, and every ASCII C0 code point U+0000 through U+001F plus DEL
U+007F reject before normalization. Exactly one bounded XML member with the
HL7 document root and selected identity is required; malformed/unclassifiable
XML and multiple candidates reject. Safe non-XML attachments remain
nonauthoritative.

## Alternatives considered

- Select from a partial candidate set when its retained candidates appear
  equivalent or match a pin.
- Mutate M1A contracts in place.
- Treat the frozen DailyMed hostname as current network authorization.
- Select the latest label by display-name similarity.
- Extract historical ZIP files to a temporary directory.

All are rejected because they weaken evidence authority, compatibility, or the
security boundary.

## Consequences

- DailyMed selection is reproducible and cannot hide incomplete discovery.
- Stable label/section identity remains reusable across exact fetch
  observations.
- M1A serialized behavior remains intact.
- DM-002 can implement only these frozen contracts after separate Owner
  authorization; DM-001 performs no transport, parsing, persistence, or API
  work.

## Validation

M1B-DM-001 must pass the four frozen domain test files with sockets disabled,
the complete ordinary offline quality suite, independent review of the actual
diff and behavior, bounded remediation, and terminal audit. Mandatory cases
include the exhaustive matrix, pinned-partial negatives, canonical SETID/SPL
identity, exact LOINC registry, non-authorizing trust metadata, 33 ASCII ZIP
control rejections, degraded-section truthfulness, stable version reuse, and
closed locator drift.

The first complete independent implementation review returned
`P0/P1/P2 = 0/4/1`. Final bounded remediation 3/3 addressed that finding set by
closing missing identity rows and parity, deriving rather than trusting
candidate equivalence, strengthening report/locator bindings, expanding the
typed machine oracles, and synchronizing documentation. The fresh independent
review of remediation 3/3 returned `FAIL — P0 0 / P1 2 / P2 0`: closed policy
models still accept weakened caller tuples, and the report accepts conflated
discovery/fetch acquisition and snapshot tuples with ordinals `(0, 0)`. The
retry budget is exhausted and status is `OWNER_DECISION_REQUIRED`. Terminal
audit and all Git/integration lifecycle steps were not run.

The Owner subsequently authorized one extra remediation cycle, limited exactly
to those two P1 findings. Extra remediation 1/1 implemented non-weakenable
canonical policy construction/deserialization and strict discovery/fetch
ordinal, acquisition, and snapshot separation. Fresh evidence is: P1-focused
`108 passed`; DailyMed plus byte-exact OpenAPI `273 passed`; Ruff check PASS;
Ruff format `67 files already formatted`; MyPy `34` source files; full offline
`887 passed`, two existing warnings, `79%` coverage; diff and scope checks PASS.
Historical Review 001 remains immutable. Fresh independent Review 002 and the
terminal audit are pending, so no PASS, commit, push, PR, CI, merge,
integration, or `M1B-DM-002` claim is made.

Review 002 binds candidate manifest
`f8c9cb5b13a93d4c15847855785afac80d16e0332462a9b0734e9cb576769ffe`
and returned `FAIL — P0 0 / P1 1 / P2 1`. It verified both Review 001 closures,
then reproduced acceptance of a DailyMed section request whose drug concept is
foreign to the report scope and identified missing executable evidence for
acquisition totals one through eight plus ninth rejection. This is recorded as
same-class P1-02 mechanical remediation and its dependent P2 evidence within
the Owner-authorized extra cycle 1/1. The implementation now rejects foreign
scope drugs, provides an exact comparator to the existing
`M1BResearchRequestV1` envelope without schema expansion, and tests real report
acquisition totals one through eight plus ninth rejection. Fresh evidence is:
P1-focused `120 passed`; DailyMed plus byte-exact OpenAPI `285 passed`; Ruff
check PASS; Ruff format `67 files already formatted`; MyPy `--no-incremental`
PASS for `34` source files; full offline `899 passed`, two existing warnings,
`80%` coverage; exact 20-path scope and diff checks PASS. This was the candidate
submitted to Review 003; no PASS or integration claim was made.

Review 003 binds exact 20-path manifest
`06b77e138ed4f87b2ddc749ef8eb67fd214b61512714f56b95e881afbbeeb6b3`
and returned `FAIL — P0 0 / P1 2 / P2 0`. It verified all prior closures, then
showed that arbitrary acquisition, intent, snapshot, and source-outcome
identities can be accepted because the report joins refs and outcomes only by
source/query. It also showed retained-response/locator drift in discovery
snapshot and selected candidate. The exact existing-model acceptance criteria
are preserved in Review 003. The Owner-authorized extra cycle 1/1 is consumed;
status is `OWNER_DECISION_REQUIRED` for another bounded mechanical remediation
cycle. Terminal audit and every Git/integration/DM-002 step are prohibited from
this candidate.

The Owner subsequently authorized exactly one new remediation cycle limited to
Review 003 P1-01/P1-02. The implementation uses non-serialized exact trusted
`AcquisitionOutcomeRef`/`SourceOutcome` pairs and a trusted selection-decision
comparator using existing models, and closes retained discovery-snapshot plus
locator selected-candidate chains. It adds no schema, public field, concept, or
frozen semantic. Fresh authoritative evidence is: P1-focused `143 passed`;
DailyMed plus byte-exact OpenAPI `308 passed`; Ruff PASS; format `67` files;
MyPy `--no-incremental` PASS for `34` source files; full offline `922 passed`,
two existing warnings, `80%` coverage; exact 21-path scope and diff checks PASS.
This was the candidate submitted to Review 004. No PASS, Git, network,
integration, or `M1B-DM-002` claim was made.

Review 004 binds canonical ordinal 21-path manifest
`e4f3ec8e43e2292ffe1c9c6206892f61d7111eb5c27392a21022122b14b5819e`
(CurrentCulture alias
`88574fcb86094047cb17c366bc8d6e280e2b476a7e0210b8bd57ac2fc8d98aaf`)
and returned `FAIL — P0 0 / P1 1 / P2 0`. It verified all prior closures, then
accepted decision/candidate scalar drift, an exact-pin mismatch, and a two-drug
cross-request evidence swap. These are one same-class missing request-owned
candidate/decision/evidence binding. Mechanical acceptance uses existing model
tuples and requires no new schema, field, concept, or frozen semantic. Under
the Owner's explicit do-not-stop same-class clause, batch remediation is in
progress. Review 005 and terminal audit remain pending; no PASS or integration
claim is made.

Post-Review 004 remediation closes the same-class binding with existing models
only: an authoritative candidate's SETID and highest numeric SPL version must
equal the decision; request-owned ephemeral request/ref/outcome triples and
request/decision pairs must equal their exact canonical unions; pinned selected
identity must equal the exact pin; and cross-request evidence-bundle swaps
reject. No serialized field, schema, or public concept was added. Fresh root
evidence is: focused source-outcomes/reports/provenance `276 passed in 0.49s`;
DailyMed plus byte-exact OpenAPI `310 passed in 0.80s`; Ruff PASS; format `67`
files; MyPy `--no-incremental` PASS for `34` source files; full offline `924
passed`, two existing warnings, `80%` coverage in `7.29s`; diff and exact
22-path scope checks PASS. Review 005 and terminal audit remain pending; no
PASS, Git, network, integration, or `M1B-DM-002` claim is made.

Review 005 binds exact 22-path manifest
`420cfd5a5ec52a30d53dee54d5bac2cfff2a11c0b450e03031434d4ea1881bca`
and returned `FAIL — P0 0 / P1 2 / P2 0`. It verified Review 004 closure, then
accepted foreign decision discovery/candidate-set fields after recomputing the
decision ID across selected failed-fetch, review-required, and no-candidate
paths. It also accepted locator/decision label drift and
locator/retained-response stable identity drift. Closure requires complete
existing-field comparisons, candidate-set recomputation, trusted primitive
context, and direct/end-to-end drift tests; it adds no frozen semantic or new
concept. Same Owner-authorized same-class batch remediation and fresh
validation completed before the Review 006 failure recorded below; no PASS or
integration claim was made.

Post-Review 005 remediation binds every authoritative candidate discovery
field, recomputes both positive- and zero-candidate `candidate_set_id`, requires
trusted source-outcome identity and discovery-manifest hash context, and
revalidates selected failed-fetch, review-required, and no-candidate report
paths. Locator optional decision and retained-response comparisons now cover
every duplicated identity field. No schema or public concept was added. Fresh
root evidence is: focused source-outcomes/reports/provenance `287 passed in
0.47s`; DailyMed plus byte-exact OpenAPI `321 passed in 0.80s`; Ruff PASS;
format `67` files; MyPy `--no-incremental` PASS for `34` source files; full
offline `935 passed`, two existing warnings, `80%` coverage in `7.30s`; diff
and exact 23-path scope checks PASS. This was the candidate submitted to Review
006; no PASS, Git, network, integration, or `M1B-DM-002` claim was made.

Review 006 binds exact candidate manifest
`75416c4fb6a3df9bbcf40783bcc4aab9f12e3d3c8df9118fdaebfe7f756dbeef`
and returned `FAIL — P0 0 / P1 1 / P2 0`. It verified the Review 005 closures,
then reproduced three one-field cross-request substitutions in a two-request
report: section 2 reused section 1's `acquisition_id`, `snapshot_id`, or
`source_outcome_id` while query, intent, ordinal, operation, and all other
fields remained constant. Rebuilding the report and trusted tuples from each
forged ref/outcome was accepted because the global report constraints require
only source/query disjointness and acquisition-ordinal uniqueness. Closure is
mechanical under the Owner's same-class do-not-stop authority: the existing
trusted collection must reject duplicate acquisition, snapshot, and
source-outcome IDs across the complete report, with independent two-request
negative tests and all existing positives preserved. Review 006 evidence is:
focused `319 passed in 0.74s`; combined DailyMed/OpenAPI `321 passed in 1.16s`;
Ruff PASS; format `67` files; MyPy `--no-incremental` PASS for `34` source
files; full offline `935 passed`, two existing warnings, `80%` coverage in
`9.60s`; diff check PASS. Review 007 and terminal audit remain pending; no
PASS, Git, network, integration, or `M1B-DM-002` claim is made.

Post-Review 006 remediation closes the same-class cross-request reuse defect
without a schema, public concept, dependency, or semantic change. The trusted
report acquisition collection now requires global uniqueness of
`acquisition_id`, `snapshot_id`, and `source_outcome_id`. It deliberately
preserves valid reuse of `acquisition_intent_id`, whose existing ownership and
exact-binding rules remain authoritative. Independent two-request adversarial
tests cover each rejected identity reuse and preserve positive multi-request
behavior. Fresh root evidence is: focused `291 passed in 0.67s`; combined
DailyMed/OpenAPI `325 passed in 1.14s`; Ruff PASS; format `67` files; MyPy
`--no-incremental` PASS for `34` source files; full offline `939 passed`, two
existing warnings, `80%` coverage in `9.68s`; diff and exact 24-path scope
checks, including Review 006, PASS. Review 007 and terminal audit remain
pending; no PASS, Git, network, integration, or `M1B-DM-002` claim is made.

Review 007 binds exact candidate manifest
`9a1ad8c2d2850c2b5ffcff67d5e19017beee740eb183c6b222270d1bdee258ca`
and returned `FAIL — P0 0 / P1 1 / P2 0`. It verified the Review 006
global-uniqueness closure and representative direct drift rejection for other
security-policy models. It then showed that the publicly exported
`DailyMedTrustPath.model_validate` accepts standalone rows outside the exact
frozen six: `/unfrozen/evil` with arbitrary purpose/mode, a discovery row with
`allowed_query_keys=('url',)`, and a getFile row with
`exact_query=(('type', 'pdf'),)`. The parent policy rejects these rows, but that
does not make the exported standalone construction boundary non-weakenable.
Mechanical acceptance is exact membership in one of the six frozen rows, with
direct negatives for arbitrary path/purpose, query/exact-query drift, omission,
duplication, and reordering while preserving parent validation. Review evidence
is: focused `14` and `53`; four-domain `323`; reports/source-outcomes/byte-exact
OpenAPI `273`; Ruff PASS; format `67` files; MyPy `--no-incremental` PASS for
`34` source files; full offline `939 passed`, two existing warnings, `80%`
coverage; diff check PASS. Same Owner-authorized security P1-01 remediation is
in progress. Review 008 and terminal audit remain pending; no PASS, Git,
network, integration, or `M1B-DM-002` claim is made.

## Review 011 accepted-instance boundary status

Independent Review 011 binds exact 28-path manifest
`564e352be9ad2470c58be20156036c9f66f8aa90ad9964048f085dc6d5de254b`
and records `FAIL — P0 0 / P1 2 / P2 0`. It reproduced a caller-controlled
intrinsic-only decision-validation bypass and invalid existing SourceOutcome
acceptance by the public classifier and report construction/direct-validation
boundary. These are same-class mechanical closure work under the existing
Owner authority; no serialized field, schema, public concept, dependency,
frozen semantic, or network authority is added. Fresh Review 012 and terminal
audit remain required.

The mechanical closure removes the publicly caller-controlled intrinsic-only
decision path, supplies full trusted discovery context to every downstream
decision comparator, and reconstructs SourceOutcome before classification and
at every report construction/validation boundary. Fresh evidence is focused
`281 passed`, domain plus byte-exact OpenAPI `380 passed in 0.86s`, Ruff and
format PASS, MyPy `34` source files, and full offline `959 passed` with two
expected warnings and `80%` coverage in `6.85s`; diff check passed. Review 012
and terminal audit remain required; no PASS or Git/integration claim is made.

## Review 012 locator-authority status

Independent Review 012 binds exact 29-path manifest
`8445fb3a9c2bed48819b03c8989f4d9ef593f3d7ede874f9010b417697f1d188`
and records `FAIL — P0 0 / P1 1 / P2 0`. It reproduced an incomplete public
locator-comparator path that accepted forged selection/discovery identities
when authoritative decision context was omitted. Requiring the existing exact
decision/candidate/outcome/manifest context is same-class mechanical closure;
it adds no field, schema, dependency, frozen semantic, or network authority.
Review 013 and terminal audit remain required.

The mechanical closure makes the existing decision, candidate, trusted
source-outcome identity, and discovery-manifest context mandatory for public
locator comparison and removes the incomplete intrinsic-report call. Fresh
evidence is locator-focused `137 passed`, domain plus byte-exact OpenAPI `380
passed in 0.82s`, Ruff/format PASS, MyPy `34` source files, and full offline
`959 passed` with two expected warnings and `80%` coverage in `6.59s`; diff
check passed. Review 013 and terminal audit remain required.

## Review 013 fetch-authority status

Independent Review 013 binds exact 30-path manifest
`c5ac09050724eab58b489b859d6a34d9e355ecca2adfd74bc843faf72396b959`
and records `FAIL — P0 0 / P1 1 / P2 0`. It reproduced coherently forged fetch
acquisition identities accepted by public retained-response and locator
comparators that lacked the existing trusted fetch reference. Requiring that
reference is same-class mechanical closure and adds no serialized field,
schema, dependency, frozen semantic, or network authority. Review 014 and
terminal audit remain required.

## Review 014 discovery/fetch relation status

Independent Review 014 binds exact 31-path manifest
`7ba32e4738a45f990b3b6f0fde6c2d34b9a1062aed8d6f638824479739f61274`
and records `FAIL — P0 0 / P1 1 / P2 0`. Public retained/locator comparators
must reassert that fetch uses a different acquisition ID and snapshot and a
strictly later ordinal than discovery. These are already frozen relations; the
closure adds no field, schema, dependency, semantic, or network authority.
Review 015 and terminal audit remain required.

The mechanical closure makes both public fetch comparators require a distinct
fetch acquisition ID, distinct snapshot, and strictly later ordinal than the
authoritative discovery decision, without a `+1` rule. Fresh evidence is
focused `281 passed`, domain plus byte-exact OpenAPI `380 passed in 0.88s`,
Ruff/format PASS, MyPy `34` source files, and full offline `959 passed` with two
expected warnings and `80%` coverage in `7.16s`; diff check passed. Review 015
and terminal audit remain required.

## Review 015 fixture-independence status

Independent Review 015 binds exact 32-path manifest
`9f71d93bf5710043697edfd848dc0a4d7bbb4232729edbcc3a939395f44bcd64`
and records `FAIL — P0 0 / P1 0 / P2 1`. Runtime relation closure is verified;
the positive trusted-fetch helper must construct its six non-reference values
independently instead of copying them from retained evidence. This is test-only
mechanical work with no contract, field, schema, dependency, or network change.
Review 016 and terminal audit remain required.

## Review 016 PASS and audit gate

Independent Review 016 binds pre-finalization 33-path manifest
`567f4663669759a82fc67ccf25419a443b6f2e200e5e5a36226b15c81549d700`
and records `PASS — P0 0 / P1 0 / P2 0`. It independently verified every prior
closure, full offline/static evidence, authorized scope, compatibility and
zero-network boundary. The evidence-finalized bytes require terminal audit
before any Git lifecycle or integration claim.

## Terminal Audit 001 PASS and final-byte rebind

Terminal Audit 001 binds pre-audit-record 34-path manifest
`8b0781a741163703467d7c96e732bee24c3854cdacde26405de886b6e1364405`
and records `PASS — P0 0 / P1 0 / P2 0`. It independently verified review
lineage, tests/static/lock evidence, exact authorized scope, frozen safety and
provenance semantics, compatibility and zero network. The audit record and
status update require a final-byte terminal rebind; no Git lifecycle step has
yet run.

The positive trusted-fetch fixture now uses explicit attempt/manifest/member/
link constants and independent stable-label raw artifact/hash evidence rather
than copying retained/locator values. Fresh evidence is report-focused `137
passed`, domain plus byte-exact OpenAPI `380 passed in 0.90s`, Ruff/format
PASS, MyPy `34` source files, and full offline `959 passed` with two expected
warnings and `80%` coverage in `7.06s`; diff check passed. Review 016 and
terminal audit remain required.

The mechanical closure supplies a canonical request-owned nonserialized trusted
fetch-evidence row composed only of existing typed identities. Exact fetch
acquisition, attempt, manifest, member, link, raw-artifact, and raw-hash values
are independently compared by the retained-response and locator comparators;
neither evidence object authenticates the other. Fresh evidence is focused
`281 passed`, domain plus byte-exact OpenAPI `380 passed in 0.86s`, Ruff/format
PASS, MyPy `34` source files, and full offline `959 passed` with two expected
warnings and `80%` coverage in `6.80s`; diff check passed. Review 014 and
terminal audit remain required.

Post-Review 007 remediation closes the standalone exported-model boundary:
`DailyMedTrustPath` now accepts exactly one complete frozen row from the six-row
connector trust allowlist. Direct negatives reject arbitrary path and purpose,
allowed-query and exact-query drift, omission, duplication, and reordering.
The enclosing parent policy remains unchanged, and no schema, public concept,
dependency, frozen security value, or network authority changed. Fresh root
evidence is: focused `293 passed in 0.46s`; combined DailyMed/OpenAPI `327
passed in 0.70s`; Ruff PASS; format `67` files; MyPy `--no-incremental` PASS
for `34` source files; full offline `941 passed`, two existing warnings, `80%`
coverage in `6.38s`; diff and exact 25-path scope checks, including Review 007,
PASS. Review 008 and terminal audit remain pending; no PASS, Git, network,
integration, or `M1B-DM-002` claim is made.

Review 008 binds exact candidate manifest
`939e99998c63dfe3ae664aa5ef6e265bc28e0e2787ea7cb73a32002dfb29e93e`
and returned `FAIL — P0 0 / P1 2 / P2 0`. It verified the direct standalone
trust-path closure, then found that existing model instances bypass complete
frozen revalidation. Accepted/total drift counts were TrustPath `0/5`, Redirect
`5/5`, Transport `17/19`, Connector `10/15`, XML `35/36`, and ZIP `25/28`;
representative accepted values included `authorizes_network_io=true`,
`max_attempts=99`, `external_io=true`, and
`filesystem_extraction=true`. Per-class complete-data revalidation closed all
tested canonical and nested drifts. Review 008 also showed that a standalone
LOINC row accepts arbitrary alias/title, evil URL, and mixed-row values, while
the oracle accepted `7/8` tested existing-instance drifts. Mechanical
acceptance is exact one-of-four standalone rows plus complete oracle-instance
revalidation, preserving the exact LOINC 2.82 registry. Evidence is: combined
DailyMed/OpenAPI `327`; full offline `941 passed`, two existing warnings, `80%`
coverage; Ruff PASS; format `67` files; MyPy `--no-incremental` PASS for `34`
source files; diff check PASS. Same Owner-frozen non-weakenability and LOINC
mechanical remediation is in progress. Review 009 and terminal audit remain
pending; no PASS, Git, network, integration, or `M1B-DM-002` claim is made.

Post-Review 008 remediation performs complete per-class revalidation of
existing instances for all six exported security models: trust path, redirect,
transport, connector, XML, and ZIP. Altered nested connector-policy instances
also reject. The LOINC row accepts exactly one of the four frozen rows, and
both existing row and oracle instances are revalidated against every frozen
field. No frozen policy, LOINC registry value, schema, public concept,
dependency, or network authority changed. Fresh root evidence is: focused `301
passed in 0.46s`; combined DailyMed/OpenAPI `335 passed in 0.74s`; Ruff PASS;
format `67` files; MyPy `--no-incremental` PASS for `34` source files; full
offline `949 passed`, two existing warnings, `80%` coverage in `7.33s`; diff
and exact 26-path scope checks, including Review 008, PASS. Review 009 and
terminal audit remain pending; no PASS, Git, network, integration, or
`M1B-DM-002` claim is made.

## Review 009 accepted-instance remediation status

Independent Review 009 binds manifest
`1cfb367f52576a765f7ccf5e3ef5d80053906dd7a8e4dffecb0066728350d3d4`
and returned `FAIL - P0 0 / P1 2 / P2 0`. It verified Review 008 security and
LOINC closure, then reproduced existing-instance bypasses across candidate,
stable-section, locator, retained-response, and nested report/request
boundaries. Same-class remediation applies per-class
`revalidate_instances="always"` with the existing closed, frozen, and
extra-forbid contract to all 14 newly added DM-001 context models. Candidate
binding preserves rather than normalizes completeness and termination values.

No field, schema, public concept, frozen evidence/security meaning,
dependency, connector/parser behavior, or network authority changed.
Implementation-node evidence is focused `335 passed`, domain/OpenAPI `372
passed`, Ruff and format PASS, MyPy `34` source files PASS, and diff check
PASS. Root full validation, fresh complete Review 010, and terminal audit are
pending; no PASS or Git/integration lifecycle claim is made.

Fresh authoritative root validation subsequently completed on the exact
27-path candidate, including Independent Review 009: domain plus byte-exact
OpenAPI `372 passed in 0.76s`; Ruff PASS; format `67` files; MyPy
`--no-incremental` PASS for `34` source files; full offline `951 passed`, two
expected warnings, `80%` coverage in `6.64s`; and diff check PASS. Fresh
complete Review 010 and terminal evidence audit remain pending. No PASS, Git,
network, integration, or `M1B-DM-002` claim is made.

## Supersedes / Superseded by

This ADR adds M1B DailyMed contracts without superseding ADR-002, ADR-003,
ADR-007, ADR-009, or ADR-010. No successor is authorized by this record.

## Review 010 public-method instance revalidation

Independent Review 010 binds exact manifest
`6955add1ad6e5f0d58517a749fb8b9f7b41fc1c384784ca8e11da8194b97e8e0`
and records `FAIL - P0 0 / P1 1 / P2 0`. Pydantic instance configuration did
not cover direct method calls that read already-constructed objects. The
accepted mechanical closure reconstructs complete self and argument data for
warning, candidate, decision, retained response, locator, report/request,
inherited SourceOutcome, and trusted/nested contexts before use. It changes no
serialized field, schema, frozen evidence semantics, dependency, or network
authority. Fresh validation, Review 011, and terminal audit remain required.

Fresh post-remediation validation completed with domain plus byte-exact OpenAPI
`373 passed in 0.82s`, Ruff PASS, format `67` files, MyPy `--no-incremental`
PASS for `34` source files, and the full offline suite `952 passed` with two
expected warnings and `80%` coverage in `6.64s`; diff check also passed. Fresh
complete Review 011 and terminal evidence audit remain required. No PASS, Git,
network, integration, or `M1B-DM-002` claim is made.
