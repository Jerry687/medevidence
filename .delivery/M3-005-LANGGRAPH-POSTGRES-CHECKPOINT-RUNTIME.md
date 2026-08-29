# M3-005 LangGraph PostgreSQL checkpoint runtime

## Status

`AWAITING_TERMINAL_AUDIT`

This delivery record rebinds the current uncommitted Round-11 exact bytes to
the Owner-approved work item. Round-11 independent review returned
`PASS — P0 0 / P1 0 / P2 0`, and every required supervisor gate has fresh
passing evidence. Terminal audit remains pending, so this update does not
claim the overall terminal PASS, commit, push, pull request, CI, merge, or
post-merge verification.

## Authorization and baseline

- Work item: `M3-005-LANGGRAPH-POSTGRES-CHECKPOINT-RUNTIME`
- Owner authorization: `OWNER FULL M3 RUNTIME AUTHORIZATION - V1`
- Accepted: 2026-08-28
- Authorization SHA-256:
  `e6b812f6411b8e8a62a559ae0182b45cae25bc70d0173c135b94e97b8cd73fa8`
- Exact baseline and current uncommitted `HEAD`:
  `b29c2b5805dbb3d6be251cac2480f050f81928b7`
- Branch: `codex/m3-005-langgraph-postgres-checkpoint-runtime`
- Worktree: `D:\Projects\medevidence-wt-m3-005`
- Original remediation budget: 10 batched rounds for this work item
- Exceptional final authorization: exactly one Owner-approved Round `11/11`,
  limited to the PostgreSQL integration-test assertion correction; no Round 12
  is authorized
- Git lifecycle after terminal PASS: local commit, push, draft PR, CI, ready,
  merge, post-merge verification, and control-plane reconciliation are
  authorized

The unrelated canonical local modification `evaluation/metrics.py` is outside
this worktree and was not reset, cleaned, stashed, read for implementation, or
modified.

## Objective and frozen boundary

Implement only the accepted LangGraph coordination and PostgreSQL checkpoint
infrastructure for the already-existing M3 application workflow:

1. `scope_and_safety`
2. `plan_sources`
3. `collect_evidence`
4. `synthesize_claims`
5. `validate_report`
6. `save_pending_draft`
7. `request_export_approval`
8. `finalize_and_export`

The graph coordinates stable application capabilities and owns no connector,
source parsing, retrieval, qrels/evaluation, citation-policy,
validation-receipt, or export-persistence rules. This work item changes no
contract/workflow model, application persistence model or migration, public
API/OpenAPI, source/provider behavior, or export lifecycle. M3-006 and later
work items remain deferred.

## Exact path allowlist

Only these 15 repository paths are authorized:

1. `pyproject.toml`
2. `uv.lock`
3. `scripts/dependency-audit.ps1`
4. `tests/unit/test_dependency_boundaries.py`
5. `src/medevidence/orchestration/langgraph_runtime.py`
6. `src/medevidence/orchestration/__init__.py`
7. `src/medevidence/infrastructure/langgraph_checkpoint.py`
8. `src/medevidence/infrastructure/__init__.py`
9. `tests/unit/orchestration/test_langgraph_runtime.py`
10. `tests/unit/infrastructure/test_langgraph_checkpoint.py`
11. `tests/integration/infrastructure/test_langgraph_postgres_checkpoint.py`
12. `docs/decisions/ADR-017-langgraph-postgres-checkpoint-runtime.md`
13. `docs/decisions/README.md`
14. `docs/TRACEABILITY_MATRIX.md`
15. `.delivery/M3-005-LANGGRAPH-POSTGRES-CHECKPOINT-RUNTIME.md`

No sixteenth total path is authorized.

## Engineering graph and ownership

| Node | Dependency | Objective | Single-writer paths | Evidence and stop condition | Result |
|---|---|---|---|---|---|
| D0 preflight/discovery | Owner authorization | Verify exact baseline, worktree isolation, applicable policies, and dependency/runtime entry points | None | Stop on ambiguous Git state, missing authority, or required boundary expansion | Complete; exact baseline and clean isolated starting state verified |
| D1 dependency governance | D0 | Resolve and lock only the two exact approved direct packages; inspect metadata, license, hashes, transitive graph, advisories, and exact repository governance reconciliation | `pyproject.toml`, `uv.lock`, `scripts/dependency-audit.ps1`, `tests/unit/test_dependency_boundaries.py` | Stop rather than substitute versions on Python 3.12.13 | Complete; baseline 86 to current 107 identities: 21 new names plus the sole pip security upgrade; both direct pins unchanged |
| D2 application runtime | D0, D1 interface knowledge | Implement the exact eight-node graph, fixed identity/namespace, primitive reconstruction, one interrupt, and terminal verification | orchestration runtime/init and its unit test | Stop on application-contract or workflow-semantic change | Complete after rounds 1, 6, and 7; current focused join `214 passed` |
| D3 checkpoint infrastructure | D1, D2 fixed namespace | Implement strict serializer and isolated official PostgreSQL saver lifecycle | infrastructure runtime/init, unit test, and PostgreSQL integration test | Stop on application Alembic, business-table access, or extra service need | Complete; official local PostgreSQL 18.4 primitive and real-runtime tests `2 passed in 1.58s`, container removed |
| D4 governance/evidence | D1-D3 exact bytes | Record ADR, traceability, scope, evidence, review history, and pending gates | ADR-017, ADR index, traceability matrix, this delivery | No overall PASS claim before terminal audit | Complete through Round 11; immutable earlier failures preserved and current exact bytes rebound here |
| V supervisor validation | D1-D4 join | Run focused, full offline, static, lock, scope, secret, dependency, and exact-byte gates | None | Mechanical failures enter only an authorized remediation round | Complete on current bytes: PostgreSQL `2 passed`, full offline `2559 passed` at `82%`, Ruff/format/strict MyPy/lock/diff/scope/secret/dependency PASS |
| R independent review | V | Review actual diff and executable reachability, including restored-checkpoint trust boundary | None | Same-scope findings are remediated only while an authorized round remains | Round-11 fresh verdict `PASS — P0 0 / P1 0 / P2 0`; all earlier FAIL verdicts remain immutable below |
| B exact-byte rebind | R PASS | Rehash every exact candidate path and preserve test/audit identities | Delivery record only if evidence recording requires it | Any byte change invalidates the preceding binding | Complete except this self-referential delivery hash, emitted by the rebind handoff after write |
| A terminal evidence audit | B | Independently decide `PASS`, `FAIL`, `BLOCKED`, or `OWNER_DECISION_REQUIRED` | None | No Git integration without terminal PASS | Pending |
| G Git lifecycle | A PASS | Stage exact audited paths, commit, push, PR, CI, merge, and verify integrated bytes | Exact audited paths only | Stop on non-mechanical CI or boundary expansion | Pending and not yet executed |

## Dependency decision and evidence

### Direct pins

- `langgraph==1.2.11`
- `langgraph-checkpoint-postgres==3.1.2`

Both exact packages declare Python `>=3.10`, which includes the repository's
Python 3.12.13 runtime, and `License-Expression: MIT`. Exact locked artifact
hashes are:

| Package | Wheel SHA-256 | sdist SHA-256 |
|---|---|---|
| `langgraph==1.2.11` | `8bab70de7b2d00b5300fb289bcf38d8b241400f3184c1e95e8ce706fb0e8686b` | `9ecfe11e50d338b34b15cf4d8a442642de103e8ae6971320efba84e4542eb363` |
| `langgraph-checkpoint-postgres==3.1.2` | `6a7e38ef16985b54e356cba7bdaf447943aae33d5aaf290026c593bb6b4a6264` | `1cd404803ff895a2b79f3ac04ce92b775e6b999715f8333fce674c6d927bba95` |

Official primary sources consulted by D1 under the Owner's exact dependency
network authorization:

- `https://pypi.org/pypi/langgraph/1.2.11/json`
- `https://pypi.org/pypi/langgraph-checkpoint-postgres/3.1.2/json`
- `https://pypi.org/pypi/langgraph-checkpoint/4.2.0/json`
- `https://docs.langchain.com/oss/python/langgraph/persistence`
- `https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-postgres`

The baseline lock contains 86 governed third-party identities. The current
lock contains 107 plus the local project entry. Of those 107 identities, 106
are active on the target and the sole inactive marker is `torch==2.13.0`.
Relative to baseline, the lock adds exactly 21 new package names, removes none,
and upgrades one existing dev-tool identity:

```text
distro==1.9.0
jsonpatch==1.33
jsonpointer==3.1.1
langchain-core==1.6.1
langchain-protocol==0.0.19
langgraph==1.2.11
langgraph-checkpoint==4.2.0
langgraph-checkpoint-postgres==3.1.2
langgraph-prebuilt==1.1.0
langgraph-sdk==0.4.4
langsmith==0.11.2
orjson==3.12.0
ormsgpack==1.12.2
psycopg-pool==3.3.1
requests-toolbelt==1.0.0
sniffio==1.3.1
tenacity==9.1.4
uuid-utils==0.17.0
websockets==16.1.1
xxhash==4.0.1
zstandard==0.25.0
```

The sole upgrade is `pip==26.1.2` to `pip==26.2.1`, required to close
`PYSEC-2026-3721` / `CVE-2026-13346` with fixed floor `26.2`. Its current wheel
SHA-256 is
`71138adf1f4ca900cdb7d289c21b7494329f2332b6d85f0e1c42108c0384ed3e`
and sdist SHA-256 is
`f6ad667e89a1fe78046c8f13232b247200f5258d7828f3f7883d660878e0813f`.
This dev-tool security correction does not alter either Owner-approved direct
runtime pin.

`langchain-core==1.6.1` is a package-owned transitive dependency required by
LangGraph; it is not a direct MedEvidence dependency. No direct LangChain,
Redis, OpenAI SDK, model, provider, or extra infrastructure package was added.
The existing synchronous `psycopg[binary]==3.3.4` direct pin was reused.

The initial runtime-only preflight inspected 49 installed production packages
and reported zero vulnerabilities and zero fixes. That immutable early evidence
preceded full lock governance and is not the final candidate audit. Its
supporting identities were:

- `pip-audit.json` SHA-256:
  `c85664fd1674d0425a565c8b9890bcab9c7ff7b029830f8a9a38a7e8d73c1991`
- locked production export SHA-256:
  `57c2d3a10155957b9106e2c6dbe7933d071f0e16dbbadb5df5bc6fb9332e4f06`
- exact `langgraph` PyPI JSON SHA-256:
  `850c84cc877c90ffe8003bd043aed799339964ee28e325ba845dd1be3fd0ebaa`
- exact `langgraph-checkpoint-postgres` PyPI JSON SHA-256:
  `234b49dfd9744aef8aae10d702b41f051f1daedf8c85084d2ec7c9ae3cd5fba4`
- exact `langgraph-checkpoint` PyPI JSON SHA-256:
  `5a53728b5637b8e65e1ef4c51e10cf832da4b9abc9931320a9378cc59cd84d65`

The evidence directories are temporary local supporting material, not
repository paths or integration artifacts.

The immutable post-round-7, pre-round-8 dependency evidence accounted for all
107 governed identities: `105` ordinary pip-audit PASS dispositions, one exact
public-version OSV fallback for the active torch CPU identity, and one inactive
torch marker. It reported no known vulnerability and no approved exception.
Those historical bindings, which do not bind the current document bytes, are:

- candidate file-set identity:
  `e6bc801d1a17a36aa5606732934516d7d1c3cc933e2c1dd25ce7001d90d1c1cd`;
- passing evidence-manifest SHA-256:
  `4ebc8d131ca6b6e66f8594189f6502c8a016d81df160ea9afcbfacbe9d9cb658`;
- dependency-audit script SHA-256:
  `9bcec0ad385c41d51dc0ce6356f241f5fc0594a0fbd585498ba7bc1bb8e71c64`.

The round-9 external Audit was generated only after all dependency-
audit candidate paths froze. It passed with 107 governed identities and
`advisory_status=passed_no_known_vulnerabilities`. Because this delivery file
is excluded from `candidatePaths`, recording these values here does not alter
the audited candidate identity:

- audit directory:
  `C:/Users/BoqiNiu/AppData/Local/Temp/medevidence-m3-005-r9-final-candidate-audit-4739db7e53054c0e890c5851a03e7f9a`;
- current candidate file-set SHA-256:
  `f36b0e2ffcfe82529cca42bccb90b2d84c0fea6673164dbc7f3e27f35cac8835`;
- current evidence-manifest SHA-256:
  `27aded0ce779c201ac01c5895dc1252a3a84f439ae31ce7b40958e54359ab727`.

Round 11 changes only the integration test and this delivery record, both of
which are excluded from the dependency-audit script's 75 `candidatePaths`.
Recomputation therefore preserves the current dependency candidate identity
and evidence-manifest binding above.

### Immutable dependency-probe history

Two non-candidate probe failures are preserved rather than rewritten:

1. The first throwaway `uv init --bare` inherited the host default and wrote
   `project.requires-python = ">=3.13"`. The subsequent
   `uv add --python 3.12.13` stopped before package resolution because the
   requested Python 3.12.13 interpreter was incompatible with that temporary
   `>=3.13` project. A new throwaway resolver created with
   `uv init --python 3.12.13` resolved the exact approved packages. Neither
   failed probe changed candidate bytes or established a package failure.
2. The authorized official-wheel loop downloaded, SHA-verified, and extracted
   all three inspected wheels. Its final display expression omitted a space,
   so PowerShell reported `Get-Item$wheel: The term 'Get-Item$wheel' is not
   recognized` three times. A read-only reprint confirmed the already-
   downloaded exact files and hashes; no repeated download or candidate change
   occurred.

## Implemented runtime behavior

### Closed application composition

`LangGraphOrchestrationRuntime` privately compiles one exact graph. Callers do
not receive the compiled graph and cannot supply a LangGraph
`RunnableConfig`. `start` accepts an exact `OrchestrationState`; `inspect` and
`resume` accept only a validated `run_id`. The runtime derives
`thread_id = run_id`, fixes `checkpoint_ns` to
`m3.orchestration-state.v2`, and rejects an existing checkpoint on a new-start
path.

The graph uses exactly one `interrupt_before`, for
`request_export_approval`. It defines no graph-level retry policy. Existing
application capabilities retain source-attempt, validation, pending-draft,
approval, finalization, idempotency, and terminal-state authority.

### Untrusted checkpoint reconstruction

The checkpoint envelope admits only exact dictionaries/lists and primitive
`None`, exact `bool`/`int`, finite `float`, and exact strings. It bounds
canonical bytes, depth, node count, container cardinality, and string bytes;
rejects cycles and non-string keys; canonicalizes JSON; and strictly
reconstructs `OrchestrationState`. Every node route and stored result then
invokes the existing complete durable-state/topology validation before any
application capability or trusted return.

The stored run ID, fixed namespace, scheduler topology, and terminal topology
are rebound. Terminal state is passed through application `run_next` and must
return unchanged. No checkpoint field proves Stage-2 completion. The
independently persisted ADR-016 `M3_VALIDATION_RECEIPT_V1` remains the sole
canonical report-validation authority.

### Strict PostgreSQL checkpoint infrastructure

The serializer is exact `JsonPlusSerializer` with:

- `pickle_fallback=False`
- `allowed_json_modules=None`
- `allowed_msgpack_modules=None`

The synchronous `psycopg` connection is autocommit, uses
`prepare_threshold=0`, and sets `search_path` to
`medevidence_langgraph_checkpoint_v1, public`. Official unqualified
`PostgresSaver.setup()` owns exactly these infrastructure tables in that
isolated schema:

- `checkpoint_migrations`
- `checkpoints`
- `checkpoint_blobs`
- `checkpoint_writes`

No application Alembic migration manages them. Domain/application code does
not query them or treat them as business evidence. The integration test alone
inspects catalogs and rows to prove isolation, official migration sequence,
same-run close/reopen resume, fixed namespace, cross-run rejection, and no
application schema/data mutation.

## Exact current byte identities

The following SHA-256 values bind every current non-document changed path plus
the unchanged allowlisted orchestration package root. Round 8 changes only the
four document paths; their final identities are recorded after those bytes are
written and must be included in the fresh review manifest.

| Node | Path | SHA-256 |
|---|---|---|
| D1 | `pyproject.toml` | `4de759265e4822146b765d60b859f132141602338805c2afafc95a18c19ac969` |
| D1 | `uv.lock` | `7746f0cde9404476cea86b7bbb2bc9269afeb12c8458cb007291c73a1a3d8e19` |
| D1 | `scripts/dependency-audit.ps1` | `9bcec0ad385c41d51dc0ce6356f241f5fc0594a0fbd585498ba7bc1bb8e71c64` |
| D1 | `tests/unit/test_dependency_boundaries.py` | `d331c9824a5e10950cf95277b97216a214bb7a11fe50c8ecffca9a705abf8895` |
| D2 | `src/medevidence/orchestration/langgraph_runtime.py` | `16301b53889ae4e0c860ddcc22d668d3ee2fac2de0272830ed3cfa91c1a3835c` |
| baseline unchanged | `src/medevidence/orchestration/__init__.py` | file SHA-256 `4ff1748662bc631981b97511845809aa693d77de7bd64529c91cd4d254c8898c`; Git blob `6f4e683c15f507a5138d783f5da26ddc9b60ccd9` |
| D2 | `tests/unit/orchestration/test_langgraph_runtime.py` | `b320f90ec4a4d4ae497b682318f7375037a9357f419ec4732efbb35b0e849fa8` |
| D3 | `src/medevidence/infrastructure/langgraph_checkpoint.py` | `ceb9d091a75503bf24f7a384044cc9a7b1da6acf76639275fc99cbf636a54693` |
| D3 | `src/medevidence/infrastructure/__init__.py` | `bf278f7cff2810695d5184d6a007153c2430234fe7bc8e3738118eafdc3eb15e` |
| D3 | `tests/unit/infrastructure/test_langgraph_checkpoint.py` | `4647bafca1f008d8b8b101f57c1bf6ac412752d8aeb8426e1edb8243488d01d4` |
| D3 | `tests/integration/infrastructure/test_langgraph_postgres_checkpoint.py` | `6f8055e6294bdc137f8975904294cd574fa665b5f6104c9e562bb8bf1cacf79c` |
| D4 | `docs/decisions/ADR-017-langgraph-postgres-checkpoint-runtime.md` | `6477333c2a56f03ae6193d1aca1267ae849a972a15468ce34909ff7762384744` |
| D4 | `docs/decisions/README.md` | `afe1a389d4614549ea4b454d632ba0a13915c2e8bf64eec61647133d23e4bf86` |
| D4 | `docs/TRACEABILITY_MATRIX.md` | `827428d79107164f66798f5359b368c5407320dd935284efdc7f3fd1c73ba5c6` |

The pre-Round-11 integration-test identity was
`68eeb99fd7d085ee5b818e5903ed616cfc36c0b1e201930d81d5d3a4302062f8`.
An implementer handoff inherited the older identity
`8e0eaee397c4280749d3ff45bead86a80acaa5fcdee19995dc011946bed7b6b1`;
that stale claim is preserved as non-authoritative history and excluded from
current provenance. The runtime remained unchanged at
`16301b53889ae4e0c860ddcc22d668d3ee2fac2de0272830ed3cfa91c1a3835c`.

This delivery file cannot embed its own final SHA-256 without changing that
same identity. Its final hash is therefore emitted by the rebind handoff and
must be the fourteenth changed-path entry in the terminal-audit manifest.

## Validation evidence to date

### Current exact executable candidate and dependency binding

- official local PostgreSQL 18.4 primitive and real-runtime selection:
  `2 passed in 1.58s`;
- full socket-disabled unit/contract suite: `2559 passed`, repository coverage
  `82%`;
- repository Ruff, format, strict MyPy, offline lock, exact 14-of-15 scope,
  diff, bounded secret, and dependency gates: PASS;
- round-9 external dependency Audit: PASS, 107 identities,
  `advisory_status=passed_no_known_vulnerabilities`;
- current dependency candidate identity:
  `f36b0e2ffcfe82529cca42bccb90b2d84c0fea6673164dbc7f3e27f35cac8835`;
- current evidence-manifest SHA-256:
  `27aded0ce779c201ac01c5895dc1252a3a84f439ae31ce7b40958e54359ab727`;
- immutable post-round-7, pre-round-8 dependency candidate identity:
  `e6bc801d1a17a36aa5606732934516d7d1c3cc933e2c1dd25ce7001d90d1c1cd`;
- immutable post-round-7, pre-round-8 passing evidence-manifest SHA-256:
  `4ebc8d131ca6b6e66f8594189f6502c8a016d81df160ea9afcbfacbe9d9cb658`;
- Round-11 fresh independent review:
  `PASS — P0 0 / P1 0 / P2 0`; and
- exact runtime SHA-256 remained
  `16301b53889ae4e0c860ddcc22d668d3ee2fac2de0272830ed3cfa91c1a3835c`
  while the integration-test-only correction moved from
  `68eeb99fd7d085ee5b818e5903ed616cfc36c0b1e201930d81d5d3a4302062f8`
  to
  `6f8055e6294bdc137f8975904294cd574fa665b5f6104c9e562bb8bf1cacf79c`.

### Earlier node-local and joined evidence

The following results remain immutable historical evidence and are not
substitutes for the current gates:

- D2 focused orchestration selection: `156 passed`;
- D3 unit infrastructure selection: `13 passed`;
- D1 dependency-governance unit selection: `94 passed`;
- parent integrated runtime, infrastructure, and existing workflow selection:
  `153 passed`;
- D4 re-execution of the two exact new unit files with socket disabled:
  `41 passed in 1.10s` before the later import-only compactness remediation;
- D4 fresh post-remediation dependency-boundary plus both new unit files with
  socket disabled: `135 passed in 1.91s`;
- earlier primitive fixed-namespace disposable PostgreSQL integration:
  `1 passed`;
- dependency resolution: 107 governed third-party identities, 106 active,
  21 new package names, one pip security upgrade, and zero removals;
- dependency-governance reconciliation tests: fallback branch exactly
  `105 pip-audit PASS + 1 exact public-version OSV fallback for the active
  torch CPU identity + 1 inactive torch marker = 107`; no-fallback branch
  exactly `106 pip-audit PASS + 1 inactive torch marker = 107`;
- production `pip-audit`: 49 packages, zero vulnerabilities, zero fixes; and
- all completed node-local Ruff/format/type checks reported PASS within their
  owned scopes.

### Immutable PostgreSQL test/infrastructure probe history

1. The first Docker Desktop start tried the default
   `C:\Program Files\Docker\Docker\Docker Desktop.exe` and failed before a
   process started because that executable was absent. A read-only registry
   lookup resolved the user-local installation; hidden startup then succeeded.
2. The first actual PostgreSQL integration compiled a minimal root graph
   directly with raw `PostgresSaver` but queried the frozen application
   namespace. LangGraph correctly stored a root graph in the empty namespace,
   so that fixture failed. The test was corrected to validate D2's actual
   `_FixedNamespaceSaver` composition. The next actual disposable PostgreSQL
   run passed `1/1`.

The earlier database run used PostgreSQL 18.4 from the already-local image
identity `1961f96e6029` and an ephemeral loopback port. Both earlier disposable
containers were removed and no pull occurred. Neither probe failure was an
implementation-review finding or a candidate PASS.

After the Owner restarted Docker Desktop, the primitive test passed and the
real eight-node test reached one erroneous test-only event assertion. The
runtime correctly performed complete terminal binding verification by loading
the exact pending draft and validation receipt before both terminal `inspect`
and idempotent terminal `resume`. The then-current test incorrectly prohibited
those required read-only loads. Persistence, approval, export, source, and all
other side-effecting capabilities still ran exactly once.

Owner-authorized Round 11 corrected only that assertion. The final disposable
run used the already-local official PostgreSQL 18.4 image
`sha256:1961f96e6029`, an ephemeral loopback port, and no image pull. Both
primitive and real eight-node close/reopen/resume tests passed:
`2 passed in 1.58s`. The disposable container was removed after the run.

### Supervisor validation finding and remediation round 1/10

The first integrated full offline suite found one mechanical legacy
compactness failure: the two frozen production modules totaled `1806` lines,
exceeding the existing `1800` ceiling solely because
`orchestration/__init__.py` exposed eight new package-root import/export lines.
This is an immutable supervisor-validation failure, not an independent-review
finding and not a semantic defect in the graph.

Authorized remediation round 1/10 removed the unnecessary package-root
exports, restored `orchestration/__init__.py` exactly to its baseline Git blob
`6f4e683c15f507a5138d783f5da26ddc9b60ccd9`, and changed the runtime unit test
to import the new symbols directly from `langgraph_runtime`. No public contract
or runtime behavior changed. The exact compactness total is now `1798 / 1800`;
the correction-node focused suite passed `29`, Ruff passed, format passed, and
`git diff --check` passed. The complete supervisor validation sequence must be
rerun on these corrected bytes before review.

### Supervisor dependency findings and remediation rounds 2-5/10

- Round 2 preserved a final dependency-Audit validation failure: the original
  conservative SPDX grammar rejected orjson's valid parenthesized expression.
  The closure is a bounded exact parser for approved IDs, parentheses,
  `AND`/`OR`, and the sole approved `WITH` form, with length/token/nesting
  bounds and malformed/injection-like negatives.
- Round 3 preserved the next Inventory validation failure: multiple exact
  license classifiers were rejected even when an exact SPDX expression covered
  the same approved license-ID set. The closure accepts only complete known-
  classifier coverage equal to the parsed exact expression; partial, extra,
  unknown, or contradictory classifiers fail closed.
- Round 4 preserved the next Inventory validation failure: exact sniffio 1.3.1
  legacy metadata has no `License-Expression` and has both Apache and MIT
  classifiers. The closure is release-specific and binds its legacy
  expression, exact classifier tuple, installed version, and SHA-256 of
  `LICENSE`, `LICENSE.APACHE2`, `LICENSE.MIT`, `METADATA`, and `RECORD`.
  Missing, substituted, or drifted artifact evidence fails closed.
- Round 5 preserved the fresh advisory validation failure for baseline
  `pip==26.1.2`: `PYSEC-2026-3721` / `CVE-2026-13346`, fixed in `>=26.2`.
  Only the dev-tool lock identity moved to `pip==26.2.1`; the 21 new package
  names and both Owner-frozen direct pins remained unchanged.

These were supervisor-validation findings, not independent-review verdicts.
The immutable post-round-7, pre-round-8 full dependency audit accounted for
107 identities, reported no known vulnerability or approved exception, and
bound candidate identity
`e6bc801d1a17a36aa5606732934516d7d1c3cc933e2c1dd25ce7001d90d1c1cd`
to evidence manifest
`4ebc8d131ca6b6e66f8594189f6502c8a016d81df160ea9afcbfacbe9d9cb658`.

### Independent Review round 6/10 — immutable FAIL

The initial independent verdict remains:

`FAIL — P0 0 / P1 3 / P2 2`

The three P1 findings were:

1. critical runtime authority could be replaced through dynamic `self` helper
   lookup, subclassing, or instance shadowing;
2. a fresh start accepted already-advanced durable state; and
3. the 2 MiB checkpoint bound was enforced only after canonical allocation.

The two P2 findings were:

1. `list(None)` could perform an unscoped or namespace-masked listing; and
2. the PostgreSQL integration exercised a primitive graph, not the real M3
   runtime.

The same review batch subsequently reproduced reset-topology residual-state
acceptance, scheduler `snapshot.next` swaps, legacy `lc=1` constructor revival,
missing sniffio reconciliation hashes, missing PostgreSQL connection/lock/
statement timeouts, and a concurrent duplicate-start TOCTOU. This entire
finding history remains immutable even though later bytes close it.

### Remediation round 7/10 and fresh re-review

Round 7 closed the executable findings with:

- an exact pristine full-state start matrix;
- exact scheduler `next`, queued-task, interrupt, and error binding;
- sealed runtime/module authority with no replaceable instance-helper path;
- exact pre-canonical payload budgeting;
- fixed-namespace listing that fails closed without a run-bound config;
- a process-wide keyed duplicate-start guard, inside-lock recheck, and
  concurrent once-only regression;
- strict rejection of legacy JSON constructors and every msgpack extension;
- PostgreSQL connect `5s`, lock `5s`, and statement `30s` bounds;
- a real eight-node PostgreSQL reopen/idempotent-export integration test; and
- exact five-file sniffio license-evidence reconciliation.

Fresh independent re-review directly verified all executable closures, ran its
focused selection with `325 passed`, and passed Ruff, format, focused MyPy,
lock, diff, and 14-of-15 scope. Its immutable verdict is nevertheless:

`FAIL — P0 0 / P1 0 / P2 1`

The sole P2 finding is stale delivery evidence: this record still named old
hashes, old dependency accounting, incomplete rounds, and outdated validation
and PostgreSQL claims.

### Remediation round 8/10 — governance/evidence only

Round 8 changes only ADR-017, the ADR index, the traceability matrix, and this
delivery record. It corrects exact hashes, baseline/current dependency
accounting, rounds 1-8, current focused/full/static evidence, the latest
independent verdict, and the distinction between the earlier primitive
PostgreSQL PASS and the still-pending real-runtime execution after Docker host
crash. Fresh re-review is required; no final PASS is claimed.

Round-8 re-review returned another immutable
`FAIL — P0 0 / P1 0 / P2 1`. The sole finding was a self-binding stale-evidence
cycle: `docs/TRACEABILITY_MATRIX.md` is included in dependency-audit
`candidatePaths` but embedded the dependency candidate identity and manifest
created before that matrix changed. Green executable and static gates did not
override that byte-identity defect.

### Remediation round 9/10 — two-phase non-self-binding evidence

Phase 1 changes the dependency-audit candidate-path traceability matrix so it
contains no current dependency candidate identity or manifest claim. After all
candidate-path documents freeze, the parent runs the exact dependency audit
externally. Phase 2 may then update only this delivery file, which is not in
dependency-audit `candidatePaths`, with the newly generated exact candidate and
manifest identities. No new current manifest was claimed before that audit.

Phase 2 records the completed external Audit: PASS for 107 identities,
`advisory_status=passed_no_known_vulnerabilities`, candidate SHA-256
`f36b0e2ffcfe82529cca42bccb90b2d84c0fea6673164dbc7f3e27f35cac8835`,
and evidence-manifest SHA-256
`27aded0ce779c201ac01c5895dc1252a3a84f439ae31ce7b40958e54359ab727`.
Recomputing `candidatePaths` after this delivery-only edit must remain exactly
`f36b0e2ffcfe82529cca42bccb90b2d84c0fea6673164dbc7f3e27f35cac8835`.
The round-8 self-binding P2 is closed in the candidate bytes, pending fresh
independent verification. This is not a final PASS.

### Round 10/10 — fresh review PASS, terminal infrastructure BLOCKED

Fresh independent review of the then-current exact bytes returned
`PASS — P0 0 / P1 0 / P2 0`. The work item nevertheless remained blocked
because Docker Desktop had crashed before the required real eight-node
PostgreSQL close/reopen/resume test could execute. That infrastructure
interruption was not an M3 implementation finding and did not become a
candidate FAIL. Because the original `10/10` budget was exhausted, no further
candidate change was made without new Owner authority.

### Exceptional Owner-authorized remediation round 11/11 — test assertion only

Once Docker restarted, the real-runtime PostgreSQL test exposed a P2 test
defect: the assertion treated the two mandatory terminal binding reads as
forbidden effects. The Owner authorized exactly one final Round `11/11`,
limited to the existing PostgreSQL integration-test path, with no runtime,
dependency, schema, API, or semantic change and no Round 12.

The correction requires exactly these read-only binding events for each
terminal `inspect` and idempotent terminal `resume`:

```text
pending_draft:load
validation_receipt:load
```

The test continues to prove that `scope_and_safety`, `plan_sources`, evidence
collection, synthesis, validation, receipt save, pending-draft save, approval,
and final export each run exactly once. The runtime byte identity is unchanged.
The pre-Round-11 and current test identities are recorded in the exact-byte
table above.

Fresh Round-11 validation passed the official local PostgreSQL selection
(`2 passed in 1.58s`), the complete socket-disabled suite (`2559 passed`,
`82%` coverage), Ruff, format, strict MyPy, offline lock, diff, exact scope,
bounded secret, and dependency checks. Fresh independent review returned:

`PASS — P0 0 / P1 0 / P2 0`

## Completed supervisor validation

The required sequence was completed from the repository root on the current
exact candidate bytes:

1. focused runtime, infrastructure, workflow, and dependency-boundary tests
   with `--disable-socket`;
2. the separately selected disposable PostgreSQL 18.4 integration, including
   both the primitive and real eight-node close/reopen/resume tests;
3. full offline unit/contract suite with socket disabled and coverage;
4. `uv run --locked --no-sync ruff check .`;
5. `uv run --locked --no-sync ruff format --check .`;
6. `uv run --locked --no-sync mypy src`;
7. offline locked-resolution check;
8. exact 15-path allowlist, `git diff --check`, bounded secret scan,
   dependency inventory/license/advisory, and no-unauthorized-path checks;
9. fresh independent review of actual diff and executable restored-state
   reachability, with `PASS — P0 0 / P1 0 / P2 0`; and
10. exact-byte rebind, completed by this delivery update and its externally
    emitted final SHA-256.

The sole remaining lifecycle gate is the fresh terminal evidence audit.

Review must directly trace checkpoint load through primitive-envelope
validation, strict state reconstruction, run/namespace binding, complete
durable-state/topology validation, capability dispatch, and terminal
verification. Green tests alone are not sufficient.

## Network and protected-boundary accounting

Authorized D1 activity occurred only against PyPI/package indexes, official
LangGraph documentation/source metadata, approved advisory sources, and exact
package downloads. Normal package/advisory traffic is distinct from medical or
provider traffic.

- PyPI/official dependency documentation/advisory/package operations:
  performed by D1 as authorized for exact approved versions;
- Docker registry/image pull: `0`;
- local Docker/PostgreSQL loopback activity: performed only for the authorized
  disposable PostgreSQL 18.4 integration; container removed;
- medical-source requests: `0`;
- OpenAI/provider requests: `0`;
- model execution/downloads: `0`;
- CADEC network: `0`;
- Holdout-20 access: `0`;
- Git remote operations: `0`;
- stage/commit/push/PR/merge operations: `0`.

## Review, remediation, audit, and Git

- Independent review: round-6 immutable
  `FAIL — P0 0 / P1 3 / P2 2`; round-7 fresh re-review immutable
  `FAIL — P0 0 / P1 0 / P2 1`; round-8 re-review immutable
  `FAIL — P0 0 / P1 0 / P2 1`; Round-10 fresh review
  `PASS — P0 0 / P1 0 / P2 0`; Round-11 fresh review
  `PASS — P0 0 / P1 0 / P2 0`.
- Current finding status: no P0, P1, or P2 finding remains after the authorized
  Round-11 integration-test-only correction.
- Remediation rounds consumed: original `10/10` plus exactly one exceptional
  Owner-authorized final Round `11/11`; no Round 12 is authorized.
- Exact-byte rebind: complete, with this delivery file's final SHA-256 emitted
  externally after write.
- Terminal audit: not yet run.
- Git operations: none; the candidate is uncommitted and unstaged.
- Required terminal verdict before Git integration:
  `PASS - P0 0 / P1 0 / P2 0`.

## Remaining risks and deferred work

- The candidate is not terminally complete until the fresh evidence auditor
  decides the current exact bytes. No P0/P1/P2 finding or supervisor gate is
  currently open.
- The 21-package transitive expansion is package-owned but materially expands
  the production dependency surface; the lock and advisory evidence must stay
  exact through integration.
- PostgreSQL evidence now proves both the primitive disposable setup/resume
  path and the real eight-node reopen/idempotent-export path. Production
  operations, retention cleanup, backup, and deployment behavior remain
  outside M3-005.
- M3-005 does not add source capability adapters, CADEC materialization,
  generation/evaluator provider calls, lifecycle migrations, export formats,
  or end-to-end runtime acceptance. Those remain M3-006+ work.
- The designated medical reviewer remains irrelevant to this infrastructure
  candidate and is not invented here; the final release gate remains governed
  separately.

## Manual verification

1. Rehash all 15 allowlisted paths and confirm every changed/untracked path is
   on the allowlist.
2. Inspect the compiled graph definition and prove the eight exact node names,
   single interrupt, private graph/config, and absence of graph retry policy.
3. Reproduce primitive, cross-run, namespace, scheduling, and terminal-state
   corruption negatives and verify no application capability runs first.
4. Inspect the strict serializer construction and prove pickle and module
   reconstruction remain disabled.
5. In disposable PostgreSQL, run official setup twice, verify only the four
   exact tables in `medevidence_langgraph_checkpoint_v1`, close/reopen and
   resume the same run, reject another run/empty namespace, and confirm the
   application schema/data snapshot is unchanged.
6. Compare baseline/current locks to prove the exact two unchanged direct pins,
   21 new package names, sole pip `26.1.2 -> 26.2.1` security upgrade, zero
   removals, and no direct LangChain/Redis/OpenAI SDK.

## Owner interview questions

1. Why can a durable LangGraph checkpoint coordinate resume without becoming
   authoritative proof that Stage 2 validated the report?
2. Why must the application fix both `thread_id = run_id` and
   `checkpoint_ns = m3.orchestration-state.v2` instead of accepting caller
   LangGraph configuration?
3. Why are the four official checkpoint tables isolated from Alembic and
   prohibited as business evidence even though they share the same PostgreSQL
   service?
