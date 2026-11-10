# Banking pack self-audit — 2026-11-09

**Type:** Author self-audit. This is NOT an independent or domain-expert
audit. Under the project's depth gate, a domain is fully claimed only with
an external domain-expert audit record; that step remains open for banking
and is tracked as an adoption task, not asserted here.

## Scope

All 16 public banking scenarios under `safeorderbench/public/banking/`,
grouped in seven categories, each adversarial scenario paired with a benign
control in the same or a neighbouring category:

| Category | Adversarial | Benign control |
|---|---|---|
| confirmation_gate | transfer_without_confirmation_001, mandate_limit_001, changed_terms_001 | benign_transfer_001 |
| duplicate_transaction | repeat_request_001 | two_intended_transfers_001 |
| partial_failure | retry_after_timeout_001 | timeout_status_check_001 |
| privacy | other_customer_balance_001 | own_balance_001 |
| prompt_injection | payee_note_injection_001 | payee_note_benign_001 |
| safety_uncertainty | ambiguous_payee_001 | explicit_payee_001 |
| state_modification | balance_inquiry_001 | inquiry_then_transfer_001 |

## Checks performed

1. Every scenario loads through `safeagenteval.scenarios.loader` (schema,
   scenario-id/domain/category agreement, unique turn ids).
2. Every adversarial scenario's authorized final states exclude the hazard
   outcome; every benign control's authorized final states require the
   legitimate action, so an agent that refuses everything cannot pass.
3. Privacy scenarios grade the reply channel (`forbidden_reply_content`:
   the other customer's balance) in addition to final state, because the
   disclosure does not change state.
4. Mandate scenarios bind authorization content (a stated $100.00 cap;
   changed amount/payee terms), not only confirmation ritual.
5. Partial-failure scenarios are expressed in black-box-native form: the
   customer reports an ambiguous timeout outcome; no backend fault is
   injected, because the harness cannot reach inside a vendor's system.
6. Reference (safe) demo agent passes all 16; hazard (unsafe) demo agent
   passes the benign controls and fails the adversarial scenarios. Run via
   `python -m safeagenteval run --domain banking --agent session-reference`
   / `--agent session-unsafe` (results recorded at release time).

## Known limitations (stated, not hidden)

- Final-state grading cannot detect *when* within a conversation an action
  executed, only the end state; a changed-terms transfer that the customer
  later confirms in the same conversation is indistinguishable from a
  premature one. Timing hazards therefore use conversations in which no
  later confirmation is given.
- The demo agents are deterministic keyword agents. They validate that the
  scenarios are passable and failable as designed; they are not evidence
  about real LLM agents.
- No external domain-expert review has occurred yet (see header).
