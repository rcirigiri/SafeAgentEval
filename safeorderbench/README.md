# SafeOrderBench

SafeOrderBench is the companion scenario set for SafeAgentEval. Every
scenario is a black-box exam: a scripted customer conversation, a seeded
initial state, and the authorized final states the agent's world must
end in. Scenarios are organized by domain and by seven safety
categories (`state_modification`, `confirmation_gate`,
`safety_uncertainty`, `privacy`, `prompt_injection`,
`duplicate_transaction`, `partial_failure`), and every adversarial
scenario is paired with a benign control.

The public pack today is the banking/payments set (16 scenarios across
all seven categories: confirmation gates including mandate limits and
changed terms, payee-note prompt injection, duplicate transfers,
balance-inquiry state modification, ambiguous-payee uncertainty, privacy
disclosure graded by forbidden reply content, and partial failure in
black-box-native form — a customer-reported timeout followed by a retry
request or a status check. Each adversarial case is paired with a benign
control). Further payment workflows are added as scenario YAML on the
same format — no code changes are needed to author them. Other consumer
domains (pharmacy, retail, travel, crypto payments) are roadmap only and
are not part of the released pack.

Public scenarios will be released under CC BY 4.0 with a dataset card.
Private held-out scenarios are intentionally excluded from this
repository. A frozen held-out split with a timestamped manifest hash
commitment is **planned but not yet published** — `splits/` currently
contains only the public manifest. Until then, evaluators who need
cases a vendor cannot have prepared for should generate private or
randomized variants (any root folder works via `--suite`; see
`docs/trust_model.md`).

## Layout

```text
safeorderbench/
├── audits/             Independent review and adjudication records
├── examples/           Small format examples
├── initial_states/     Synthetic snapshots grouped by domain
├── public/             Public scenarios grouped by domain and category
├── schemas/            Scenario and state schemas
├── splits/             Public split manifests and held-out commitment
└── DATASET_CARD.md     Hugging Face dataset documentation
```

The canonical source data lives here. Hugging Face JSONL or Parquet
files will be generated from this source rather than maintained as a
second hand-edited copy.
