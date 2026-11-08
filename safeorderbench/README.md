# SafeOrderBench

SafeOrderBench is the companion scenario set for SafeAgentEval.

The planned v1.0 design contains 280 multi-turn text scenarios:

- 4 domains: banking, pharmacy, retail, and travel;
- 7 safety categories; and
- 10 scenarios per domain-category cell.

The exact benign/adversarial composition will be frozen in the benchmark
manifest before scenario authoring is scaled up.

Public scenarios will be released under CC BY 4.0 with a dataset card. Private
held-out scenarios are intentionally excluded from this repository; a
timestamped manifest hash will document the frozen held-out split.

## Layout

```text
safeorderbench/
├── audits/             Independent review and adjudication records
├── examples/           Small format examples
├── fault_schedules/    Seeded, replayable backend faults
├── initial_states/     Synthetic snapshots grouped by domain
├── public/             Public scenario manifests grouped by domain
├── schemas/            Scenario, state, and fault schemas
├── splits/             Public split manifests and held-out commitment
└── DATASET_CARD.md     Hugging Face dataset documentation
```

The canonical source data lives here. Hugging Face JSONL or Parquet files will
be generated from this source rather than maintained as a second hand-edited
copy.
