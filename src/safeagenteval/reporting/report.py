"""Aggregate saved CLI run files into a Markdown report and leaderboard JSON."""

from __future__ import annotations

import json
from pathlib import Path


def load_run_files(runs_dir: Path) -> list[dict[str, object]]:
    """Load every ``*.json`` run record directly under ``runs_dir``."""
    records: list[dict[str, object]] = []
    for path in sorted(runs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and "scenario_id" in data and "state_score" in data:
            records.append(data)
    return records


def build_leaderboard(records: list[dict[str, object]]) -> dict[str, object]:
    """Summarize run records into a comparable aggregate."""
    total = len(records)
    passed = sum(1 for record in records if record.get("passed") is True)
    unauthorized = 0
    per_scenario: dict[str, list[bool]] = {}
    for record in records:
        score = record.get("state_score")
        if isinstance(score, dict) and score.get("unauthorized_action") is True:
            unauthorized += 1
        scenario_id = record.get("scenario_id")
        if isinstance(scenario_id, str):
            per_scenario.setdefault(scenario_id, []).append(record.get("passed") is True)
    return {
        "runs": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "unauthorized_runs": unauthorized,
        "scenarios": sorted(per_scenario),
        "scenario_pass_rates": {
            scenario_id: round(sum(outcomes) / len(outcomes), 4)
            for scenario_id, outcomes in sorted(per_scenario.items())
        },
    }


def build_markdown_report(records: list[dict[str, object]]) -> str:
    """Render run records as a small Markdown table."""
    board = build_leaderboard(records)
    lines = [
        "# SafeAgentEval report",
        "",
        f"Runs: {board['runs']}  Passed: {board['passed']}  "
        f"Pass rate: {board['pass_rate']}  Unauthorized runs: {board['unauthorized_runs']}",
        "",
        "| Scenario | Configuration | Passed | Final state | Unauthorized | Commits |",
        "|---|---|---|---|---|---|",
    ]
    for record in records:
        score = record.get("state_score")
        score = score if isinstance(score, dict) else {}
        lines.append(
            f"| {record.get('scenario_id')} | {record.get('configuration')} "
            f"| {record.get('passed')} | {score.get('final_state_correct')} "
            f"| {score.get('unauthorized_action')} | {score.get('successful_commits')} |"
        )
    return "\n".join(lines) + "\n"
