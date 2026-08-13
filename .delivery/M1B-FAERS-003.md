# M1B-FAERS-003 delivery record

## Status

`TERMINAL_REAUDIT002_P2_REMEDIATED_AWAITING_FINAL_REBIND`

Branch: `feat/m1b-faers-003-report-api`

Baseline and current unstaged HEAD:
`263be374bd7039b07ded5a5fc095b2377c3ae37c`

Authoritative Owner Freeze: 680,144 bytes, SHA-256
`1701431e299542d3ef16f29efc45d03c7dae58259385e18ab7273bd64519d372`.

## Implemented behavior

- `build_faers_report` accepts only exact typed FAERS aggregate executions,
  builds one complete locator per canonical bucket, propagates the frozen
  mandatory limitations, and returns a draft, research-only, non-exportable
  M1B report after authoritative comparator validation.
- `POST /v1/research/faers` is registered only when an explicit
  `FaersReportApplicationPort` is injected. Raw request, required response
  presence, source ownership, planning, scope, section, and request echo
  validation fail closed.
- OpenAPI exposes the additive FAERS route and report graph without changing
  the default M1A schema, PubMed path/component closure, or DailyMed-only
  schema.
- Composition forwards only an injected application. It installs no connector,
  persistence adapter, credential, transport, or network fallback.
- The live FAERS harness is unconditionally skipped pending a separate exact
  Owner authorization.

The exact statistical unit remains `provider_count_occurrence`; the role policy
remains `unfiltered_provider_roles`; and `GI_PT_SET_M1B_V1` remains exactly
`("DIARRHOEA", "NAUSEA", "VOMITING")`. No individual FAERS report, narrative,
or provider payload is represented. Counts establish no incidence, causality,
risk, comparative safety, ranking, or general absence of GI adverse events.

## Validation evidence

- Focused report/API/OpenAPI:
  `194 passed`, one existing TestClient warning.
- Offline FAERS API integration: `1 passed` with sockets disabled.
- Live harness: one test collected and `1 skipped` with the separate-Owner-
  authorization reason.
- Full unit and contract suite with sockets disabled: `1435 passed`, two
  expected warnings, 80% coverage.
- Dependency/offline boundary selection: `12 passed`, one expected socket-block
  warning.
- Ruff: PASS.
- Format check: 99 files already formatted.
- MyPy: PASS for 46 source files.
- `git diff --check`: PASS.
- Enabled OpenAPI fixture: 100,987 bytes, SHA-256
  `d644412d660bc886cace41c78c3953ef41649e73eead209372efecbdc346cec6`.

## Scope and operations

Changed implementation/test/documentation paths are confined to K.6. Frozen
connector, parser, ingestion, persistence, migration, and dependency files are
unchanged. No CADEC implementation was started.

Medical-source requests: `0`. Other external network requests: `0`. Database,
Docker, dependency, commit, push, PR, CI, merge, and integration operations:
`0`. One authorized staging operation was performed after the initial
Re-Audit002 PASS and one unstaging operation restored the empty index after its
corrected FAIL; no commit or remote operation occurred.

## Review and remaining gates

Independent Review001 bound the exact 22-path candidate manifest
`a4072857a957db638e3395f7e4335c702df91909a2b157c851367c01e7843939`
and recorded `FAIL - P0 0 / P1 2 / P2 0`. The two mechanical findings are raw
JSON integral-float coercion into integer fields and source-generic FAERS route
OpenAPI schemas that over-advertise shapes rejected at runtime. At that
Review001 checkpoint, remediation and fresh Review002 were required. This
record makes no completion, merge, integrated verification,
vertical-slice-complete, or CADEC-readiness claim.

Remediation cycle 1/3 closed both findings without changing serialized
envelopes or source semantics. The raw boundary now compares JSON primitives
type-sensitively and tests five invalid numeric classes across all 17 frozen
integer paths plus HTTP representatives. FAERS-route-only OpenAPI overlay
components constrain exact FAERS requests, plans, outcomes, and sections while
the default, PubMed, and DailyMed-only byte pins remain unchanged. The enabled
fixture is 103,037 bytes, SHA-256
`1669d1698dce678e6980f1ba723df2c503243b946c0ebfe263cebfe89f209d77`.

Post-remediation evidence: focused report/API/OpenAPI `288 passed`; offline
integration `1 passed`; full sockets-disabled unit/contract suite `1529
passed`, two expected warnings, 80% coverage; dependency/offline boundary `12
passed`; Ruff, format (99 files), MyPy (46 files), and diff check PASS. Fresh
complete Review002 remains required.

Independent Review002 completed a fresh whole-candidate review and recorded
`PASS - P0 0 / P1 0 / P2 0` on exact pre-append manifest
`7906832214221f846178b2260197bf36e90d95bced7f6f1a4e6e1eab2c191945`
(23 rows, 2,333 preimage bytes). It independently reproduced both closures,
the schema evaluator matrix, the full offline/static gates, scope and dependency
boundaries, and zero network activity. At that Review002 checkpoint, terminal
evidence audit remained pending; no Git or completion claim was made.

Terminal Evidence Audit001 independently passed the exact post-Review002
candidate manifest
`90db3c0c0aa5c2ce96d45570ed5068050d8ee5d4906c572c14ca0269831615bc`
(23 rows, 2,333 bytes) with `P0 0 / P1 0 / P2 0`. Fresh audit evidence was
focused `288 passed`, integration `1 passed`, live authorization skip `1`,
boundary `12 passed`, full offline `1529 passed` with two expected warnings and
80% coverage, Ruff/format/MyPy/diff/scope/encoding PASS, and zero medical-source
or other network activity. At that Audit001 checkpoint, final byte rebind and
Git lifecycle remained pending.

Audit-process disclosure: the Audit001 coverage command refreshed ignored
`.coverage` and `coverage.xml`; candidate bytes and Git state did not change.
Strict read-only Re-Audit002 subsequently corrected its verdict to `FAIL - P0
0 / P1 0 / P2 1` because TRACEABILITY still contained a stale paragraph saying
review and audit were pending. The stale paragraph is now removed and the
current evidence distinguishes Review002 PASS, Audit001 candidate-quality
evidence, Re-Audit002 FAIL, and the required fresh final-byte rebind. An
authorized staging attempt made after the initial Re-Audit002 PASS was fully
unstaged after the correction; no commit or remote Git operation occurred.
Strict read-only Re-Audit003 then recorded `FAIL - P0 0 / P1 0 / P2 1`
because the earlier operations summary still claimed staging operations were
zero. The summary now records the exact stage-and-unstage history. Fresh strict
read-only final-byte rebind remains required before Git eligibility.

## Owner defense questions

1. Why is the FAERS route absent unless an application port is explicitly
   injected?
2. Why must every aggregate count carry the complete mandatory limitation
   tuple and never be presented as incidence or risk?
3. Which byte pins prove the existing PubMed and DailyMed API surfaces did not
   drift?
