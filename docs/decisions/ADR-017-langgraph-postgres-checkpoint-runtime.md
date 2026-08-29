# ADR-017: LangGraph PostgreSQL checkpoint runtime

- Status: Accepted by Project Owner; round-8 evidence remediation awaiting fresh re-review
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-08-28
- Approval reference: `OWNER FULL M3 RUNTIME AUTHORIZATION - V1`
- Approval artifact SHA-256: `e6b812f6411b8e8a62a559ae0182b45cae25bc70d0173c135b94e97b8cd73fa8`
- Work item: `M3-005-LANGGRAPH-POSTGRES-CHECKPOINT-RUNTIME`
- Baseline: `b29c2b5805dbb3d6be251cac2480f050f81928b7`
- Revision: 2
- Independent review reference: Round-7 fresh re-review — immutable `FAIL — P0 0 / P1 0 / P2 1`
- Independent review role: Validation only; not an approving authority

## Context

ADR-005 accepted a bounded LangGraph workflow with one export-approval
interrupt, and ADR-016 made an independently persisted validation receipt the
authority for canonical report-validation proof. M3-005 supplies the missing
runtime and checkpoint infrastructure without moving application behavior into
LangGraph or treating checkpoint bytes as evidence.

The Owner froze `langgraph==1.2.11` and
`langgraph-checkpoint-postgres==3.1.2`. The exact-version package metadata
declares Python `>=3.10`, so both support the repository's exact Python
`>=3.12.13,<3.13` boundary, and declares the MIT license. The locked artifacts
are:

| Package | Wheel SHA-256 | sdist SHA-256 |
|---|---|---|
| `langgraph==1.2.11` | `8bab70de7b2d00b5300fb289bcf38d8b241400f3184c1e95e8ce706fb0e8686b` | `9ecfe11e50d338b34b15cf4d8a442642de103e8ae6971320efba84e4542eb363` |
| `langgraph-checkpoint-postgres==3.1.2` | `6a7e38ef16985b54e356cba7bdaf447943aae33d5aaf290026c593bb6b4a6264` | `1cd404803ff895a2b79f3ac04ce92b775e6b999715f8333fce674c6d927bba95` |

Official primary metadata and implementation references are the exact-version
PyPI JSON records at
`https://pypi.org/pypi/langgraph/1.2.11/json` and
`https://pypi.org/pypi/langgraph-checkpoint-postgres/3.1.2/json`, the official
LangGraph documentation at
`https://docs.langchain.com/oss/python/langgraph/persistence`, and the package
source at
`https://github.com/langchain-ai/langgraph/tree/main/libs/checkpoint-postgres`.

The baseline lock governed 86 third-party identities. The current lock governs
107: 21 new package names required by the approved graph plus one security-
required dev-tool upgrade, `pip==26.1.2` to `pip==26.2.1`. The pip change fixes
`PYSEC-2026-3721` / `CVE-2026-13346`, whose fixed floor is `26.2`; it does not
change a production direct pin. The two Owner-frozen direct pins remain exact.
The graph includes `langchain-core==1.6.1` only because the approved LangGraph
distribution owns that transitive requirement. MedEvidence does not directly
depend on LangChain, Redis, the OpenAI SDK, or another model/provider package.

The initial independent review after remediation round 6 remains immutable
`FAIL — P0 0 / P1 3 / P2 2`. Its primary findings were replaceable
instance/subclass helper authority, acceptance of a non-pristine fresh-start
state, post-allocation enforcement of the 2 MiB bound, unscoped checkpoint
listing, and a PostgreSQL test that exercised only a primitive graph. The same
review batch also demonstrated residual data in reset topology, swapped
scheduler state, legacy `lc=1` constructor revival, missing exact sniffio
artifact reconciliation, missing PostgreSQL timeouts, and a duplicate-start
TOCTOU. Round 7 closed those executable findings. Fresh re-review directly
verified the closures and returned immutable `FAIL — P0 0 / P1 0 / P2 1`
solely because the delivery evidence still described earlier bytes and gates.
Round 8 changes governance/evidence only and requires a fresh re-review; no
final PASS is claimed by this ADR.

## Decision

### Application graph

One `LangGraphOrchestrationRuntime` coordinates the existing application-owned
workflow through exactly these eight nodes, in order:

1. `scope_and_safety`
2. `plan_sources`
3. `collect_evidence`
4. `synthesize_claims`
5. `validate_report`
6. `save_pending_draft`
7. `request_export_approval`
8. `finalize_and_export`

The graph contains no connector, parsing, retrieval, citation-policy,
validation-receipt, or export-persistence business logic. It adds no graph
retry policy; connector retries and source-attempt semantics remain owned by
their existing capabilities. The only interrupt is immediately before
`request_export_approval`.

The compiled graph and its configuration are private implementation details.
Callers can start only with an exact `OrchestrationState`, and can inspect or
resume only by validated `run_id`; no caller-provided runnable configuration or
public compiled graph is accepted. The runtime derives `thread_id = run_id`
and always stores under the sole constant namespace
`m3.orchestration-state.v2`.

### Checkpoint trust boundary

The checkpoint envelope contains only bounded JSON/messagepack-safe
primitives. Before node dispatch, resume, inspection, or terminal return, the
runtime:

```text
loads checkpoint bytes
  -> validates the exact primitive envelope and resource bounds
  -> strictly reconstructs the versioned OrchestrationState
  -> binds the expected run and fixed checkpoint namespace
  -> executes complete canonical durable-state and topology validation
  -> dispatches or verifies the terminal application state
```

Unsupported objects, non-string keys, reference cycles, non-finite numbers,
malformed state, cross-run identity, namespace drift, scheduling drift, and
invalid durable topology fail closed. A restored completed source task is not
refreshed by the graph, absence of a terminal task never becomes `no_match`,
and a terminal return is revalidated through the application workflow.

Checkpoint state is infrastructure state, not authoritative evidence. It
cannot prove Stage-2 execution or authorize export. The independently
persisted `M3_VALIDATION_RECEIPT_V1` and the canonical ADR-016 verification
path remain the report-validation authority.

Serialization uses `JsonPlusSerializer` with `pickle_fallback=False`,
`allowed_json_modules=None`, and `allowed_msgpack_modules=None`. No Python
pickle fallback or open runtime-module reconstruction is permitted.

### PostgreSQL lifecycle ownership

LangGraph checkpoint infrastructure uses the isolated PostgreSQL schema
`medevidence_langgraph_checkpoint_v1`. An application-owned synchronous
`psycopg` connection uses autocommit, `prepare_threshold=0`, and a fixed
`search_path` to that schema followed by `public`. The exact official
`PostgresSaver.setup()` mechanism creates and upgrades only:

- `checkpoint_migrations`
- `checkpoints`
- `checkpoint_blobs`
- `checkpoint_writes`

These tables are package-owned infrastructure. They are not duplicated in an
application table, are not managed by application Alembic migrations, and are
never queried by domain or application code as business evidence. Tests may
inspect them only to verify infrastructure isolation and official setup.

One earlier disposable PostgreSQL 18.4 integration run used the already-local
image identity `1961f96e6029`, an ephemeral loopback port, and the official
setup plus fixed-namespace primitive resume path. It passed `1/1`. The first
integration fixture was an immutable test-design failure because it asserted
the frozen namespace through a raw root `PostgresSaver`; it was corrected to
test the actual `_FixedNamespaceSaver` application composition. The disposable
container was removed and Docker Desktop stopped. No image pull occurred. The
new final real eight-node runtime reopen/export integration test has been
implemented but has not executed against PostgreSQL because the Docker host
crashed; its real-runtime database result remains pending.

## Alternatives considered

- Expose LangGraph configuration or the compiled graph to callers. Rejected
  because callers could influence checkpoint identity or namespace.
- Persist arbitrary Python objects or enable pickle fallback. Rejected because
  restored checkpoint content is untrusted.
- Treat the checkpoint as proof of validation or Stage-2 completion. Rejected
  because ADR-016 requires an independent durable validation receipt.
- Manage package checkpoint tables through application Alembic or query them
  as business state. Rejected because the tables are implementation
  infrastructure owned by the exact checkpointer package.
- Add Redis, direct LangChain, or OpenAI SDK dependencies. Rejected because
  none is required or authorized for this work item.
- Add a graph-level retry policy. Rejected because retry and attempt
  provenance remain capability-owned.

## Consequences

- M3 obtains durable checkpoint/resume coordination without changing existing
  workflow, source, report, receipt, or export semantics.
- Checkpoint deserialization and restored-state use fail closed at the
  application boundary.
- Exact package versions and infrastructure schema ownership become part of
  the M3 runtime release freeze.
- `langchain-core` and its package-owned transitive graph increase the locked
  dependency surface; exact lock, license, advisory, and dependency-boundary
  gates are therefore required for every candidate.
- M3-006 and later work items still own source capability adapters,
  generation/evaluator providers, lifecycle records, and formal export.

## Validation

- Assert the graph exposes exactly eight application nodes and one interrupt
  before `request_export_approval`.
- Assert runtime entry points accept no caller configuration and always bind
  `thread_id` to `run_id` plus the sole fixed namespace.
- Assert cross-run, namespace, topology, primitive-type, cardinality, byte,
  depth, node-count, cycle, and terminal-state drift fail closed before a
  capability or trusted return.
- Assert resume does not repeat completed work and the graph defines no retry
  policy.
- Assert the serializer has no pickle fallback or permitted runtime module
  reconstruction.
- Assert official setup creates exactly the four package tables in the
  isolated schema and changes no application relation or row count.
- Assert close/reopen resume uses the same run and namespace and cannot load a
  different run or the root empty namespace.
- Run exact baseline/current dependency comparison, verify the sole pip
  security upgrade and unchanged direct pins, inspect licenses/hashes, run
  `pip-audit`, dependency-boundary tests, focused tests, full offline
  validation, independent review, exact-byte rebind, and terminal evidence
  audit.

## Supersedes / Superseded by

Supersedes none. This record implements and constrains the runtime portion of
ADR-005 and supplements ADR-008 and ADR-016 without rewriting their accepted
history. Superseded by none.
