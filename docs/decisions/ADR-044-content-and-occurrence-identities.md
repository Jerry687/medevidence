# ADR-044: Shared source content and run-bound outcome occurrences

Source response artifacts are addressed by their content hash. The same exact
response bytes may therefore appear in multiple acquisitions and runs. The
first persisted `created_at_utc` is retained for that shared artifact row;
later insert-or-verify calls must still match every intrinsic field, including
hash, byte size, media type, storage path, schema, source partition and corpus
context. Acquisition and snapshot rows continue to carry the actual per-run
observation and retrieval timestamps.

`source-operation-outcome` remains the provider-neutral content identity used
by workflow contracts and receipts. Identical queries and results can produce
the same content identity in separate runs, while each PostgreSQL outcome row
also contains run, source, acquisition and snapshot bindings. The persisted
primary key is therefore `(run_id, source, acquisition_id,
source_outcome_id)`. Existing stronger run-qualified uniqueness constraints
and foreign keys remain unchanged. No prior row is merged, rewritten or given
a different content identity.

The migration only replaces the primary-key constraint. Downgrade attempts to
restore the legacy global content-ID key and fails transactionally if multiple
run-bound occurrences already exist; it never deletes or combines evidence.

Downgrade is conditional: after multiple occurrences share a content outcome ID,
restoring the historical global key would be lossy. The migration explicitly
checks for such duplicates and refuses before DDL; it never merges or deletes
records to force rollback. With no duplicates the original key can be restored.
