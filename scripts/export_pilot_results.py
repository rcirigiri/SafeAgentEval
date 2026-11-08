"""Export the pilot's per-run and per-cell results for the paper.

Usage:
    python scripts/export_pilot_results.py experiments/configs/pilot_v1.yaml \
        paper/results/pilot_v1.json

Private endpoint URLs are redacted; API keys are never part of the pilot outputs.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from safeagenteval.pilot.analysis import analyze
from safeagenteval.pilot.config import RunPaths, load_config
from safeagenteval.pilot.extraction import ClaimFile
from safeagenteval.pilot.runner import load_run, load_scenarios


def main(config_path: Path, output: Path) -> None:
    config = load_config(config_path)
    paths = RunPaths(config)
    kinds = {s.scenario_id: s.kind.value for s in load_scenarios(config)}
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))

    runs: list[dict[str, Any]] = []
    served: dict[str, set[str]] = {}
    for run_path in sorted((paths.root / "runs").glob("*/*/*.json")):
        saved = load_run(run_path)
        score = saved.result.state_score
        name = saved.model.name
        served.setdefault(name, set()).update(r.model for r in saved.responses if r.model)
        claim_path = paths.claims(name, saved.configuration, saved.result.scenario_id)
        verdicts: Counter[str] = Counter()
        statuses: Counter[str] = Counter()
        if claim_path.exists():
            claim_file = ClaimFile.model_validate_json(claim_path.read_text(encoding="utf-8"))
            verdicts.update(v.verdict.value for v in claim_file.verdicts)
            statuses.update(v.claim.status.value for v in claim_file.verdicts)
        runs.append(
            {
                "model": name,
                "configuration": saved.configuration.value,
                "scenario_id": saved.result.scenario_id,
                "kind": kinds[saved.result.scenario_id],
                "authorized_final_state": score.final_state_correct,
                "unauthorized_action": score.unauthorized_action,
                "blocked_action_attempts": score.blocked_action_attempts,
                "successful_commits": score.successful_commits,
                "violations": list(score.violations),
                "aborted_reason": saved.result.aborted_reason,
                "model_calls": len(saved.responses),
                "claims_by_status": dict(statuses),
                "claims_by_verdict": dict(verdicts),
            }
        )

    models = []
    for model in manifest["config"]["models"]:
        public = {k: v for k, v in model.items() if k != "base_url"}
        if model.get("base_url"):
            public["endpoint"] = "private Hugging Face Inference Endpoint (vLLM)"
        public["served_model_ids"] = sorted(served.get(model["name"], set()))
        models.append(public)

    record = {
        "experiment_id": config.experiment_id,
        "created_at": manifest["created_at"],
        "safeagenteval_version": manifest["safeagenteval_version"],
        "python": manifest["python"],
        "sdk_versions": manifest.get("sdk_versions", {}),
        "agent_prompt_sha256": manifest["agent_prompt_sha256"],
        "extractor_prompt_sha256": manifest["extractor_prompt_sha256"],
        "models": models,
        "extractor": manifest["config"]["extractor"],
        "analysis": analyze(config),
        "runs": runs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {output} ({len(runs)} runs)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]), Path(sys.argv[2]))
