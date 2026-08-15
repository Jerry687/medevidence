# M1B-ACCEPTANCE-001 delivery record

- Status: `PASS_INDEPENDENT_REVIEW_PENDING_TERMINAL_AUDIT`
- Branch: `codex/m1b-acceptance-001-closeout`
- Baseline: `748de36237b264f95cfd7f483434cf617e0e79cc`
- Candidate commit: not created
- Independent review: `PASS` - `P0 0 / P1 0 / P2 0`; A 0 / B 0 / C 0
- Terminal evidence audit: pending
- Completion: not claimed

## Objective and acceptance boundary

Accept the integrated M1B system without adding source behavior. PubMed's
accepted M1A behavior remains unchanged; DailyMed and FAERS retain their
integrated request, report, and API surfaces; and CADEC remains auxiliary-only.
Repository governance records CADEC with
`planning_status=skipped_by_policy` and
`reason_code=source_execution_not_authorized`, while each runtime
`M1BResearchReportV1.source_plan` remains exactly the sources selected by that
request. CADEC has no M1B query request, connector invocation through the
research request, `SourceOutcome`, report section, API/OpenAPI execution
surface, persistence, search, index, or retrieval execution.

This closeout binds accepted interoperability evidence; it does not copy raw
provider or corpus payloads into Git. The accepted outcomes remain bounded
engineering evidence, not clinical conclusions. Reports remain research-only,
non-clinical, non-exportable drafts. Only successful complete execution may
produce exhaustive `no_match`; partial or failed zero-result execution remains
`indeterminate`.

## Accepted interoperability evidence

### PubMed

The immutable [M1A live run 002 acceptance](M1A-LIVE-RUN-002-ACCEPTANCE.md)
remains authoritative. Its redacted external record is identified only by
external root label `OWNER_EXTERNAL_M1A_LIVE_RUN_002_ROOT` and relative label
`acceptance/pubmed-live-b1ab911398624933ab8fc06de2e08596.json`. The record is
3,223 bytes with SHA-256
`008770e8155eee608aa71fab08cdd2a223f1e9ec92824427cc7a3409c6f69f25`
and binds code revision `531f867006f3d01ebbc14633ad6e5509e4e70a47`, schema
`1.0`, connector `m1a-002`, and execution time
`2026-08-09T05:13:33.284549Z`.

The accepted single run used two contiguous acquisitions and exactly two
requests. Search was `succeeded / partial / matches`, with 100 valid results,
one page, and `truncated=true`; fetch was
`succeeded / complete / matches`, with one retained publication, one page, and
`truncated=false`. The partial search is explicitly non-exhaustive. Raw
artifact, canonical-manifest, and acquisition-registration identities remain
bound in the immutable M1A record and external evidence; source content is not
reproduced here.

### DailyMed

`M1B-DAILYMED-LIVE-SMOKE-002` ran once at exact revision
`8674b500346e6341ace6d4e893a3ed6a87d123a3` against the separately authorized
one-page discovery request. It used one HTTP transaction, zero retries, and
zero redirects. The official summary response parsed with exact SETID and SPL
version retention. Its truthful terminal state is
`succeeded / partial / matches`: one summary record was admitted from page 1,
the provider reported total 9 and next page 2, and the one-page acceptance
bound makes `truncated=true`. No selection, ingredient enrichment, SETID
follow-up, history, NDC, packaging, SPL, or ZIP request occurred.

External-only evidence is bound as follows:

| File | Bytes | SHA-256 |
|---|---:|---|
| `dailymed-live-smoke-002-response.bin` | 650 | `101b9137c17446e7ce43a9ce5fce0bb24a90b82ca600057e659e8abfd3bdb6da` |
| `dailymed-live-smoke-002-acceptance.json` | 5,351 | `9b37548746a0f9d2209cf481c51256fbfbc09ed2861cd2ecb3b27c17c7381404` |

### FAERS/openFDA

`M1B-FAERS-LIVE-SMOKE-003` ran once at exact integrated revision
`748de36237b264f95cfd7f483434cf617e0e79cc`. The generated one-page count URL
preserved the frozen Boolean expression, contained the corrected encoded date
separator `%20TO%20`, and did not contain `%2BTO%2B`. It used one HTTP attempt,
zero retries, zero redirects, and no API key. The complete HTTP 404 response
matched one exact strict openFDA empty-result envelope and was retained
unchanged. The integrated connector therefore truthfully returned
`succeeded / complete / no_match`, with zero buckets,
`valid_result_count=0`, `pages_completed=1`, `truncated=false`, and no
`failure_id`.

External-only evidence is bound as follows:

| File | Bytes | SHA-256 |
|---|---:|---|
| `faers-live-smoke-003-response.bin` | 80 | `57b1e7534d003e4246182162fd2469cdf038de39405056f44fc006715e5496da` |
| `faers-live-smoke-003-acceptance.json` | 7,981 | `1b097a4cfcce39afcd06caa687f9c095bcaed138378b77a30f4d71e76e2592f4` |

FAERS buckets remain descriptive provider-count occurrences only. This
acceptance does not support incidence, causality, exposure, relative risk,
comparative safety, or product ranking.

### CADEC

CADEC requires no network smoke. Its accepted interoperability evidence is the
exact read-only local archive verification and integrated loader state bound by
[M1B-CADEC-003](M1B-CADEC-003.md) and
[ADR-013](../docs/decisions/ADR-013-m1b-cadec-asset-contract.md). The archive
SHA-256 is
`4045b926a0a5735f00f785f7ad935e5a73731d6ab607d11d88880a334be18c4a`;
the authoritative manifest is 1,699,979 bytes with SHA-256
`1c475ded0e7a2e0d80fe0909f2ccf1131c746da6ffc9c52879bfd9076234abfa`;
and the freeze audit is 6,354 bytes with SHA-256
`18928091762df33fc1fc39e9d45a55c86637a0c55c1d5cc987bc12e55a36f753`.

The loader reproduced 1,250 canonical and 1,248 approved documents, the exact
two exclusions, five rejected malformed rows, two approved zero-byte documents
with zero annotation rows, 91 visible reference-binding limitations, 24,478
provider-gold annotations and locators, the exact CP1252 exception, and split
counts 992/119/137. CADEC-002 feature
`03fffef7ad8f68a9ca36c4961a5264b2e0b295ff` was integrated by merge
`a2b97b5a3562fa68857d09fa9f4cd7562b98bd5a` through PR #20 with terminal
aggregate
`d307456bcfb4b5cf20392d93e922fb75d0d5684d9e5064c8a811ac960f973d9a`.
CADEC-003 feature `83617405e58bcec657bdaa84aceb8d2460d46fb1` was integrated
by merge `c226a632753e6fc65e8c84c74ec568d994612b7d` through PR #21.

CADEC remains provider-gold only, REDIST/VOCAB restricted, Option-A bound,
metadata-only, auxiliary-only, and not directly retrieval-consumable. No
archive or corpus bytes, restricted terminology payload, or real
corpus-derived fixture enters Git.

## Immutable failed interoperability history

Earlier failed runs remain evidence of their exact historical outcomes and are
not used as acceptance PASS evidence:

- PubMed Run 001 remains
  `M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE`; it never
  established live acceptance.
- DailyMed Smoke001 remains `failed / unavailable / indeterminate`. Its
  650-byte response has SHA-256
  `101b9137c17446e7ce43a9ce5fce0bb24a90b82ca600057e659e8abfd3bdb6da`;
  its 4,805-byte acceptance record has SHA-256
  `e13ef9b3f33fff9b6e7b2b9e3bda656770d6d2552e566d2272e9f6c671c06260`;
  and its 5,100-byte offline diagnosis has SHA-256
  `2937c210dc025d6b31176b3e7cfddc223380afec3458006751ef95d9283ff4fb`.
- FAERS Smoke001 remains `failed / partial / indeterminate`. Its 242-byte
  response has SHA-256
  `3890833a4db92fb4bb14814ce3024795a496b48ee821a66b69bed73b2db1ef9e`;
  its 9,223-byte acceptance record has SHA-256
  `cd7ad305d709deb4c70f0ca6d87db5c4521df5015ce70ebe771d788488ec9cb3`;
  and its 7,169-byte offline diagnosis has SHA-256
  `fd6c17f61772e4f7424b98930fa11134d25e5c86c692adafac39aba9c8acf5dc`.
- FAERS Smoke002 remains `failed / partial / indeterminate`. Its 80-byte
  response has SHA-256
  `57b1e7534d003e4246182162fd2469cdf038de39405056f44fc006715e5496da`;
  its 8,105-byte acceptance record has SHA-256
  `7d3bf1cb11268e22b5b90c4574e446322724314b346aecdefe61f788e927ab75`.

The later successful smokes supplement this history; they do not rewrite it.

## Integrated M1B system invariants

- PubMed accepted M1A behavior remains unchanged.
- DailyMed product/version selection semantics remain exact; discovery-summary
  acceptance does not invent ingredient identity or authoritative selection.
- FAERS remains bounded aggregate reporting with mandatory limitations.
- CADEC remains governance-visible as `skipped_by_policy`, execution-disabled
  in M1B, and auxiliary-only.
- `SourceOutcome` exists only for an executed source. A skipped source receives
  no fabricated outcome, and partial or failed zero-result states remain
  `indeterminate`.
- Immutable source identity, response/snapshot hashes, request identity,
  timestamps, parser/connector revision, and transformation lineage remain
  replay-bound.
- Protected API/OpenAPI contracts remain unchanged, and ordinary validation
  remains offline by default.
- Reports remain draft, research-only, non-clinical, and non-exportable.

## Validation and independent review

Writer validation passed with no medical-source network access:

- focused M1B acceptance selection: `461 passed`, two expected warnings;
- injected-port PubMed integration: `1 passed`;
- protected OpenAPI selection: `11 passed`;
- offline/dependency boundary selection: `94 passed`, one expected warning;
- full unit/contract suite: `1835 passed`, two expected warnings, 79% coverage;
- Ruff check: passed;
- Ruff format check: passed for 120 files;
- MyPy: passed for 52 source files; and
- `git diff --check`: passed.

The independent reviewer then ran a broader focused superset (`609 passed`,
two expected warnings), injected-port PubMed (`1 passed`), protected OpenAPI
(`11 passed`), offline/dependency boundaries (`94 passed`, one expected
warning), and the full unit/contract suite (`1835 passed`, two expected
warnings, 79% coverage). The reviewer also passed Ruff, format over 120 files,
MyPy over 52 source files, exact scope, diff, encoding, Markdown, secret,
payload-boundary, and evidence-reconciliation gates.

[Review001](../docs/reviews/M1B-ACCEPTANCE-001-INDEPENDENT-REVIEW-001.md)
returned `PASS - P0 0 / P1 0 / P2 0`, with A 0 / B 0 / C 0. No remediation
cycle was required. The review inspected the pre-persistence three-file
candidate at canonical aggregate
`63962b09c0489e25bd714b24320b0cc0cf1249a92364d2087f5fc3099f821d44`.
Persisting the review outcome changes candidate bytes, so this value is
historical review input only and is not the final candidate identity. The
terminal evidence audit must recompute every path hash and the canonical
aggregate from the post-persistence bytes.

## Candidate scope and pending lifecycle

This documentation candidate is limited to:

- `.delivery/M1B-INTEGRATION-001.md`;
- `.delivery/M1B-ACCEPTANCE-001.md`; and
- `docs/reviews/M1B-ACCEPTANCE-001-INDEPENDENT-REVIEW-001.md`.

No source, test, API/OpenAPI, dependency, persistence, retrieval, M2, M3, UI,
or corpus path is changed. After Smoke003, this documentation node made no
medical-source request, archive access, database operation, or M2-worktree
access. Validation and independent review passed. Exact-byte rebind, terminal
audit, commit, hosted CI, merge, and integrated verification remain pending.

## Post-terminal and integration targets — not achieved

Only a later terminal PASS followed by successful Git integration may establish:

- `M1B-ACCEPTANCE-001_COMPLETE`;
- `M1B_COMPLETE`;
- `M1_COMPLETE`; and
- `READY_FOR_M2`.

This candidate does not claim any of those markers.

## Owner interview questions

1. Why does the DailyMed partial match establish interoperability but not an
   exhaustive discovery result or authoritative ingredient selection?
2. Why can only the two exact strict openFDA empty-result envelopes map a
   complete FAERS count query to `no_match`?
3. Why does CADEC governance visibility not create a runtime request,
   `SourceOutcome`, report section, or retrieval authorization?
