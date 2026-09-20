# ADR-027: paced Attempt012 with unchanged per-case semantics

Decision date: 2026-09-14. Authority: Owner delegates remaining V1 engineering
decisions and completion; supervisor selects this bounded operational successor.

Attempt011 remains FAILED/accepted=false:4 successful cases,5 attempted,6 HTTP
attempts. Exact persisted evidence replay verified. A separate diagnostic sent
the unchanged case005 as its first and only operation: a complete, parseable
response arrived in19.625seconds. That diagnostic is not calibration acceptance
and does not establish a definitive queueing/rate-limit root cause.

Select a conservative15-second pause between successful completed cases in a
new fixed Attempt012. There is no pause before case1, after the last case, or
after a failed run. The next case's45-second budget starts after the pause.
Connect5/read30/write10/pool5, max3 attempts, retry/backoff,36-case order,
provider/model/prompt/schema, frozen human labels and quality thresholds remain
unchanged. No deadline extension or selective-case acceptance is introduced.

Active configuration binds execution profile
`m3.stage2.deepseek-paced-execution.v1`, its canonical identity and pause15.
Historical011 reconstructs the exact unpaced configuration without new fields
and has dedicated immutable replay, alongside007–010. Known historical run IDs
must not be accepted as current authority. New run/config/output identity is
independent; no old raw files, rows or acceptance conclusions are rewritten.

Production pacing is fixed and not a caller-selectable CLI override. Offline
tests can replace the private wait boundary to prove35 waits for36 successful
cases and verify deadline ordering without actual sleeping. Default import,
construction and tests remain free of provider/medical-source calls.

This successor requires focused/full offline, PostgreSQL, independent review
and terminal audit before its separately declared exact live run. The configured
pacing adds525seconds for a complete36-case batch; actual elapsed time is
measured, not guaranteed. Blocking reads retain the disclosed original per-read
timeout limitation. Another failure is retained as a failure; neither this ADR
nor the diagnostic authorizes an unbounded cycle of provider retries.
