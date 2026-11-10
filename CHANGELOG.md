# Changelog

## Unreleased — enterprise scaling

- Concurrent execution: `run --concurrency N` (bounded worker pool; each
  run has a unique `run_id`, recorded in its trace), `--retries N` with
  exponential backoff for aborted runs only (records carry `attempts`).
- Providers may be asynchronous (`AsyncStateProvider`): awaitable
  seed/snapshot/reset results are detected and awaited. Providers that
  share one backend partition per instance and may implement
  `set_run_context(run_id)`.
- Record sinks: `--sink file|sqlite`; SQLite stores indexed run history
  in one file. `report`, `build-site`, and `judge` accept a directory or
  a SQLite path.
- New `matrix` command: one suite against several `label=agent` entries
  with a combined pass-rate table and a cross-agent `--min-pass-rate`
  gate.
- `judge` gains `--sample-rate` (deterministic subset) and
  `--concurrency` for cost-controlled offline judging.

## 0.2.0 — 2026-11-09

Banking/payments focus release (black-box execution only).

- SafeOrderBench public pack is now 16 banking scenarios across all seven
  safety categories, each adversarial scenario paired with a benign
  control: added mandate-limit and changed-terms confirmation scenarios,
  two-intended-transfers and inquiry-then-transfer benign controls,
  privacy scenarios (graded by forbidden reply content), and
  partial-failure scenarios in black-box-native form (customer-reported
  timeout, retry vs. status check).
- Scenario model: `forbidden_reply_content` grades reply-channel hazards
  (e.g. disclosing another customer's balance) deterministically; a
  `reply_violation` trace event records each disclosure, and the single
  pass rule includes it.
- CLI: `run` accepts `--extractor-model provider:model` to extract and
  verify reply claims (results persisted in run records) and
  `--min-pass-rate` as a pre-deployment CI gate; new `judge` command
  grades saved run records with an LLM judge and reports agreement with
  the deterministic verdict.
- Split manifest (`safeorderbench/splits/public_banking_v1.json`) hashes
  every released scenario; a dated author self-audit of the banking pack
  is recorded under `safeorderbench/audits/` (external expert audit still
  open, and not claimed).
- Removed the retail/pharmacy/travel scenario placeholders; banking and
  payments are the sole released domain. Other consumer domains remain
  roadmap, not released packs.

## 0.1.0 — 2026-11-08

Initial release: black-box session-agent evaluation harness, deterministic
final-state scoring over hash-linked traces, claim extraction/verification,
LLM judge, conformance certification, and the initial banking scenario
pack with paired reference (safe) and hazard (unsafe) demo agents.
