# M1A-005 Independent Review 001

- Work item: `M1A-005`
- Branch: `feat/m1a-005-fastapi-acceptance`
- Approved `main` baseline:
  `14a38d48416e8a4b63fe72b91ceb083f1d895473`
- Reviewed implementation parent commit:
  `5a75b96a034abbaf4769f9dfde93ea3bb154567e`
- Current PR head (documentation-only child):
  `d70b3121634ba2cd1ca89d7c935c6ec470a9a988`
- Draft PR: [#7](https://github.com/Jerry687/medevidence/pull/7),
  `M1A-005: expose and validate the PubMed vertical slice`
- Hosted checks: **PASS** — `compose-config`, `dependency-audit`, and
  `windows-quality`
- Independent implementation review: **PASS — P0 0 / P1 0 / P2 0**
- Terminal evidence audit: **PASS — P0 0 / P1 0 / P2 0**
- Integration state: **NOT MERGED OR INTEGRATED**
- Live medical-source access: **NOT RUN**

## Authority reviewed

The controlling Owner freeze is
`C:\Users\BoqiNiu\Downloads\M1A-005-API-FREEZE-v1.md`: 32,586 bytes,
SHA-256 `27da352fd395833de78d8eb6f9222d84e7410c02f4efd7785dc4398ec9c46b71`,
UTF-8/LF with terminal marker `READY_FOR_M1A005_IMPLEMENTATION\n`, status
**OWNER APPROVED — IMPLEMENTATION AUTHORIZED**. It supersedes ADR-009's older
provisional `fastapi==0.140.0` pin for this work item and explicitly authorizes
only `fastapi==0.141.1`, with no FastAPI extras or Uvicorn. ADR-009 remains
unchanged.

The Owner amendment is 12,490 bytes with SHA-256
`9f69433d1497e7631709171526472584da250c118bf12fb9b7fd9077210447f7`.
It authorizes the operation-sensitive persistence correction and amended exact
26-path scope.

## Review scope

Independent review inspected the actual amended 26-path implementation and
executable behavior, including:

- the single-route FastAPI and exact normalized OpenAPI contract;
- raw-byte, strict-JSON, patient-data, catalog, and precedence boundaries;
- warning-safe forged-output handling and fixed redacted errors;
- fresh distinct UUID4 correlations for request-ID factory failures;
- concrete connector-to-tool-to-snapshot-to-repository composition with no
  construction-time I/O or implicit real-transport fallback;
- positive search PMID cardinality without publication rows or lineage;
- strict singular fetch and replay cardinality;
- exact artifact, manifest, envelope, run, report, and publication lineage;
- the exact FastAPI dependency decision and dependency evidence; and
- absence of unauthorized paths, secrets, sensitive data, or live-source
  calls.

## Decision ledger

Initial candidate
`sha256:0813bc6c42d5dee434335749f018598d716cf8be38eb9fe7e0c40421be4449ed`
received **FAIL — P0 0 / P1 2 / P2 2**. It emitted a Pydantic serialization
warning containing forged output, left request-ID factory failure outside the
versioned error boundary, lacked frozen boundary regressions, and carried stale
M1A-004 integration text.

Cycle-2 candidate
`sha256:ebf5d7c7994dc6ae40768f44852808bd6f8c4950c58b3d9640ff51da91e5b5c6`
closed those findings, but independent review remained **FAIL** because all
request-ID factory failures shared one hard-coded fallback correlation.

Cycle-3 candidate
`sha256:295c8401b9aa4f44038f93c16c8425c5a6266e6949016656e33f4aebd3020045`
generates a fresh canonical local UUID4 correlation at each failure boundary
and includes a deterministic regression proving distinct valid identifiers
without untrusted-value leakage. Independent review returned
**PASS — P0 0 / P1 0 / P2 0**.

Cycle-4 evidence candidate
`sha256:cf1a65aecae71dbd8f35b56d29adb90ae43152512985ec39a2475665601053cb`
was committed as the reviewed implementation
`5a75b96a034abbaf4769f9dfde93ea3bb154567e`. Hosted checks then passed,
independent review returned **PASS — P0 0 / P1 0 / P2 0**, and the
terminal evidence audit returned **PASS — P0 0 / P1 0 / P2 0**.

Cycle-5 evidence candidate
`sha256:ff2652651de9cde37ff767dd3d17201505062a1c64879889754cc22a96051177`
was committed as documentation-only child
`d70b3121634ba2cd1ca89d7c935c6ec470a9a988` and pushed as the current Draft PR
`#7` head.

The prior failures remain historical evidence and are not current
implementation findings.

## Reviewed evidence

- focused M1A-005 selection excluding live: 46 passed in 0.55 seconds;
- full sockets-disabled unit/contract gate: 713 passed in 4.74 seconds, 79%
  coverage, with two expected warnings;
- `uv lock --check`, Ruff, 67-file format check, and MyPy over 34 source files:
  exit 0;
- PostgreSQL repository/API gate: 254 passed in 7.30 seconds; cleanup residue
  0 containers / 0 networks / 0 volumes;
- normalized OpenAPI: 40,511 bytes, SHA-256
  `0d735acbbb1503dcc3235a37193b9d383cae08b8dc4fdb3b0e42616982ff028a`;
- dependency evidence: 61 packages/licenses, zero missing or review-required
  licenses, zero vulnerabilities, and zero skipped packages;
- dependency candidate file-set identity:
  `sha256:e9dd241de6cfbf4a0cb05c863d32e4edcf21cf6440559124ba93233466ab630b`;
- dependency evidence-manifest SHA-256:
  `756c21b38536114807daee5dcb5e8716e16ab145742ba38739aeb83fc5cf9827`;
- implementation scope: 26/26 paths, zero unexpected or missing; and
- no live PubMed or other medical-source request occurred.

Hosted `compose-config`, `dependency-audit`, and `windows-quality` checks passed
for reviewed implementation commit
`5a75b96a034abbaf4769f9dfde93ea3bb154567e`. Current PR head
`d70b3121634ba2cd1ca89d7c935c6ec470a9a988` is its documentation-only child.

## Decision

**PASS — P0 0 / P1 0 / P2 0.** Independent review and terminal evidence audit
both passed for reviewed implementation commit
`5a75b96a034abbaf4769f9dfde93ea3bb154567e`. Current Draft PR `#7` head
`d70b3121634ba2cd1ca89d7c935c6ec470a9a988` adds only the committed and pushed
cycle-5 documentation ledger. This is not evidence of merge, integration into
`main`, or live PubMed acceptance; none of those occurred.

The cycle-5 ledger updates are committed and pushed at current PR head
`d70b3121634ba2cd1ca89d7c935c6ec470a9a988`; this cycle-6 correction is not
committed or pushed under the current authorization. No code, dependency,
schema, or public contract changed during either documentation-only cycle.
