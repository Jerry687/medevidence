---
name: medevidence-autopilot
description: Use for an Owner-approved MedEvidence work item that should run through bounded discovery, implementation, offline validation, independent review, remediation, evidence audit, and local commit. Do not use for unapproved architecture decisions, live medical-source access, or open-ended project completion.
---

# MedEvidence autopilot

Run only one explicitly Owner-approved MedEvidence work item through a bounded,
evidence-gated engineering graph. Repository instructions and the current
work-item authorization remain authoritative.

## Required inputs

- work-item ID;
- objective;
- Owner-frozen behavior;
- exact authorized files or an Owner-approved rule for deriving them;
- approved and prohibited dependencies;
- required validation commands;
- remediation limit;
- Git authorization; and
- explicit network authorization.

If required authorization is missing, perform read-only planning when that is
allowed or stop. Never silently infer authorization.

## Workflow

1. Preflight the repository and Git state against the approved baseline.
2. Load every applicable instruction and work-item evidence record.
3. Spawn `medevidence_explorer` for bounded, read-only mapping.
4. Produce a directed acyclic graph with dependencies, joins, file ownership,
   validation, evidence, retry limits, and stop conditions.
5. Delegate only independent nodes in parallel, with no overlapping writers.
6. Use `medevidence_implementer` for approved write nodes.
7. Run focused validation and the required full offline validation.
8. Spawn `medevidence_reviewer` after integration for independent review of the
   actual diff and executable behavior.
9. Automatically remediate only authorized mechanical findings within the
   retry budget.
10. Spawn `medevidence_evidence_auditor` for the terminal evidence decision.
11. Commit locally only after terminal `PASS` and only when the work item
    explicitly authorizes that Git operation.
12. Stop before the next work item unless it is also explicitly authorized.

## Status model

- `PASS`: every applicable implementation, validation, independent-review,
  scope, evidence, network, and Git-state gate has fresh supporting evidence.
- `FAIL`: a reproducible defect or unmet approved requirement remains.
- `BLOCKED`: required evidence, authority, infrastructure, or safe repository
  state is unavailable.
- `OWNER_DECISION_REQUIRED`: progress requires an Owner-level semantic,
  authorization, dependency, trust-boundary, security, privacy, governance, or
  clinical-safety decision.

Never downgrade `BLOCKED` or `OWNER_DECISION_REQUIRED` merely to keep the graph
moving.

## Handoff format

Return:

- status;
- graph nodes and results;
- exact files;
- commands and tests;
- review findings;
- remediation cycles;
- evidence;
- network operations;
- Git operations;
- remaining risk; and
- one precise Owner question when stopped.

Keep the handoff concise, bind completion to the exact candidate or commit, and
state every required check that was not run.
