# M1A-005 Project Owner integration approval record

- Approval reference: `M1A-005-OWNER-INTEGRATION-APPROVAL-001`
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: `2026-08-08`
- Status: **APPROVED AND EFFECTIVE — M1A OFFLINE INTEGRATED**
- Approved `main` identity:
  `47504a4016f968ed0a0dd10e4280b1a957c15461`
- Integration reconciliation:
  [M1A-005 integration reconciliation](../../.delivery/M1A-005-INTEGRATION-RECONCILIATION.md)
- Live-gate readiness:
  [M1A live-gate readiness](../../.delivery/M1A-LIVE-GATE-READINESS.md)
- Historical audit: [M1A-005 audit](../../.delivery/M1A-005-AUDIT.md)

## Purpose and present effect

This record recognizes the immutable post-merge state of M1A-005. PR #7 was
merged with Create-a-merge-commit semantics at
`47504a4016f968ed0a0dd10e4280b1a957c15461`. The reviewed implementation and
its evidence commits are ancestors of that exact identity. M1A offline
integration is complete; the separately gated live PubMed acceptance remains
`LIVE_GATE_NOT_RUN`.

The historical M1A-005 review and audit remain valid for the pre-merge
candidate they describe. This approval supersedes only their current-state
integration wording; it does not rewrite their candidate identities, earlier
FAIL findings, hosted attestations, or validation evidence.

## Immutable integration ledger

| Item | Identity or result |
|---|---|
| Merge commit / current baseline | `47504a4016f968ed0a0dd10e4280b1a957c15461` |
| M1A-005 implementation | `5a75b96a034abbaf4769f9dfde93ea3bb154567e` ancestor |
| Evidence-finalization commits | `d70b3121634ba2cd1ca89d7c935c6ec470a9a988`, `b603a2df6a1c1c16f5dd80cbd801d425aa6aed23`, and `affc019c74058879a682094bd508ed93f68ed631` ancestors |
| PR #7 | merged, non-draft, base `main` |
| Historical implementation review | PASS — P0 0 / P1 0 / P2 0 |
| Historical terminal audit | PASS — P0 0 / P1 0 / P2 0 |
| Historical hosted checks | `compose-config`, `dependency-audit`, and `windows-quality` PASS |
| Live PubMed acceptance | not run |
| Next milestone | M1B has not begun |

## Non-authorizations

This record does not authorize a PubMed/NCBI request, credentials, a new
dependency, a production source change, a schema/public-interface change, or
any M1B work. Live execution remains behind the separate Owner gate described
in ADR-009 §14 and the readiness record.

No future reconciliation commit, PR-head SHA, merge SHA, hosted result, or
post-commit cleanliness is claimed by this document.
