# M1A PubMed provider-DTD interoperability independent review 001

- Review reference: `M1A-PUBMED-DTD-INTEROPERABILITY-001`
- Work item: `M1A-PUBMED-DTD-INTEROPERABILITY`
- Branch: `fix/m1a-pubmed-provider-dtd-compatibility`
- Approved baseline: `e8e28ffbde7fa3994ff8aa71dd62a956250147c1`
- Reviewed nine-path candidate:
  `sha256:f4b9cf1816c7bb0ec9d3df4fc8bd307ffc6f59ebc03b5abdd27395361c4a586d`
- Independent review: **PASS - P0 0 / P1 0 / P2 0**
- Reviewer remediation cycles consumed: `1` of maximum `4`
- Terminal evidence audit: **PENDING**
- Live acceptance: **NOT PASS; NO RUN 002 AUTHORITY**

## Authority and exact scope

Independent review covered exactly the following nine-path candidate:

- `.delivery/M1A-LIVE-GATE-READINESS.md`;
- `.delivery/M1A-LIVE-RUN-001-RECOVERY.md`;
- `.delivery/M1A-PUBMED-DTD-INTEROPERABILITY.md`;
- `.delivery/STATE.md`;
- `README.md`;
- `docs/TRACEABILITY_MATRIX.md`;
- `src/medevidence/connectors/pubmed/parsing.py`;
- `tests/contract/connectors/test_pubmed_connector.py`; and
- `tests/unit/connectors/test_pubmed_parsing.py`.

The candidate adds no dependency and changes no client, domain, schema, public
exception, or public interface. Review and validation made no network request,
live medical-source request, external-artifact write, or Git state/history
operation. No staging, commit, push, pull, fetch, merge, rebase, reset, clean,
branch deletion, history rewrite, or remote-state mutation occurred.

## Reviewed behavior and security boundary

The parser accepts no DOCTYPE or one bounded ASCII external `SYSTEM` or
canonical NLM `PUBLIC` declaration before the operation-specific root. The
declaration is metadata only: scheme, exact host, credential/userinfo, port,
fragment, size, declaration count, root, and public identifier are validated
without dereferencing any DTD. Internal subsets, general/parameter/external
entities, body entity references, malformed declarations, declarations after
the document root, and declared/actual/operation root mismatches fail closed.

Final parsing uses the exact hardened call:

```python
safe_etree.fromstring(
    payload,
    forbid_dtd=False,
    forbid_entities=True,
    forbid_external=True,
)
```

Unsupported-encoding policy and all existing semantic item, response, record,
page, and completeness bounds remain unchanged. Fixed safe
`InvalidPubMedXmlError` messages never interpolate provider payload, DTD URL,
encoding, or parser metadata.

## Review finding and remediation

The initial candidate review found one P2 class with two manifestations:

1. an invalid allowed-host port containing `LEAK_SENTINEL` remained reachable
   through the translated error cause/context and formatted traceback; and
2. a delayed unsupported XML encoding token could remain reachable through the
   caught parser `LookupError`.

Reviewer remediation cycle 1 of 4 translated parser, ASCII-decode, URL-split,
and port failures only after leaving the active exception handler. Exact
sentinel regressions now require `__cause__ is None`, `__context__ is None`,
and absence from the exception string, representation, arguments, object state,
and `traceback.format_exception`. The same cycle corrected the stale focused
test total in the delivery record. No P0, P1, or P2 finding remains.

## Fresh validation evidence

The exact focused command was:

```text
uv run --locked --no-sync pytest tests/unit/connectors/test_pubmed_parsing.py tests/contract/connectors/test_pubmed_connector.py tests/unit/test_dependency_boundaries.py --disable-socket -q
```

Result: `149 passed`. The focused parser evidence contains 7 positive and 21
negative provider-DTD/security probes, including the invalid-port, non-ASCII
declaration, delayed-encoding, wrong-operation-root, after-root declaration,
entity, non-resolution, malformed, and oversize cases.

The exact full offline command was:

```text
uv run --locked --no-sync pytest tests/unit tests/contract --disable-socket --cov=medevidence --cov-report=term-missing --cov-report=xml
```

Result: `749 passed`; measured coverage was `78.86%`, reported as rounded whole
coverage `79%`. The required `uv lock --check --offline` completed
successfully.

An ancillary, non-required `uv sync --locked --offline --check --group dev`
read-only probe was run and reported only editable-local-project reinstall
drift. No synchronization or environment change was performed; this probe is
not a required gate for this work item.

## Retained evidence and disposition

The exact retained response remains 2,205 bytes with SHA-256
`6a9e93bae1247dd69771be66c13f05eb7c0e6efd11ddbd1ae33698b1fd1f6aa3`.
At the approved baseline, those bytes deterministically produced
`InvalidPubMedXmlError`. Under the reviewed candidate, the same bytes parse as
`PubMedSearchPage` with provider `count=676` and
`returned_identifier_count=100`, with zero socket calls and zero external
file-open calls.

The canonical manifest remains 1,380 bytes with SHA-256
`fab3ba93ab1f81e9bd6ca7b8bc705a5c065faced452dea33895f13d66151165a`.
The recovery record remains 3,032 bytes with SHA-256
`1d90d931620952c0a0ea62aaa29d9b9a8c3ed952b3cef8860accf9db1e9f37cf`.

The root cause is `CLIENT_XML_DTD_INTEROPERABILITY_FAILURE`, not an NCBI
outage: response bytes were received, and the baseline parser rejected the
official external provider declaration before accepting the document. The
historical connector result remains `failed / unavailable / indeterminate`;
the manifest/envelope separately remain `failed / partial / indeterminate`
because received bytes were retained. Fetch was not executed.

The exact milestone states remain `M1A_LIVE_RUN_001_EXECUTED`,
`LIVE_GATE_ACCEPTANCE_UNRESOLVED`, and `NO_RERUN_AUTHORIZED`, alongside the
additional disposition
`M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE`. No rerun or
live PASS occurred.

## Decision

**PASS - P0 0 / P1 0 / P2 0** for the exact reviewed nine-path candidate
`sha256:f4b9cf1816c7bb0ec9d3df4fc8bd307ffc6f59ebc03b5abdd27395361c4a586d`.

This is an independent implementation-review decision only. Terminal evidence
audit, local commit, PR, push, merge, and integration remain pending. This
record does not establish `M1A_LIVE_ACCEPTANCE_PASS`, authorize PubMed live run
002, authorize any other live medical-source operation, complete M1A, or make
the project ready for M1B Owner planning. Any second live run remains under a
new exact Owner authorization.
