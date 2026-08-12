# M1B-DM-001 Independent Review 014

## Verdict

`FAIL — P0 0 / P1 1 / P2 0`

## P1-01 — Public fetch comparators permit discovery/fetch acquisition conflation

The Review 013 remediation matches fetch fields to caller-supplied trusted
values, but `RetainedSplResponse.validate_against` and
`DailyMedLocatorV1.validate_against` do not both require the trusted fetch
acquisition to remain distinct from the authoritative discovery decision.

Reproduced with the positive fixture:

```text
RETAINED_ACCEPTED_REUSED_DISCOVERY_ACQUISITION acquisition:dailymed-discovery
LOCATOR_ACCEPTED_REUSED_DISCOVERY_ACQUISITION acquisition:dailymed-discovery
RETAINED_ACCEPTED_FULL_DISCOVERY_FETCH_CONFLATION 0 snapshot:dailymed-discovery
```

The retained response reused the discovery acquisition, recomputed its valid
response ID, and received matching trusted fetch values. A second case also
reused discovery intent, ordinal `0`, and snapshot. Both public comparators
accepted, although report/section aggregates reject the conflation.

Required closure: require fetch acquisition ID and snapshot to differ from the
decision discovery values and fetch ordinal to be strictly greater, without a
`+1` rule; add direct one-relation and complete-conflation tests; construct
positive trusted-fetch rows independently rather than copying retained values.

## Candidate identity and gates

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Freeze SHA-256:
  `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Exact 31-path ordinal/no-terminal-LF manifest:
  `7ba32e4738a45f990b3b6f0fde6c2d34b9a1062aed8d6f638824479739f61274`
- Review 013: 2,864 bytes, SHA-256
  `245e265afded275d54771eceba0d0c413ebbf149baa6b385eca9a7a9c9cd3b9f`
- Index empty; diff check passed.

```text
Domain plus byte-exact OpenAPI: 380 passed in 0.83s
Full offline: 959 passed, 2 expected warnings
Ruff check: passed
Ruff format: 67 files already formatted
MyPy --no-incremental: 34 source files passed
```

No other finding was reproduced in prior closures, selection semantics,
provenance union/uniqueness, security/XML/ZIP/LOINC, M1A/OpenAPI, or scope.
No network, Git mutation, dependency, connector/parser/API/persistence, schema,
or DM-002 activity occurred.

## Lifecycle result

Review 014 is `FAIL — P0 0 / P1 1 / P2 0`. Terminal audit and every Git/PR/CI/
merge/integration step remain prohibited pending mechanical remediation and a
fresh independent `0/0/0` review.
