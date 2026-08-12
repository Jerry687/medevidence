# M1B-DM-001 Independent Review 015

## Verdict

`FAIL — P0 0 / P1 0 / P2 1`

This verdict binds exact 32-path ordinal/no-terminal-LF manifest
`9f71d93bf5710043697edfd848dc0a4d7bbb4232729edbcc3a939395f44bcd64`.

## P2 — Positive trusted-fetch fixture is not independently constructed

Review 014 required positive trusted-fetch rows to originate independently
from retained/locator evidence. `tests/unit/domain/test_reports.py` helper
`trusted_fetch_rows` still copied `fetch_attempt_id`, `fetch_manifest_id`,
`fetch_member_ordinal`, `fetch_link_id`, `fetch_raw_artifact_id`, and
`fetch_raw_content_hash` from `retained_response`.

This contradicts the delivery claim that positive authority is constructed from
independent constants or stable-label evidence. It is a P2 test/evidence defect,
not runtime P1: an independently constructed row accepted and each independently
mutated primitive rejected. Closure is to use explicit fixture constants,
fetch reference, and stable-label evidence while retaining all negative tests.

## Verified runtime closure

Both public comparators rejected acquisition-only, snapshot-only, ordinal-only,
and complete discovery/fetch conflation; every trusted-fetch omission rejected;
and discovery ordinal plus two accepted, confirming no `+1` rule.

## Candidate identity and validation

- Branch: `feat/m1b-dm-001-contract-freeze`
- HEAD/baseline: `ebcd11eb91aa02ae9a7115188ea10604e9f335d1`
- Freeze SHA-256:
  `e44778f42585134634e2311e16d61d2269f3da06f79ac74c8ed37cbaa701ea70`
- Review 014: 2,512 bytes, SHA-256
  `9041ce99a8411bc275e68cb77fac8f4fa8444e1234feede55e191c6000d27605`
- Index empty; diff check passed.

```text
Domain plus byte-exact OpenAPI: 380 passed
Selection/security/provenance focus: 85 passed, 196 deselected
Compatibility: 568 passed, 2 expected warnings
Architecture/baseline: 13 passed
Full offline: 959 passed, 2 expected warnings
Coverage: 80%
Ruff/format/MyPy: passed
```

No other finding was reproduced across prior closures or scope. No network,
Git mutation, dependency, connector/parser/API/persistence, schema, or DM-002
activity occurred.

## Lifecycle result

Review 015 is `FAIL — P0 0 / P1 0 / P2 1`. Terminal audit and Git lifecycle
remain gated pending mechanical fixture closure and fresh independent `0/0/0`.
