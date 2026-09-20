# ADR-032: Durable M1B source execution lifecycle

Decision date: 2026-09-16. Authority: Owner-delegated V1 completion decision.

M1B runs may enter `running` with no completion time. The source bridge writes
an exact acquisition START row and bounded immutable request intent before any
provider operation. A started acquisition without a verified terminal record is
unknown and must not be sent again automatically. Run finalization is a one-way
compare-and-set from `running` to `completed`, `degraded`, or `failed`; terminal
rows cannot be reopened or revised. Historical terminal M1B rows retain their
identities and semantics.

The FAERS bridge uses the existing constrained connector, captures original
response bytes and manifest, stores exact PostgreSQL source rows, then replays
the immutable material and database bindings before returning the aggregate.
It derives numerical evidence only from source-supplied count buckets and
records the fixed FAERS limitations. Source outcome bounds remain the actual
FAERS profile, independent of the wider UI budget.

An openFDA HTTP 404 is exhaustive `no_match` only when the connector's exact
recognized empty-count envelope is complete. Capture and replay require the
same strict recognizer over retained raw bytes. Generic 404, malformed or
truncated responses remain failures. Existing 200 and historical manifest
bytes are unchanged.

DailyMed source execution remains unavailable until a separate retained-source
candidate enrichment authority supplies every required candidate field. A
typed native-query resolver is required; the local concept ID alone is never
used to infer ingredients or provider identity. No live medical-source call
is authorized by this decision.
