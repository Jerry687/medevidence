# ME-000A Project Owner Authorization Record

- Authorization reference: ME-000A-OWNER-AUTHORIZATION-001
- Authorized by: Boqi Niu
- Authorization role: Project Owner
- Authorization date: 2026-07-25
- Status: **AUTHORIZED FOR PLANNING AND IMPLEMENTATION REVIEW**
- Revision: 1
- Required independent review: ME-000A implementation review before merge

## Purpose

This record authorizes repository and toolchain work for decision gate
`ME-000A`. It records the Project Owner's governance interpretation for
descendant commits derived from the approved M0 artifact.

This record is not an M0 manifest replacement, does not amend the historical
M0 approval, and does not authorize medical or application business logic.

## Immutable M0 artifact

The approved M0 artifact remains permanently and immutably bound to:

- commit: `8a227d5f39c77556b2fa4b3a8d6a835412575ee4`;
- tag: `m0-approved-v1`;
- manifest SHA-256:
  `23e8430e29c18cd4ab0b6266d671d7b999d436b083c717e1fc2c4ef11d9c683d`.

The M0 approval is artifact-scoped. It does not require every descendant
commit to remain byte-identical to the M0 manifest.

## Descendant-commit interpretation

A descendant ME-000A commit may modify authorized manifested executable
placeholders and operational instructions. Such modification:

1. does not retroactively invalidate the historical M0 approval;
2. means the descendant tree is no longer byte-identical to the M0 manifest;
3. must be described as **derived from `m0-approved-v1`**, not as an unchanged
   M0-approved corpus;
4. must not regenerate or overwrite the M0 manifest;
5. must not move the `m0-approved-v1` tag; and
6. must receive its own implementation review and Project Owner approval
   before merge.

## Authorized ME-000A file categories

ME-000A changes are authorized only for repository and toolchain work,
including:

- `.python-version`;
- `pyproject.toml`;
- `uv.lock`;
- `.env.example`;
- `docker-compose.yml`;
- `Makefile`;
- `.github/workflows/quality.yml`;
- `.gitignore`;
- PowerShell scripts;
- offline placeholder tests;
- README Windows setup and developer-command sections; and
- root or nested `AGENTS.md` files only where required to synchronize actual
  validation commands and the Windows-native workflow.

Changes to `AGENTS.md` must not change frozen product scope, architecture,
security, source semantics, HITL policy, evaluation policy, or milestone
boundaries.

## Frozen during ME-000A

The following files and categories remain frozen:

- `docs/PRD.md`;
- `docs/ARCHITECTURE.md`;
- `docs/DATA_SOURCES.md`;
- `docs/EVALUATION_PLAN.md`;
- `docs/SECURITY.md`;
- `docs/TRACEABILITY_MATRIX.md`;
- `docs/decisions/*`;
- `docs/reviews/M0-DESIGN-MANIFEST.sha256`;
- `docs/reviews/M0-DESIGN-MANIFEST.md`;
- the M0 Project Owner approval record; and
- the M0 independent audit record.

If ME-000A reveals that a frozen design document or ADR must change,
implementation must stop and a formal design-change proposal must be
submitted. Frozen records must not be silently edited.

## ME-000A review and approval requirements

Before ME-000A may merge, it requires:

- a focused diff against `m0-approved-v1`;
- all required quality and offline-test gates passing;
- Docker Compose configuration validation;
- an independent ME-000A implementation review;
- a clean working tree; and
- a dedicated Project Owner approval commit and tag, proposed as
  `me-000a-approved-v1`.

The independent reviewer validates the implementation but does not approve
product scope, architecture, security policy, or the decision gate. Final
approval authority remains with the Project Owner.
