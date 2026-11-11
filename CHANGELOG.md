# Changelog

## Unreleased — provider trust controls

- Trust model for the StateProvider, the verdict's trust root
  (`docs/trust_model.md`, `docs/vendor_review_playbook.md`): results are
  labeled `provider_trust` (`harness` / `auditor` / `self_reported`) on
  every record and report; evaluatee-operated results are self-reported.
- Runner controls: a run aborts before the agent acts if the post-seed
  snapshot differs from the seeded initial state (seed read-back);
  `--provider-probe` requires a randomized probe round-trip per run;
  state is snapshotted after every turn (`turn_state` trace events).
- Harness-side state invariants (`scoring/invariants.py`): balance
  conservation, referential integrity, valid amounts — checked
  independently of the provider and folded into the pass rule.
  `RunResult.state_passed` exposes the pass rule without the claim clause.
- Claim verifier v2: claims are verified against the snapshots from
  their own turn onward (no longer only end-of-run) with key-aware
  identifier matching; `safeagenteval regrade` re-verifies saved records
  offline with no model calls.
- Records carry `snapshot_hash` and `scenario_sha256` provenance hashes.

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
