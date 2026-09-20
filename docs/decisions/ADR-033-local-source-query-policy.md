# ADR-033: Explicit local source query defaults

The Owner delegated remaining V1 engineering decisions. This bounded policy
maps the two admitted public drug concepts to literal provider search terms;
the mapping is query configuration, never evidence of ingredient or product
identity. DailyMed candidates still require independently captured enrichment.

`m3.local-source-query-policy.v1` has identity
`sha256:33581c3efc9758923cd02b8020f31fdff790afde50f420a1f9f443d515811e13`.

- PubMed continues to use the exact scoped public terms through its catalog
  adapter and bounded query builder.
- DailyMed uses the configured literal `drug_name` searches `semaglutide` or
  `tirzepatide`, requests the Adverse reactions section `34084-4`, and uses
  strict identity selection. A search term cannot supply missing candidate
  ingredients. The policy does not silently pin a label or choose among
  ambiguous candidates. Because this path retrieves current label metadata,
  any explicit global date interval with DailyMed selected is rejected before
  execution. An undated current-label lookup cannot satisfy a historical
  interval. Supporting historical labels requires its own exact version policy.
- FAERS uses only the harmonized-substance stratum with exact configured
  `SEMAGLUTIDE` or `TIRZEPATIDE` values. There is no native-product fallback.
  It retains the existing three-PT tuple and all count/role/interpretation
  constraints. The local workflow admits FAERS only when all three configured
  reaction terms are in scope.
- An explicit FAERS date range is preserved and must have a difference of at
  most 365 days. Without a global date range, its default ends on the persisted
  UTC run-creation date and starts 365 days earlier, covering 366 inclusive
  calendar dates. This source-specific window must be displayed in the report.
  An overlong explicit range is rejected before execution rather than silently
  narrowed. PubMed retains the explicit date bounds. DailyMed's current-label
  restriction is checked independently, including mixed-source scopes.

The composite local scope policy checks these finite capability constraints
before a job is created. Its rejection is a local capability restriction, not
a medical judgment. Requested budgets must also contain each selected source's
fixed execution limits: PubMed 1 page and DailyMed/FAERS 5 pages, each with
512 query characters, 100 records, 5 MiB and 30 seconds. Smaller caller budgets
are rejected rather than overridden. The UI declares upper budgets of 5 pages,
60 seconds and 5 MiB; per-source outcomes must retain their actual limits.
The pure builder and DailyMed resolver perform no I/O.
Actual source execution, enrichment, persistence, source selection and report
approval remain independently gated components. No live source request is
authorized by this code addition.
