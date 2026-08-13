# M2-001 real benchmark independent review 001

Date: 2026-08-13

Candidate baseline: `ab15c55fbf9cee897a961905944ffee232a03372` plus the
uncommitted M2 candidate diff reviewed in the isolated worktree.

Decision: **FAIL — P0 0 / P1 4 / P2 3**

Status: one Owner-authorized batched remediation is in progress. This record is
immutable review evidence; remediation does not rewrite the original decision.

## Findings

1. **P1 — execution source was not reproducibly bound.** The manifest recorded
   HEAD but the benchmark ran from a dirty worktree, without an exact patch or
   tracked/untracked source inventory.
2. **P1 — clean bootstrap and CI omitted the retrieval dependency group.** The
   harness required NumPy/scikit-learn although the authoritative bootstrap
   synchronized only the development group.
3. **P1 — final evidence was not deliverable.** All generated results were
   ignored, so the exact final per-query evidence and manifest could not be
   reviewed or committed without an explicit narrow path.
4. **P1 — empty/non-evaluable qrel states were not uniformly rejected.** Missing
   JSON qrels, empty qrel maps, empty per-query maps, or zero evaluated queries
   could reach unsafe states.
5. **P2 — dependency boundaries/evidence did not assert the exact retrieval
   pins and their absence from production defaults.**
6. **P2 — concurrency and timing semantics were incomplete.** Query concurrency
   and BLAS/thread policy were unstated, and hybrid build time was not
   distinguished as a derived sum of measured sparse/dense builds.
7. **P2 — saved rankings were insufficient to reconstruct fusion.** Only final
   top-ten component details were retained; ModeResult coverage/uniqueness and
   summaries were not revalidated immediately before saving.

## Required remediation and disposition

The Owner authorized exactly one mechanical batch covering all seven findings,
followed by a real benchmark rerun. The remediation must preserve the algorithms,
configuration, NFCorpus bytes, and the immutable ignored run-001 evidence. A
fresh post-remediation review and terminal audit remain required; this review
does not constitute their PASS.

---

# M2-001 real benchmark independent review 002

Date: 2026-08-13

Decision: **PASS — P0 0 / P1 0 / P2 0**

Status: `REVIEW002_PASS_AWAITING_TERMINAL_AUDIT`.

Review002 examined branch `feat/m2-retrieval-eval-codex` at HEAD
`ab15c55fbf9cee897a961905944ffee232a03372`. The execution source-state identity
is `fb87bea9a8cd271a58b1d790a455cc241973d0c0178f5b924bbcadd3c97fa884`;
its tracked patch is 133,064 bytes with SHA-256
`2604ad49876d5662c23dd582243a87b60d12d41045e947ba3731675141d8f754`.
No separate candidate path-manifest was supplied or claimed.

The authoritative review candidate is
`evaluation/results/nfcorpus-real-thread1-final/`. Its manifest is 19,030
bytes with SHA-256
`a9ef3cdeaf42c54921ae07c6b8fc9f872381132aad43926e33f8ba377d583356`;
the 80-byte sidecar has SHA-256
`0747afb3007f5aa1ecf2f3f1bab558daa6c3f48760a342fc5359c08ae3059a80`.
Review recomputation matched all named output identities and saved metrics.
The remaining identities were: dense JSONL 2,752,034 bytes,
`73fa318fac69123a0afdad6b1565ab77da4306830c29b9d1293f70303a261cc4`;
hybrid JSONL 3,852,273 bytes,
`2d867c9317f585418554000a72fc2b3b81a5f0b71410b7d94736c54e703973a5`;
sparse JSONL 1,899,202 bytes,
`fa7891b2c4f96cddbd6e3b9a9741fc8f69e63f03d952a28ad8dd6f36852a07d0`;
source-state JSON 2,886 bytes,
`52a70e6aaf1fbc3eb1a6d3bea9f23cebabb84719bf0bc941ceda137349401b3d`;
and untracked snapshot 11,488,052 bytes,
`fdead70a75a990f9d1dfe76f8f0e24275df0e5b1479b55f5a9b5013fdedc7333`.

Review002 verified closure of Review001's seven finding classes. Every captured
BLAS/OpenMP pool reported exactly one thread at entry and exit for index build
and sparse, dense, and hybrid query-latency contexts; the five required thread
environment variables were `1`.

Fresh gates were 132 focused tests passed; 1,650 full offline unit/contract
tests passed with two expected warnings and 80% coverage; Ruff lint and format,
strict MyPy, lock validation, PowerShell parsing, and diff checks passed.

Review002 performed no network or medical-source request, benchmark rerun, Git
stage, commit, push, merge, rebase, reset, clean, or history rewrite. Terminal
Audit001 remains immutable historical **FAIL — P0 0 / P1 1 / P2 0**, and the
earlier 24-thread run remains diagnostic evidence only. A fresh terminal audit
is still required; Review002 does not authorize an M2 completion marker,
transformer readiness, or a commit.

---

# M2-001 real benchmark terminal evidence audit 002

Date: 2026-08-13

Decision: **PASS — P0 0 / P1 0 / P2 0**

Status: `M2_001_REAL_BENCHMARK_COMPLETE` and
`READY_FOR_M2_TRANSFORMER_BASELINE`.

Audit002 examined the exact pre-persistence candidate on branch
`feat/m2-retrieval-eval-codex` at HEAD
`ab15c55fbf9cee897a961905944ffee232a03372`: 33 changed/untracked paths with a
3,854-byte canonical path manifest whose SHA-256 was
`8f5a8b355e0681c1782b26aa3d881d687f8f88db4753f7722bd13f448564bb6b`.
The canonical manifest used Ordinal UTF-8 path sorting and
`path<TAB>bytes<TAB>lowercase-sha256<LF>` records encoded as UTF-8 without BOM
with LF termination.

Audit002 reverified execution source-state
`fb87bea9a8cd271a58b1d790a455cc241973d0c0178f5b924bbcadd3c97fa884`,
the 133,064-byte tracked patch with SHA-256
`2604ad49876d5662c23dd582243a87b60d12d41045e947ba3731675141d8f754`,
and the eight immutable files under
`evaluation/results/nfcorpus-real-thread1-final/`. The 19,030-byte manifest
SHA-256 was
`a9ef3cdeaf42c54921ae07c6b8fc9f872381132aad43926e33f8ba377d583356`;
its 80-byte sidecar SHA-256 was
`0747afb3007f5aa1ecf2f3f1bab558daa6c3f48760a342fc5359c08ae3059a80`.
All six manifest-listed output identities rehashed exactly.

The exact NFCorpus distribution, corpus, queries, qrels, counts, configuration,
rankings, metrics, and measured-versus-derived timing evidence matched the
manifest and Review002. All five native-thread environment variables were `1`;
every discovered and in-context BLAS/OpenMP pool reported one thread at build
and sparse, dense, and hybrid entry/exit boundaries. Python `3.12.13`, NumPy
`2.5.1`, scikit-learn `1.9.0`, Windows platform provenance, and the 108,274-byte
`uv.lock` SHA-256
`26603561a612b39cb900d2472fe7933d1e600fefd78a54f767472c3f467d26f4`
were recorded.

Fresh evidence remained 132 focused tests passed and 1,650 full offline
unit/contract tests passed with two expected warnings and 80% coverage; Ruff,
format, strict MyPy, lock, PowerShell parsing, diff, source, scope, artifact,
metric-recomputation, and no-network checks passed. Audit002 performed no
network or medical-source request, benchmark rerun, Git stage, commit, push,
merge, rebase, reset, clean, or history rewrite.

Historical Review001, Audit001, and Review002 remain unchanged above. Audit002
authorizes the two M2 evidence-status markers only. No commit was authorized or
performed. `ME-000C` remains open for release indexes, Qdrant, transformer
dense retrieval, rerankers, and later retrieval architecture. No M3 work was
authorized or started.
