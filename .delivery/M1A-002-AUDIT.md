# M1A-002 terminal audit snapshot

Updated: `2026-08-05`

This phase-local snapshot binds the deterministic final-audit helper to the
M1A-002 candidate remediated under the Owner-authorized fourth B-017 cycle.
The candidate is based on local M1A-001B commit
`8f1405f334b2f5c3b52d16e9b1f95cc6c800ae06`. The repeated independent
terminal security audit returned unconditional PASS. This is a pre-commit
snapshot with decision `READY_TO_COMMIT`: the exact M1A-002 commit, final
commit identity, post-commit clean worktree, full completion, and final handoff
do not yet exist.

| Item | Status | Evidence |
|---|---|---|
| Fixed-host bounded PubMed connector | DONE | Exact host/path and finite bounds; redirect query components validate every percent escape, decode to bytes, require strict UTF-8, and preserve exact decoded pairs before another request |
| Hardened parsing and evidence mapping | DONE | `defusedxml`; invalid/incomplete/malformed distinctions; per-response provenance; conservative publication-status mapping; duplicate whole-record conflicts fail closed across the full fetch operation |
| Owner offline acceptance matrix | DONE | 23 required cases passed, including success/empty/truncation/retry/error/partial/redirect/lookalike/no-network paths |
| Focused regression and architecture validation | DONE | 178 tests passed with sockets disabled; both required B-017 regressions passed |
| Full repository validation | DONE | Ruff lint PASS; Ruff format PASS on 24 files; MyPy PASS on 13 source files; 339 unit/contract tests PASS at 87% coverage with sockets disabled |
| Dependency and lock authorization | DONE | Only approved direct pins `httpx==0.28.1` and `defusedxml==0.7.1` were added; Tenacity was not added; dependency-boundary tests PASS |
| Dependency evidence | DONE | 50 external packages reconciled; 50 declared licenses; zero known vulnerabilities, skipped packages, or exceptions; manifest SHA-256 `9895b6c8f7e96fb89452cd459d7a0e13d80eca5a0c8d32325ee1b55a8c943c4c`; candidate identity `sha256:d503b8960603a605ae88ad50465048ee2dfc21cac733530407b8b80872b76e67` |
| Four bounded remediation cycles | DONE | Three original cycles plus the explicitly Owner-authorized B-017 cycle were fixed and retested without dependency, public-contract, or allowlist changes |
| Independent code review | DONE | Exact-hash final re-review PASS; no P0/P1/P2 blocker |
| Independent test-gap review | DONE | Exact-hash final re-review PASS; 49 cycle-3 regressions, 23 Owner-minimum cases, and 176 focused cases passed |
| Prior independent terminal evidence audit | DONE | Correctly blocked the pre-remediation candidate on B-017 and prevented staging/commit |
| B-017 fourth-cycle readiness | DONE | Original reproduction rejects invalid UTF-8; policy and full `MockTransport` regressions prove `%FF` is not followed and only one request occurs |
| Repeated independent terminal security audit | DONE | Exact six-path fourth-cycle hashes and 19-path M1A-002 scope verified; semantic malformed/equivalence matrices, focused 178, full 339, Ruff, format, MyPy, lock, manifest, and phase audit PASS; no P0/P1/P2 finding |
| Prior evidence-only terminal rebind | DONE | Correctly found B-018: P4 and the latest handoff claimed completion before the exact commit and clean-tree conditions existed |
| B-018 evidence-state correction | DONE | P4 is limited to the completed pre-commit evidence gate; the handoff is `READY_TO_COMMIT` and does not claim a commit, final SHA, clean worktree, full completion, or final handoff |
| Current pre-commit decision | READY_TO_COMMIT | An independent read-only rebind of the full 19-path candidate is required immediately before any authorized staging |
| Offline and Git boundary | DONE | All source behavior used `httpx.MockTransport`; default suite used `--disable-socket`; no live PubMed/NCBI request and no remote Git operation occurred |
| Scope, secrets, and status documentation | DONE | No later M1A implementation, live response, credential, secret, cache, or temporary evidence artifact is included; README, interview notes, SPEC, and STATE describe the implemented boundary |

Final exact implementation bindings:

```text
client.py:          02c0918e6f5b651d8076bfeeffcb846dd0e64e1e13dfdee9249925558ee8485c
parsing.py:         874a065eb7d252d75d9209ee8fe47c07bf69c9f62e89e523ba9ee9e0e6991a5b
policy.py:          7845ce7fe89219d9c3feebee526ee3cc87b1da4689807a7db088ddc73f8d486f
contract tests:     4649841297fa2187a852225de8193416033770a9541780c41b65ea3c69f02049
parser tests:       de98a57ec4d843fd6c5ef0e3280a8989418e7893658e48a8b5b80b9270ed96cd
policy tests:       4b64f4a5b703c5fe974b704feaa7de90b5f80c94b48dae9881795a8e96864bd0
boundary tests:     06206b351f2504dcd9b5c82e63a0e563da1e4a49df8b2dfb675ef9ecd084a4a2
pyproject.toml:     b88680e7039cbb8a34ef7252f646601e18b850e50bb5d6f5a6bc7a3e2d27cd21
uv.lock:            61ab80e26f7a7567c8072f774707a0ef62196dbddeadde586368bbe9d4f90eb3
```

The advisory audit evidence is outside Git at
`C:\Users\BoqiNiu\AppData\Local\Temp\medevidence-m1a002-b017-final-deps-20260805-192510062`.
It contacted only the PyPI advisory service; it did not contact PubMed or any
NCBI API endpoint.

## B-017 resolution

`resolve_pubmed_redirect` now validates every percent escape in each form-style
query component, percent-decodes to bytes, and decodes with strict UTF-8 before
comparing the multiplicity-preserving pair collections. It does not normalize,
case-fold, or replacement-decode values.

The exact `%EF%BF%BD` versus `%FF` policy regression raises `ValueError`. The
full `httpx.MockTransport` regression returns `REDIRECT_REJECTED`, records one
request, and proves the redirect was not followed. A non-persistent boundary
smoke also rejected malformed `%`, `%G0`, and overlong `%C0%AF` while retaining
the existing acceptance of valid query-pair reordering.

## B-018 correction

B-018 was limited to terminal evidence semantics: the ledger had marked the
commit work and handoff complete while HEAD still identified M1A-001B, all 19
M1A-002 paths remained uncommitted, and the Git index was empty. The corrected
model treats P4 as the completed pre-commit evidence gate and reports
`READY_TO_COMMIT`. It does not assert that staging, commit creation, a final
commit identity, post-commit verification, full work-item completion, or the
final handoff has occurred.

The source, tests, dependency evidence, and B-017 terminal security PASS remain
unchanged. The Owner-authorized next gate is an independent read-only rebind of
the exact 19-path candidate. Staging and the single local M1A-002 commit are
permitted only if that rebind returns PASS.
