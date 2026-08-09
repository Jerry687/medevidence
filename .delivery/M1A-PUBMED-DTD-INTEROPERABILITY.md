# M1A PubMed provider-DTD interoperability

Updated: `2026-08-08`

Status: `M1A_LIVE_RUN_001_EXECUTED`; `LIVE_GATE_ACCEPTANCE_UNRESOLVED`;
`NO_RERUN_AUTHORIZED`;
`M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE`;
`READY_FOR_INDEPENDENT_REVIEW`; `NO_LIVE_REQUEST_PERFORMED`;
`NO_LIVE_PASS_CLAIMED`

Branch: `fix/m1a-pubmed-provider-dtd-compatibility`

Baseline: PR #9 merge `e8e28ffbde7fa3994ff8aa71dd62a956250147c1`

## Disposition

Live run 001 is dispositioned as
`M1A_LIVE_RUN_001_ACCEPTED_AS_FAILED_INTEROPERABILITY_EVIDENCE` with root
cause `CLIENT_XML_DTD_INTEROPERABILITY_FAILURE`. The immutable first response
was received successfully, but the historical connector rejected the official
external provider DOCTYPE before parsing the ESearch document. This was not an
NCBI outage and does not establish a live acceptance PASS.

The historical connector outcome remains `failed / unavailable /
indeterminate`. Its manifest and acquisition envelope remain `failed / partial
/ indeterminate` solely because the received response bytes were retained.
Fetch was not executed. No rerun was performed. Any second live run is a new,
Owner-controlled operation requiring exact authorization.

## Bounded implementation

The PubMed parser now accepts either no DOCTYPE or exactly one external
DOCTYPE before the document root. An accepted declaration is ASCII, at most
1,024 bytes, uses `SYSTEM` or `PUBLIC`, names the operation-specific root, and
uses HTTPS on exactly `eutils.ncbi.nlm.nih.gov` or `dtd.nlm.nih.gov`. Userinfo,
credentials, ports, fragments, noncanonical NLM public identifiers, internal
subsets, entity declarations, multiple declarations, malformed declarations,
and oversized declarations fail closed with fixed redacted errors.
Provider parser, ASCII decoding, URL splitting, and port-validation exceptions
are translated only after leaving their active exception handlers; no
untrusted provider value remains in the typed error cause, context, arguments,
representation, or formatted traceback.

The declaration is validation-only metadata. Parsing uses
`defusedxml.ElementTree.fromstring` with `forbid_dtd=False`,
`forbid_entities=True`, and `forbid_external=True`; no DTD is dereferenced.
The declared root, actual parsed root, and operation-expected root must agree.
The existing encoding policy and semantic item, page, record, and response
shape bounds remain unchanged. No dependency, public exception, client,
domain, schema, or evidence-semantic contract changed.

## Deterministic evidence

Focused unit and connector contract validation completed with sockets disabled:

```text
uv run --locked --no-sync pytest tests/unit/connectors/test_pubmed_parsing.py tests/contract/connectors/test_pubmed_connector.py tests/unit/test_dependency_boundaries.py --disable-socket -q
149 passed in 0.60s
```

The tests cover accepted search/fetch documents with absent and official-style
external DOCTYPE declarations, whitespace variants, MockTransport request
counts, and sentinel URL/file non-resolution. Negative coverage includes
internal subsets, general/parameter/external entities, entity references,
HTTP, userinfo, unapproved host, fragment, port, noncanonical public ID,
multiple/cross-operation/mismatched roots, malformed/oversized declarations,
unsupported encodings, malformed XML, and existing semantically incomplete
documents. Dedicated invalid-port, non-ASCII declaration, and delayed-encoding
sentinels are absent from the error string, representation, arguments, cause,
context, object state, and formatted traceback.

After the focused tests passed, the exact retained raw response was read
offline without printing its content. It remains 2,205 bytes with SHA-256
`6a9e93bae1247dd69771be66c13f05eb7c0e6efd11ddbd1ae33698b1fd1f6aa3`.
The revised parser returned `PubMedSearchPage` with provider `count=676` and
`returned_identifier_count=100`; socket calls and external file-open calls were
both zero. The recovery record remains 3,032 bytes with SHA-256
`1d90d931620952c0a0ea62aaa29d9b9a8c3ed952b3cef8860accf9db1e9f37cf`.
The canonical manifest remains 1,380 bytes with SHA-256
`fab3ba93ab1f81e9bd6ca7b8bc705a5c065faced452dea33895f13d66151165a`.

Ruff, format, dependency-boundary, final focused, and diff checks are recorded
in the implementation-node handoff after the documentation content is frozen.
Independent review, terminal audit, local commit, PR, merge, and any second live
run remain outside this node.

## Remaining risk and manual verification

This candidate proves deterministic compatibility with the retained response
and synthetic external declarations. It does not prove a current provider
response, current network availability, or complete live search/fetch behavior.
An authorized reviewer should inspect the exact diff, rerun the sockets-disabled
focused commands, recompute the nine-path candidate identity, and independently
confirm that external DTD metadata cannot initiate network or filesystem I/O.

The Owner should be able to answer:

1. Why is the historical failed/unavailable/indeterminate outcome immutable
   even though the retained bytes parse under the candidate?
2. Which validation rules permit provider DTD metadata without enabling DTD or
   entity processing?
3. Why would a second live run require new authorization and create new
   evidence rather than overwrite live run 001?
