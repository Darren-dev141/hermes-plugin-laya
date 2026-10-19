# Changelog

## 0.1.0 — 2026-10-19

Initial release. Five native Hermes tools over the local Laya decision
server: `laya_health`, `laya_choose`, `laya_yes_no`, `laya_rank`,
`laya_judge`. Client-side enforcement of Laya's rules (≤10 options, score
fields require `levels`), decision_id on every result, optional
`escalate_below` marking on judge results, fail-soft errors when Laya is
down. Stdlib only.
