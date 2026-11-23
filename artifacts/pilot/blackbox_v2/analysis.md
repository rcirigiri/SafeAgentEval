# Black-box pilot analysis (pilot: blackbox_v2)

| Agent | Runs | Pass rate | Benign | Adversarial | Claims | Contradicted |
|---|---|---|---|---|---|---|
| claude-opus-5-5 | 32 | 1.0 | 1.0 | 1.0 | 51 | 0 |
| gpt-4.1-mini | 32 | 0.75 | 1.0 | 0.5556 | 45 | 0 |

Judge vs deterministic:

- claude-sonnet-5-5|replies: {'n': 64, 'agreement': 0.9375, 'kappa': 0.6364}
- claude-sonnet-5-5|with_state: {'n': 64, 'agreement': 1.0, 'kappa': 1.0}
- gpt-6.1-sol|replies: {'n': 64, 'agreement': 0.8906, 'kappa': 0.2}
- gpt-6.1-sol|with_state: {'n': 64, 'agreement': 0.9844, 'kappa': 0.9245}

Labeling: {"claims_total": 96, "extraction_labeled": 0, "extraction_accuracy": null, "verdict_labeled": 0, "verdict_accuracy": null, "contradictions_confirmed": 0, "contradictions_rejected": 0, "contradictions_unlabeled": 0, "replies_total": 92, "replies_with_missed_claims_labeled": 0, "runs_total": 64, "runs_labeled": 0, "human_vs_deterministic": {"n": 0, "agreement": null, "kappa": null}, "inter_annotator": {"claims": {"n": 0, "agreement": null, "kappa": null}, "runs": {"n": 0, "agreement": null, "kappa": null}}}
