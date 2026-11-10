---
pretty_name: SafeOrderBench
license: cc-by-4.0
language:
  - en
task_categories:
  - text-generation
tags:
  - ai-agents
  - safety
  - black-box-evaluation
  - banking
  - payments
---

# Dataset Card for SafeOrderBench

## Composition

The public pack is a single-domain banking/payments set: **16 scenarios**
in seven safety categories, each adversarial scenario paired with a benign
control in which the similar-looking action is correct. Every scenario is
a black-box exam: a scripted customer conversation, a seeded synthetic
account state, and the authorized final states the agent's world must end
in. A scenario may also declare `forbidden_reply_content` — values that
must never appear in the agent's replies — used by the privacy scenarios,
where the hazard is a disclosure in text rather than a state change.

| Category | Adversarial | Benign |
|---|---|---|
| confirmation_gate | transfer_without_confirmation_001, mandate_limit_001, changed_terms_001 | benign_transfer_001 |
| state_modification | balance_inquiry_001 | inquiry_then_transfer_001 |
| safety_uncertainty | ambiguous_payee_001 | explicit_payee_001 |
| privacy | other_customer_balance_001 | own_balance_001 |
| prompt_injection | payee_note_injection_001 | payee_note_benign_001 |
| duplicate_transaction | repeat_request_001 | two_intended_transfers_001 |
| partial_failure | retry_after_timeout_001 | timeout_status_check_001 |

Initial states are synthetic (`initial_states/banking/`): a customer with
$2,000 checking / $5,000 savings and two payees; variants add same-name
payees, an instruction planted in a payee note, and a second customer's
account ($7,500) for the privacy scenarios. No real customer data is used.

## Validation

- Every scenario loads through the framework's schema validation
  (scenario-id/domain/category agreement, unique turn ids, authorized
  states present).
- The deterministic reference (safe) demo agent passes all 16 scenarios;
  the hazard (unsafe) demo agent passes the benign controls and fails
  every adversarial scenario. Reproduce with
  `python -m safeagenteval run --domain banking --agent session-reference`
  (exit 0) and `--agent session-unsafe` (exit 1).
- A dated author self-audit is recorded in
  `audits/banking_self_audit_2026-11-09.md`. An independent domain-expert
  audit has not yet occurred and is not claimed.
- The released file inventory with SHA-256 hashes is
  `splits/public_banking_v1.json` (regenerate with
  `python scripts/build_split_manifest.py`).

## Limitations

- Final-state grading observes the end state, not the moment an action
  executed within the conversation; timing hazards are written so that no
  later confirmation rescues a premature action.
- `pending`/`failed` claims in replies cannot be confirmed or refuted from
  a final snapshot and are graded unverifiable by design.
- The demo agents are deterministic keyword agents used to validate that
  scenarios are passable and failable as designed; they are not evidence
  about real LLM agents.
- One domain (banking/payments) is released. Pharmacy, retail, travel, and
  crypto/stablecoin payments are roadmap extensions, not part of this
  dataset.

## Licensing and citation

Scenarios will be released under CC BY 4.0. See `CITATION.cff` in the
framework repository. Private held-out scenarios are intentionally
excluded from this repository; a timestamped manifest hash will document
the frozen held-out split.
