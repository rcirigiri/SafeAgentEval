# Black-box pilot analysis (pilot: blackbox_v1)

| Agent | Runs | Pass rate | Benign | Adversarial | Claims | Contradicted |
|---|---|---|---|---|---|---|
| claude-haiku-5-5 | 32 | 0.6562 | 0.5 | 0.7778 | 54 | 13 |
| claude-opus-5-5 | 32 | 0.7188 | 0.6429 | 0.7778 | 53 | 10 |
| gpt-4.1-mini | 32 | 0.5938 | 0.8571 | 0.3889 | 46 | 4 |

Judge vs deterministic:

- claude-sonnet-5-5|replies: {'n': 96, 'agreement': 0.6875, 'kappa': 0.1474}
- claude-sonnet-5-5|with_state: {'n': 96, 'agreement': 0.7292, 'kappa': 0.2864}
- gpt-6.1-sol|replies: {'n': 96, 'agreement': 0.6875, 'kappa': 0.132}
- gpt-6.1-sol|with_state: {'n': 96, 'agreement': 0.7396, 'kappa': 0.308}

Labeling: {"claims_total": 153, "extraction_labeled": 0, "extraction_accuracy": null, "verdict_labeled": 0, "verdict_accuracy": null, "contradictions_confirmed": 0, "contradictions_rejected": 0, "contradictions_unlabeled": 27, "replies_total": 137, "replies_with_missed_claims_labeled": 0, "runs_total": 96, "runs_labeled": 0, "human_vs_deterministic": {"n": 0, "agreement": null, "kappa": null}, "inter_annotator": {"claims": {"n": 0, "agreement": null, "kappa": null}, "runs": {"n": 0, "agreement": null, "kappa": null}}}
