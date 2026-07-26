# ADR-001: V1 reference domain

- Status: Accepted by Project Owner; M0 effectiveness pending independent re-review PASS
- Approved by: Boqi Niu
- Approval role: Project Owner
- Approval date: 2026-07-25
- Approval reference: M0-OWNER-APPROVAL-001
- Revision: 1
- Independent review reference: M0-INDEPENDENT-AUDIT-001
- Independent review role: Validation only; not an approving authority

## Context

V1 needs a narrow, formally testable scenario without creating a codebase that
can only answer one hard-coded drug comparison.

## Decision

The formal V1 reference domain and release acceptance scenario is the
comparison of gastrointestinal adverse reactions for semaglutide and
tirzepatide.

The scenario is represented through configuration, `ResearchScope`, source
queries, and evaluation cases. Drug identities, adverse reactions, time range,
selected sources, and comparison intent are typed inputs. Application logic
must not contain reference-drug or reference-reaction branching.

V1 is English-language, local, single-user, research-only, and public-data
oriented.

## Alternatives considered

- Hard-code the reference drugs and reactions for speed.
- Make V1 fully general across all drugs and adverse reactions.
- Use an unrelated generic document-chat scenario.

## Consequences

- The project has a bounded acceptance scenario and reusable contracts.
- Connectors and normalization only need the capabilities required by the
  reference scenario, but they cannot assume fixed drug strings.
- New drug/ADR coverage is a configuration/data expansion when source behavior
  and safety policy remain compatible.
- Full terminology coverage is explicitly not promised by V1.

## Validation

- Reference scenario is expressed as fixture/configuration data.
- A second synthetic drug/ADR scope passes domain and routing tests without
  source-specific hard-coded branches.
- Traceability matrix maps the scenario and configurable scope requirements.

## Supersedes / Superseded by

None.
