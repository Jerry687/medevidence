# ME-000A Project Owner Approval Record

- Approval reference: ME-000A-OWNER-APPROVAL-001
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-26
- Status: **APPROVED FOR MERGE AND BASELINE TAGGING**
- Revision: 1
- Final independent review reference:
  ME-000A-FINAL-INDEPENDENT-REVIEW-001

## Immutable approval identity

This approval is bound exclusively to:

- M0 baseline commit:
  `8a227d5f39c77556b2fa4b3a8d6a835412575ee4`;
- M0 tag: `m0-approved-v1`;
- M0 manifest SHA-256:
  `23e8430e29c18cd4ab0b6266d671d7b999d436b083c717e1fc2c4ef11d9c683d`;
- ME-000A1 implementation commit:
  `e25f5f166cdd05e12205554f5eb98a2fe1f4278b`; and
- final ME-000A implementation candidate:
  `c6384c766d0e65240ba617d9b78f17dd7f500260`.

The M0 artifact and tag remain immutable. The approved ME-000A descendant is
derived from `m0-approved-v1`; it is not represented as an unchanged copy of
the M0 design corpus.

## Approved ME-000A scope

The Project Owner approves the following repository and toolchain scope:

- **ME-000A1:** exact CPython `3.12.13` and uv `0.11.32` baselines; the locked
  Python development environment; Ruff, formatting, mypy, pytest, coverage,
  and offline socket enforcement; Windows-native bootstrap, quality, and test
  scripts; and deterministic repository-baseline tests.
- **ME-000A2:** exact PostgreSQL `18.4` and Qdrant `1.18.3` container
  baselines; approved immutable image digests; loopback-only Docker Compose
  infrastructure; strict environment and Compose validation; isolated smoke
  testing; collision-safe ownership and cleanup; cross-platform
  infrastructure-contract tests; synchronized developer commands; and pinned
  GitHub Actions for Windows quality and Linux Compose validation.
- **Final ME-000A remediation:** the environment-restoration,
  Docker-resolution, source-gate ordering, fail-closed Compose semantics, and
  cross-platform child-output normalization corrections committed through
  exact candidate `c6384c766d0e65240ba617d9b78f17dd7f500260`.

No capability outside the authorized ME-000A repository and toolchain scope
is approved by this record.

## Independent and hosted validation acknowledgment

The Project Owner acknowledges:

- the ME-000A1 independent PASS bound to
  `e25f5f166cdd05e12205554f5eb98a2fe1f4278b`;
- the final independent PASS in
  `ME-000A-FINAL-INDEPENDENT-REVIEW-001`, bound to
  `c6384c766d0e65240ba617d9b78f17dd7f500260`;
- no Critical, High, or Medium finding remained;
- the exact final infrastructure-contract result was `114` cases passed with
  `0` failed;
- hosted GitHub Actions job `windows-quality` passed for the exact final
  candidate; and
- hosted GitHub Actions job `compose-config` passed for the exact final
  candidate.

## Merge authorization

The Project Owner authorizes the Draft PR containing the approved final
candidate and these governance records to be merged into `main` using a
**merge commit**.

- Squash merging is explicitly prohibited.
- Rebase merging is explicitly prohibited.
- This record does not itself perform or complete the merge.
- The resulting `main` merge commit must preserve the reviewed candidate's
  commit identity in its first-parent/second-parent history and include these
  final governance records.

## Approval tag and future baseline

After the authorized merge commit exists on `main`, the Project Owner
authorizes creation of:

```text
me-000a-approved-v1
```

The tag must point to the resulting `main` merge commit. It must not point
directly to the pre-merge candidate, replace `m0-approved-v1`, or be moved
after creation.

Later development must branch from the approved `main` baseline containing the
authorized merge commit and `me-000a-approved-v1`. This approval does not
begin ME-000B, ME-000C, ME-000D, a source-specific decision, or any later
milestone.

## Business-implementation boundary

ME-000A contains no medical, connector, ingestion, retrieval, tool, API,
Agent, orchestration, frontend, or other MedEvidence business
implementation. It establishes engineering, dependency, validation,
infrastructure, and CI foundations only.

## Decision

**ME-000A is approved for the authorized merge-commit workflow and subsequent
baseline tagging described in this record.**

No merge, tag, push, or later-milestone implementation is performed by this
approval record.
