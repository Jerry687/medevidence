# M1A-001A Independent Governance Review Record

- Review reference: M1A-001A-INDEPENDENT-REVIEW-001
- Review type: Independent uncommitted-governance-candidate review
- Review date: 2026-07-26
- Verdict: **PASS**
- Safe for Project Owner activation: **YES**
- Approval authority: None; this review validates and does not approve the ADR,
  dependencies, retention policy, implementation start, merge, or tag
- Project Owner:
  Boqi Niu
- Governing decision:
  [ADR-009](../decisions/ADR-009-m1a-pubmed-vertical-slice-contracts.md)
- Owner authorization:
  [M1A-001A-OWNER-AUTHORIZATION-001](M1A-001A-OWNER-AUTHORIZATION-001.md)

## Immutable review identity

This review is bound to:

- parent baseline commit:
  `540420d437ff7306f4c53dc784ccf8ec5ced9e1d`;
- branch at review:
  `docs/m1a-001a-decision-gates`;
- candidate type:
  uncommitted five-file governance candidate;
- candidate file count:
  `5`; and
- candidate-set SHA-256:
  `b3620a0445c51023bf68ed4d9e2c0a4ad5a9a429fc57c0e5e5cb20c87998ec5d`.

The exact reviewed file identities are:

```text
5729126c8e634e8f8f5e75aec9e449c6405f5b748bc069aebe63c46b34af4558  AGENTS.md
22ff5672a246bd9cd4e29f579613bb84550c7d2fdbf8d8926da16f57ea9386bb  README.md
8dc56bfbca1ff0198c055a8829cbed53d165573f118823a67addb69d43afd5d7  docs/decisions/ADR-009-m1a-pubmed-vertical-slice-contracts.md
100abb2234b1aaefce6760f7eed3cf8686d01ec876d194d82b1cf1f7a74b3d01  docs/decisions/README.md
cf6b21cccb38ed87d28ffec26bf75600df2be75331e6c9f2955a2e4d66606dbd  docs/reviews/M1A-001A-OWNER-AUTHORIZATION-001.md
```

The candidate-set identity is the SHA-256 of the displayed five lowercase
hash/path lines encoded as UTF-8 without BOM, with repository-relative POSIX
paths, ordinal path ordering, exactly two spaces between each hash and path,
and one LF after every line.

This review record is excluded from the five-file set to avoid self-reference.
No candidate commit existed during review. Before any Git write, all five
file hashes and the candidate-set hash must be recomputed. A later commit is a
valid committed candidate only when its corresponding five file bytes match
the identities above and it also contains this review record unchanged.

## Review scope

The review covered:

- phase transition and the seven sequential M1A work items;
- package and dependency direction;
- `ResearchScope`, source planning, and all source outcomes;
- publication identity, publication-status safety, claims, citations, report
  warnings, and API preservation;
- exact raw snapshots, manifests, replay, and PostgreSQL metadata authority;
- dependency pins and recorded security/compatibility risks;
- live-query execution boundaries;
- approved retention policy `M1A-LIVE-RETENTION-v1`;
- the no-standalone-ASGI decision;
- post-merge authorization of only `M1A-001B`;
- preservation of historical M0 and `ME-000A` artifacts; and
- Git path, staging, whitespace, link, and candidate-hash state.

No business implementation, dependency installation, container execution,
external API call, staging, commit, merge, tag, or push was in scope.

## Findings

- Critical findings: none.
- High findings: none.
- Medium findings: none.
- Low findings: none.

No blocking finding remains.

## Publication-status safety

ADR-009 requires a typed publication-status object with current/no-known-
notice, corrected, retracted, expression-of-concern, and unknown/unverified
states. It preserves status source, notice relationship, related PMID or
notice identity, retrieval-as-of provenance, warning codes, disclosure, and a
deterministic status identity.

Citation validation fails closed for missing, mismatched, stale, or drifted
status identity, warning identity, notice relationship, related PMID, source,
or provenance. Publication status remains independent of `SourceOutcome`, so
a successfully retrieved retracted publication is not misclassified as a
connector failure.

The deterministic claim policy:

- rejects retracted evidence as unqualified affirmative support;
- permits retracted evidence only for explicit status/history context;
- prevents expression-of-concern evidence from becoming unqualified support;
- requires correction relationships to be resolved and disclosed;
- prevents unknown status from silently becoming current; and
- creates no claim when required status provenance, relationship, identity, or
  warnings cannot be validated.

Source-level and claim-level warnings are required in `ResearchReport`, and
the later API serializer must preserve their identities, references,
relationships, and disclosure. The ten deterministic `PS-01` through `PS-10`
acceptance requirements cover the ordinary, corrected, retracted,
retraction-context, expression-of-concern, missing-warning, mismatch, drift,
unknown, and serialization cases.

Result: **PASS**.

## Live-query retention and execution boundary

The Project Owner selected `M1A-LIVE-RETENTION-v1` with:

- raw bytes in the configured immutable snapshot root outside Git through the
  V1 lifecycle;
- manifests outside Git retained indefinitely;
- normalized publication records outside Git through the V1 lifecycle;
- PostgreSQL metadata retained indefinitely with auditable disposition;
- redacted acceptance summaries eligible for `docs/reviews` and indefinite
  retention;
- ordinary redacted operational logs outside Git with a 90-day lifetime;
- immutable retention of partial/pre-failure bytes;
- typed metadata and a zero-file manifest for wholly unavailable attempts;
- content-addressed reuse plus distinct run identities;
- supplement-not-replace supersession;
- quarantine/invalid marking for corrupt artifacts; and
- Owner-only deletion with an auditable disposition record.

The retention decision does not authorize live execution. The exact query,
NCBI client-identification values, execution time, and final acceptance command
remain subject to focused Owner approval before `M1A-005`. Default CI remains
offline.

Result: **PASS**.

## Dependency and ASGI decisions

ADR-009 and the authorization contain the same nine direct pins and classes,
including `fastapi==0.140.0` and `psycopg[binary]==3.3.4`.

The Psycopg record preserves the bundled `libpq`, `libssl`, and other native-
library inventory; advisory-monitoring and patch ownership; platform-dependent
best-effort wheel availability; lock, vulnerability, and PostgreSQL
integration validation; production-suitability reassessment; and possible
preference for locally linked or source-built deployment.

No standalone ASGI server dependency is authorized. `M1A-005` may use FastAPI
through an in-process ASGI test client. Uvicorn or another server requires a
later explicit Owner decision.

Result: **PASS**.

## Previous-contract preservation

The candidate preserves:

- exactly seven sequential M1A work items and separate focused Draft PRs;
- package boundaries and inward dependency direction;
- `ResearchScope`;
- seven valid and eleven invalid `SourceOutcome` combinations;
- publication and citation identity, exact Unicode offsets, and hashes;
- deterministic attributed extracts and no-valid-span/no-claim behavior;
- immutable snapshots, canonical manifests, and replay;
- PostgreSQL metadata authority and raw bytes outside database columns;
- draft-only FastAPI transport with no export;
- nine exact direct dependency pins;
- approved historical M0 and `ME-000A` identities and records;
- an empty production dependency list in `pyproject.toml`; and
- no MedEvidence business implementation.

Result: **PASS**.

## Structural validation

The review executed read-only checks for:

- `git diff --check`;
- the exact five candidate paths before this review record was added;
- Markdown local-link targets;
- publication-status consistency;
- all 16 resolved Owner decisions;
- nine-row dependency-table consistency;
- stale/current-state language;
- exact authorization status;
- whitespace and final LF;
- production dependency and lock preservation; and
- initial/final candidate hash identity.

The focused checks passed. The full implementation quality suite was not run
because this is a documentation-only governance review and the strict task
boundary prohibited generated artifacts, dependency changes, and business
implementation.

## Decision

**M1A-001A passes independent governance review.**

The exact five-file uncommitted candidate identified above is safe for Project
Owner activation. The reviewer does not approve ADR-009, dependencies,
retention policy, implementation start, merge, or tag.

After Owner activation, the next Git workflow is:

1. reverify the five candidate hashes and this review record;
2. intentionally create one focused governance candidate commit;
3. independently verify the committed tree and record the exact candidate
   commit SHA;
4. obtain Project Owner merge approval bound to that SHA;
5. merge through the explicitly approved merge method; and
6. begin only `M1A-001B` from the resulting approved `main` baseline.

No Git write action is performed by this review.
