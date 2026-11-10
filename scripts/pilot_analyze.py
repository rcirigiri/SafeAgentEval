"""Analyze the black-box pilot artifacts (``artifacts/pilot/blackbox_v1``).

Offline research script. Reports, from the saved records and judgements:

- deterministic pass rates per agent model (overall, benign vs.
  adversarial, per category);
- claim counts and automated verdicts, plus — once the labeling sheets
  are filled — extraction/verdict accuracy, confirmed contradictions,
  extractor missed claims, and judge-vs-human agreement with Cohen's
  kappa (including second-annotator kappa when ``*_second.csv`` exist);
- judge-vs-deterministic agreement per judge and visibility (always
  computable; the deterministic verdict is the reference).

Unlabeled rows are reported as unlabeled, never as agreement.

    python scripts/pilot_analyze.py [--pilot-dir artifacts/pilot/blackbox_v1]
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path

from safeagenteval.core.models import Domain
from safeagenteval.reporting import SavedRunRecord, load_records
from safeagenteval.scenarios.loader import discover_scenarios

_YES = {"y", "yes", "true", "1", "correct", "pass", "passed"}
_NO = {"n", "no", "false", "0", "incorrect", "fail", "failed"}


def _bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in _YES:
        return True
    if normalized in _NO:
        return False
    return None


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def _kappa(pairs: list[tuple[bool, bool]]) -> float | None:
    if not pairs:
        return None
    total = len(pairs)
    observed = sum(1 for a, b in pairs if a == b) / total
    first = sum(1 for a, _ in pairs if a) / total
    second = sum(1 for _, b in pairs if b) / total
    expected = first * second + (1 - first) * (1 - second)
    if expected >= 1.0:
        return 1.0 if observed >= 1.0 else None
    return round((observed - expected) / (1 - expected), 4)


def _agreement(pairs: list[tuple[bool, bool]]) -> dict[str, object]:
    if not pairs:
        return {"n": 0, "agreement": None, "kappa": None}
    return {
        "n": len(pairs),
        "agreement": round(sum(1 for a, b in pairs if a == b) / len(pairs), 4),
        "kappa": _kappa(pairs),
    }


def _rate(records: list[SavedRunRecord]) -> float | None:
    return round(sum(r.passed for r in records) / len(records), 4) if records else None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot-dir", type=Path, default=Path("artifacts/pilot/blackbox_v1"))
    args = parser.parse_args()
    pilot_dir: Path = args.pilot_dir
    root = Path(__file__).resolve().parents[1]
    scenarios = {
        s.scenario_id: s for s in discover_scenarios(root / "safeorderbench", domain=Domain.BANKING)
    }

    records_by_agent: dict[str, list[SavedRunRecord]] = {}
    runs_root = pilot_dir / "runs"
    if runs_root.exists():
        for agent_dir in sorted(runs_root.iterdir()):
            if agent_dir.is_dir():
                records_by_agent[agent_dir.name] = load_records(agent_dir)

    agents: dict[str, object] = {}
    deterministic: dict[tuple[str, str, int], bool] = {}
    for agent, records in records_by_agent.items():
        benign = [r for r in records if scenarios[r.scenario_id].kind.value == "benign"]
        adversarial = [r for r in records if scenarios[r.scenario_id].kind.value == "adversarial"]
        per_category: dict[str, dict[str, object]] = {}
        grouped: dict[str, list[SavedRunRecord]] = defaultdict(list)
        for record in records:
            grouped[scenarios[record.scenario_id].category.value].append(record)
            deterministic[(agent, record.scenario_id, record.repeat)] = record.passed
        for category, subset in sorted(grouped.items()):
            per_category[category] = {"runs": len(subset), "pass_rate": _rate(subset)}
        agents[agent] = {
            "runs": len(records),
            "pass_rate": _rate(records),
            "benign_pass_rate": _rate(benign),
            "adversarial_pass_rate": _rate(adversarial),
            "claims": sum(len(r.claims) for r in records),
            "claims_contradicted": sum(
                1 for r in records for v in r.claim_verdicts if v.verdict.value == "contradicted"
            ),
            "reply_violations": sum(len(r.reply_violations) for r in records),
            "per_category": per_category,
        }

    # Judge agreement with the deterministic verdict (always computable).
    judge_rows: dict[str, dict[str, object]] = {}
    judgements_root = pilot_dir / "judgements"
    judge_pairs: dict[tuple[str, str], list[tuple[bool, bool]]] = defaultdict(list)
    if judgements_root.exists():
        for path in judgements_root.rglob("*.json"):
            parts = path.relative_to(judgements_root).parts
            if len(parts) != 4:
                continue
            judge_name, visibility, agent, filename = parts
            payload = json.loads(path.read_text(encoding="utf-8"))
            assessment = payload.get("assessment") or {}
            verdict = assessment.get("verdict")
            if verdict not in {"pass", "fail"}:
                continue
            scenario_id = filename.rsplit(".r", 1)[0]
            repeat = int(filename.rsplit(".r", 1)[1].split(".")[0]) - 1
            reference = deterministic.get((agent, scenario_id, repeat))
            if reference is not None:
                judge_pairs[(judge_name, visibility)].append((reference, verdict == "pass"))
    for key, pairs in sorted(judge_pairs.items()):
        judge_rows[f"{key[0]}|{key[1]}"] = _agreement(pairs)

    # Human labeling (pending until the sheets are filled).
    labels_dir = pilot_dir / "labels"
    claim_rows = _rows(labels_dir / "claims.csv")
    extraction = [
        v for r in claim_rows if (v := _bool(r.get("label_extraction_correct"))) is not None
    ]
    verdict_labels = [
        v for r in claim_rows if (v := _bool(r.get("label_verdict_correct"))) is not None
    ]
    confirmed = rejected = unlabeled_contradictions = 0
    for row in claim_rows:
        if row.get("verdict", "").strip().lower() != "contradicted":
            continue
        ok_e, ok_v = (
            _bool(row.get("label_extraction_correct")),
            _bool(row.get("label_verdict_correct")),
        )
        if ok_e and ok_v:
            confirmed += 1
        elif ok_e is False or ok_v is False:
            rejected += 1
        else:
            unlabeled_contradictions += 1
    reply_rows = _rows(labels_dir / "replies.csv")
    missed = [
        r
        for r in reply_rows
        if (r.get("label_missed_claims") or "").strip().lower() not in {"", "none", "0", "no", "[]"}
    ]
    run_rows = _rows(labels_dir / "runs.csv")
    human_pairs: list[tuple[bool, bool]] = []
    for row in run_rows:
        label = _bool(row.get("label_pass"))
        if label is None:
            continue
        parts = row.get("run_key", "").split("|")
        if len(parts) != 3:
            continue
        agent, scenario_id, repeat_part = parts
        reference = deterministic.get((agent, scenario_id, int(repeat_part[1:]) - 1))
        if reference is not None:
            human_pairs.append((label, reference))
    inter: dict[str, object] = {}
    for sheet, column, key in (
        ("claims", "label_extraction_correct", "claim_key"),
        ("runs", "label_pass", "run_key"),
    ):
        first = {r.get(key, ""): _bool(r.get(column)) for r in _rows(labels_dir / f"{sheet}.csv")}
        second = {
            r.get(key, ""): _bool(r.get(column)) for r in _rows(labels_dir / f"{sheet}_second.csv")
        }
        pairs = [
            (first[k], second[k])  # type: ignore[misc]
            for k in first.keys() & second.keys()
            if first[k] is not None and second[k] is not None
        ]
        inter[sheet] = _agreement(pairs)  # type: ignore[arg-type]

    analysis: dict[str, object] = {
        "pilot": "blackbox_v1",
        "agents": agents,
        "judge_vs_deterministic": judge_rows,
        "labels": {
            "claims_total": len(claim_rows),
            "extraction_labeled": len(extraction),
            "extraction_accuracy": round(sum(extraction) / len(extraction), 4)
            if extraction
            else None,
            "verdict_labeled": len(verdict_labels),
            "verdict_accuracy": round(sum(verdict_labels) / len(verdict_labels), 4)
            if verdict_labels
            else None,
            "contradictions_confirmed": confirmed,
            "contradictions_rejected": rejected,
            "contradictions_unlabeled": unlabeled_contradictions,
            "replies_total": len(reply_rows),
            "replies_with_missed_claims_labeled": len(missed),
            "runs_total": len(run_rows),
            "runs_labeled": len(human_pairs),
            "human_vs_deterministic": _agreement(human_pairs),
            "inter_annotator": inter,
        },
    }
    pilot_dir.mkdir(parents=True, exist_ok=True)
    (pilot_dir / "analysis.json").write_text(
        json.dumps(analysis, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Black-box pilot analysis (pilot: blackbox_v1)",
        "",
        "| Agent | Runs | Pass rate | Benign | Adversarial | Claims | Contradicted |",
        "|---|---|---|---|---|---|---|",
    ]
    for agent, stats in agents.items():
        s = stats  # type: ignore[assignment]
        lines.append(
            f"| {agent} | {s['runs']} | {s['pass_rate']} | {s['benign_pass_rate']} "
            f"| {s['adversarial_pass_rate']} | {s['claims']} | {s['claims_contradicted']} |"
        )
    lines += ["", "Judge vs deterministic:", ""]
    for key, value in judge_rows.items():
        lines.append(f"- {key}: {value}")
    lines += ["", f"Labeling: {json.dumps(analysis['labels'])}", ""]
    (pilot_dir / "analysis.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
