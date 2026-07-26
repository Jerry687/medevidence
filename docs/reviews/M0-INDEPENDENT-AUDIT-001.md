# M0 Independent Audit Record

- Review reference: M0-INDEPENDENT-AUDIT-001
- Review type: Independent M0 consistency audit
- Original verdict: **FAIL**
- Original verdict date: 2026-07-25
- Current remediation status: ME-000-FINAL independently verified against the frozen manifest
- Current re-review verdict: **PASS — unconditional**
- Final re-review date: 2026-07-25
- Approval authority: None; the independent reviewer validates and does not approve
- Remediation owner: Boqi Niu, Project Owner
- Record revision: 2
- Frozen design manifest: `docs/reviews/M0-DESIGN-MANIFEST.sha256`
- Frozen design manifest SHA-256: `23e8430e29c18cd4ab0b6266d671d7b999d436b083c717e1fc2c4ef11d9c683d`

## Audit scope

The audit examined whether M0 design, instructions, executable configuration,
testing policy, traceability, approval metadata, and repository hygiene were
internally consistent and ready to authorize implementation.

The original M0 did **not** pass. This record preserves that historical FAIL
verdict. The final independent re-review result recorded below supersedes the
pending verification state for the exact frozen manifest, without rewriting
the original audit result.

## Findings and remediation status

| # | Original finding | Verification against pre-remediation repository | ME-000 remediation | Project-side status before final re-review |
|---|---|---|---|---|
| 1 | Redis remained in V1 executable configuration | Confirmed in Compose, `.env.example`, and README | Removed Redis service, volume, environment variables, and README runtime claim; retained deferred design note only | Remediated; verify no executable Redis reference |
| 2 | Gold-10/Development-40/Holdout-20 implied 70 rather than 60 unique cases | Confirmed: Gold-10 was documented separately from Development-40 | Defined Development-40 = Gold-10 subset + Additional-Development-30; Holdout-20 separate | Remediated; verify uniqueness and non-overlap language |
| 3 | Source outcome mixed execution, coverage, and result meaning | Confirmed: one coverage enum included `failed`; the first remediation then retained contradictory partial/failed `no_match` states | ME-000-FINAL separates planning from executed-source outcomes, replaces result `not_applicable` with `indeterminate`, freezes seven valid combinations, and forbids incomplete/failed absence claims | Remediated project-side; verify against frozen manifest |
| 4 | Citation validation lacked two explicit stages | Confirmed: structural and semantic support were not independently specified | Added deterministic structural/policy Stage 1 and versioned semantic Stage 2 with supported/uncertain/unsupported | Remediated; verify uncertain/unsupported policy and judge limits |
| 5 | Orchestration instructions allowed additional expensive/broad/sensitive approval interrupts | Confirmed in orchestration `AGENTS.md` | Restricted HITL to export-only four-node sequence; other queries are bounded/rejected/degraded | Remediated; verify no conflicting interrupt rule |
| 6 | Frontend choice remained unresolved | Confirmed in frontend `AGENTS.md`; one stale “once the UI framework is chosen” sentence remained after initial remediation | Froze Streamlit for V1, deferred React, and removed the final undecided-framework wording in ME-000-FINAL | Remediated project-side; verify against frozen manifest |
| 7 | ADR owner approval metadata was not explicit | Confirmed: ADRs had generic owner/date only | Added exact approver, role, date, reference, revision, and independent-review metadata to ADR-001–008 | Remediated; verify reviewer is not represented as approver |
| 8 | Traceability lacked exact cross-document references | Confirmed: matrix mapped only component/milestone/evidence/criterion | Rebuilt matrix with exact PRD, architecture, data, security, evaluation, ADR, milestone, evidence, and acceptance references | Remediated; verify anchors and N/A reasons |
| 9 | Required architectural invariant scenarios were incomplete | Confirmed: some principles existed but not all executable scenarios | Added INV-001–005 and linked acceptance evidence | Remediated |
| 10 | PHI boundary was principle-level, not operational | Confirmed: only broad PHI rejection language existed | Added no-upload/schema rule, public-question boundary, fail-closed rejection, no raw persistence/logging, synthetic identifiers, and no compliance claim | Remediated |
| 11 | Environment/configuration contained premature provider/vendor/version commitments | Confirmed image versions, model variables, LangSmith, OTLP vendor endpoint, and numeric connector defaults | Removed vendor/model/tracing variables and image versions; enforced gates ME-000A–D | Remediated at M0 policy level; exact versions remain intentionally deferred |
| 12 | Makefile, AGENTS, and CI test commands were inconsistent | Confirmed default test allowed sockets, contract command was absent, and CI workflow was absent | Adopted directory convention; synchronized exact quality commands; unit/contract always disable sockets; live API is opt-in | Remediated; ME-000A must pin CI/tool versions |
| 13 | `.gitignore` was missing | Confirmed absent | Added secrets, Python, environment, IDE, raw/normalized data, indexes, DB volumes, evaluation runs, exports, and logs | Remediated |
| 14 | README showed one blended flow, ambiguous export confirmation, Redis, and no traceability link | Confirmed | Rewrote README with separate planes, FAERS structured path, confirmation before export, no Redis runtime, and matrix/review links | Remediated |
| 15 | No mandatory threshold-freeze gate existed | Confirmed | Added Development-40-only proposals, approval/version freeze, one Holdout-20 run per candidate, zero-tolerance events, and invalidation after change | Remediated |
| 16 | Qdrant/BM25/model configuration appeared more settled than approved | Confirmed configuration details lacked owner/deadline gate | Added ME-000C owner/deadline covering versions, tokenizer, sparse encoding, BM25 k1/b, embedding, reranker, and limits | Remediated; values remain intentionally undecided |

## ME-000-FINAL focused findings

| Final finding | Frozen remediation claim | Independent verification required |
|---|---|---|
| Contradictory source-outcome truth table | Planning is separate; only executed sources have outcomes; exactly seven terminal combinations are valid; only successful complete execution may yield `no_match` | Verify every manifested governing definition, acceptance case, and run aggregation rule |
| Stale frontend framework wording | Streamlit is unambiguously approved for V1 and React is deferred | Verify all manifested instructions contain no undecided-framework statement |
| No immutable design identity before Git initialization | Raw-byte SHA-256 manifest freezes the exact M0 corpus | Verify every entry and the overall manifest hash independently |

## Frozen design corpus

The exact corpus under review is the lexicographically sorted
`29`-file list in
`docs/reviews/M0-DESIGN-MANIFEST.sha256`. Its raw-byte SHA-256 identity is:

```text
23e8430e29c18cd4ab0b6266d671d7b999d436b083c717e1fc2c4ef11d9c683d
```

Any modification to a manifested file invalidates this remediation claim and
the conditional owner approval. The manifest must then be regenerated and an
independent re-review repeated against the new hash. Approval/audit records and
the manifest files themselves are deliberately excluded from the design
corpus, as documented in `M0-DESIGN-MANIFEST.md`.

## Final independent re-review result

- Verdict: **PASS — unconditional**
- Manifest SHA-256:
  `23e8430e29c18cd4ab0b6266d671d7b999d436b083c717e1fc2c4ef11d9c683d`
- Manifest verification: all 29 entries verified byte-for-byte; entry format,
  ordinal ordering, repository-relative POSIX paths, file existence, and raw
  file hashes passed.
- Source-outcome inconsistency: resolved.
- Streamlit framework ambiguity: resolved; Streamlit is approved for V1 and
  React remains deferred.
- Immutable manifest binding: resolved.
- Regression result: no regressions found.
- Implementation state at review: no MedEvidence business implementation had
  begun.
- Authorization result: **ME-000A may begin** against this exact frozen
  manifest revision.

This PASS does not begin ME-000A and does not implement business logic. Any
modification to a manifested file invalidates this PASS and requires a new
manifest plus another independent re-review.
