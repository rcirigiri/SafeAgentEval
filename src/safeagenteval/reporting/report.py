"""Saved run records and their aggregation into reports.

The CLI writes one ``SavedRunRecord`` JSON file per run; reporting reads
only that model. Writer and reader share the schema by construction, so
record fields cannot drift apart.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from safeagenteval.claims.verifier import ActionClaim, ClaimVerdict
from safeagenteval.core.models import FrozenModel, JsonObject
from safeagenteval.scoring.state import StateScore
from safeagenteval.trace.recorder import TraceEvent


class SavedRunRecord(FrozenModel):
    """One saved black-box run: trace, score, and verdict."""

    scenario_id: str
    execution_mode: Literal["black_box"] = "black_box"
    repeat: int = 0
    run_id: str = ""
    attempts: int = 1
    agent: str
    passed: bool
    completed: bool
    aborted_reason: str | None = None
    final_state: JsonObject
    state_score: StateScore
    events: tuple[TraceEvent, ...]
    claims: tuple[ActionClaim, ...] = ()
    claim_verdicts: tuple[ClaimVerdict, ...] = ()
    reply_violations: tuple[str, ...] = ()
    invariant_violations: tuple[str, ...] = ()
    # Trust provenance (docs/trust_model.md): who operated the
    # StateProvider, and hashes binding this record to the exact scenario
    # content and final snapshot it was graded from.
    provider_trust: Literal["harness", "auditor", "self_reported"] = "self_reported"
    snapshot_hash: str = ""
    scenario_sha256: str = ""


def load_run_files(runs_dir: Path) -> list[SavedRunRecord]:
    """Load every valid ``*.json`` run record directly under ``runs_dir``."""
    records: list[SavedRunRecord] = []
    for path in sorted(runs_dir.glob("*.json")):
        try:
            records.append(SavedRunRecord.model_validate_json(path.read_text(encoding="utf-8")))
        except (OSError, ValidationError, json.JSONDecodeError):
            continue
    return records


def build_leaderboard(records: list[SavedRunRecord]) -> dict[str, object]:
    """Summarize run records into a comparable aggregate."""
    total = len(records)
    passed = sum(1 for record in records if record.passed)
    per_scenario: dict[str, list[bool]] = {}
    for record in records:
        per_scenario.setdefault(record.scenario_id, []).append(record.passed)
    return {
        "runs": total,
        "passed": passed,
        "pass_rate": round(passed / total, 4) if total else 0.0,
        "scenarios": sorted(per_scenario),
        "scenario_pass_rates": {
            scenario_id: round(sum(outcomes) / len(outcomes), 4)
            for scenario_id, outcomes in sorted(per_scenario.items())
        },
    }


def build_markdown_report(records: list[SavedRunRecord]) -> str:
    """Render run records as a small Markdown table."""
    board = build_leaderboard(records)
    lines = [
        "# SafeAgentEval report",
        "",
        f"Runs: {board['runs']}  Passed: {board['passed']}  Pass rate: {board['pass_rate']}",
        "",
        "| Scenario | Execution mode | Provider trust | Passed | Final state correct |",
        "|---|---|---|---|---|",
    ]
    for record in records:
        lines.append(
            f"| {record.scenario_id} | {record.execution_mode} | {record.provider_trust} "
            f"| {record.passed} | {record.state_score.final_state_correct} |"
        )
    return "\n".join(lines) + "\n"
