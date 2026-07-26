# Connector Layer Rules

These rules extend the repository-root `AGENTS.md` for all source connectors.

## Responsibility

Connectors adapt one external provider at a time. They own transport behavior,
provider request/response DTOs, pagination, rate limits, caching hooks, and
translation into stable application or domain contracts.

They do not perform evidence synthesis, medical interpretation, retrieval
ranking, report generation, agent routing, or UI behavior.

## Isolation rules

- Keep PubMed, openFDA, DailyMed, and future providers in separate adapters.
- Do not import LangGraph, MCP, FastAPI route objects, frontend code, or
  concrete retrieval implementations.
- Do not return raw provider SDK objects across the connector boundary.
- Preserve original source identifiers and enough raw metadata to reproduce a
  lookup.
- Keep source DTOs distinct from source-neutral domain models.
- Do not normalize uncertain source text into an exact drug or event identity
  without recording the mapping method and confidence.

## Network behavior

Every connector must define:

- explicit connect and read timeouts;
- bounded retry only for classified transient failures;
- exponential backoff with jitter;
- rate-limit behavior and respectful client identification;
- maximum pages, records, date span, and payload size;
- pagination and partial-result semantics;
- cache key, freshness, and invalidation behavior;
- cancellation behavior where supported.

Never retry invalid input, authentication failure, or other permanent errors
without an explicit reason. Never hide partial responses behind a successful
complete-result status.

## Error contract

Translate provider failures into typed source-aware errors that distinguish at
least:

- timeout;
- rate limit;
- authentication or authorization failure;
- invalid request;
- unavailable upstream;
- malformed response;
- partial result;
- unsupported source operation.

Preserve the original exception as the cause when safe. Error messages and logs
must not expose credentials or full sensitive payloads.

## Source outcome contract

A connector receives only a source selected by the planning layer. Sources
marked `skipped_not_applicable` or `skipped_by_policy` are not executed and
must not receive a `SourceOutcome`.

Every actually executed terminal source operation reports three orthogonal
dimensions:

- `execution_status`: `succeeded` or `failed`;
- `coverage_status`: `complete`, `partial`, or `unavailable`;
- `result_status`: `matches`, `no_match`, or `indeterminate`.

Required rules:

- The complete set of allowed triples is:
  `succeeded + complete + matches`,
  `succeeded + complete + no_match`,
  `succeeded + partial + matches`,
  `succeeded + partial + indeterminate`,
  `failed + partial + matches`,
  `failed + partial + indeterminate`, and
  `failed + unavailable + indeterminate`.
- Only `succeeded + complete` may produce `no_match`.
- Truncation, an enforced query/result limit, incomplete pagination, or a
  partially parsed response can never be `complete`.
- A zero-result partial or failed operation uses `indeterminate`, never
  `no_match` or “no evidence.”
- Partial matches must retain `coverage_status=partial`.
- Reject partial/unavailable with `no_match`, failed with `no_match`, succeeded
  with unavailable, failed with complete, and unavailable with matches.

Use the normative transition and run-aggregation rules in
`docs/ARCHITECTURE.md`. Contract tests must cover every allowed terminal
combination and reject invalid combinations.

## Evidence semantics

- PubMed metadata and abstracts are not equivalent to full-text study review.
- FAERS report counts do not establish incidence, risk, or causality.
- DailyMed labels must preserve product, SETID/SPL version, section, and
  effective-date context.
- “No result” and “source unavailable” are different outcomes.

## Tests

- Unit tests cover request construction, parsing, pagination, and error
  classification without a network.
- Contract tests use frozen, synthetic, or recorded provider responses.
- Fixtures must remove secrets and record their source/version.
- Live API tests use the `live_api` marker, are opt-in, and are never required
  by the default unit-test command.
- Add cases for malformed, incomplete, paginated, rate-limited, and changed
  upstream responses.
