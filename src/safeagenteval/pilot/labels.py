"""Export extracted claims and runs for hand labeling, preserving existing labels.

``claims.csv`` has one row per extracted claim; the annotator judges whether
the extraction is faithful to the reply and whether the verdict is right given
the trace. ``replies.csv`` has one row per reply; the annotator counts claims
the extractor missed, which gives extractor recall. ``runs.csv`` has one row
per run; the annotator applies the judge rubric to the full trace, blind to the
state verdict and to every judge, which gives judge-human agreement.
"""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path

from safeagenteval.claims.verifier import ActionClaim
from safeagenteval.pilot.config import PilotConfig, RunPaths
from safeagenteval.pilot.extraction import ClaimFile
from safeagenteval.pilot.runner import load_run, load_scenarios
from safeagenteval.trace.recorder import EventKind, TraceEvent

CLAIM_LABEL_COLUMNS = ("label_extraction_correct", "label_verdict_correct", "notes")
REPLY_LABEL_COLUMNS = ("label_missed_claims", "notes")
CLAIM_COLUMNS = (
    "claim_key",
    "model",
    "configuration",
    "scenario_id",
    "turn_id",
    "reply_sequence",
    "reply_text",
    "action",
    "status",
    "attributes",
    "verdict",
    "verdict_reason",
    "trace_summary",
    *CLAIM_LABEL_COLUMNS,
)
RUN_LABEL_COLUMNS = ("label_pass", "notes")
RUN_COLUMNS = (
    "run_key",
    "model",
    "configuration",
    "scenario_id",
    "scenario_description",
    "trace_summary",
    *RUN_LABEL_COLUMNS,
)
REPLY_COLUMNS = (
    "reply_key",
    "model",
    "configuration",
    "scenario_id",
    "turn_id",
    "reply_sequence",
    "reply_text",
    "extracted_claims",
    "parse_error",
    *REPLY_LABEL_COLUMNS,
)


def run_key(model: str, configuration: str, scenario_id: str) -> str:
    """Stable key for one run."""
    return f"{model}|{configuration}|{scenario_id}"


def claim_key(model: str, configuration: str, scenario_id: str, claim: ActionClaim) -> str:
    """Stable row key; includes the claim content so re-extraction cannot inherit labels."""
    attributes = json.dumps(claim.attributes, sort_keys=True)
    return (
        f"{model}|{configuration}|{scenario_id}|{claim.claim_id}|{claim.status.value}|{attributes}"
    )


def trace_summary(events: Sequence[TraceEvent], marker_sequence: int | None = None) -> str:
    """Render the run as short lines an annotator can read in a spreadsheet cell."""
    calls: dict[str, str] = {}
    lines: list[str] = []
    for event in events:
        payload = event.payload
        if event.kind is EventKind.CUSTOMER_MESSAGE:
            lines.append(f"[{event.turn_id}] CUSTOMER: {payload.get('message')}")
        elif event.kind is EventKind.AGENT_REPLY:
            here = "  <<< THIS REPLY" if event.sequence == marker_sequence else ""
            lines.append(f"[{event.turn_id}] AGENT: {payload.get('reply')}{here}")
        elif event.kind is EventKind.TOOL_CALL:
            call = payload.get("call")
            if isinstance(call, dict):
                arguments = json.dumps(call.get("normalized_arguments"), sort_keys=True)
                calls[str(call.get("call_id"))] = f"{call.get('name')}({arguments})"
        elif event.kind is EventKind.POLICY_DECISION and payload.get("allowed") is False:
            call_text = calls.get(str(payload.get("call_id")), "?")
            lines.append(f"[{event.turn_id}] BLOCKED {call_text}: {payload.get('reason')}")
        elif event.kind is EventKind.TOOL_RESULT:
            result = payload.get("result")
            if not isinstance(result, dict) or result.get("status") == "denied":
                continue
            call_text = calls.get(str(result.get("call_id")), "?")
            status = result.get("status")
            fault = payload.get("fault")
            if fault is not None:
                visible = payload.get("agent_visible_result")
                shown = visible.get("status") if isinstance(visible, dict) else "?"
                status = f"{status} (agent saw {shown}; fault {fault})"
            committed = " COMMITTED" if result.get("committed") is True else ""
            lines.append(f"[{event.turn_id}] TOOL {call_text} -> {status}{committed}")
        elif event.kind is EventKind.RUN_ABORTED:
            lines.append(f"[{event.turn_id}] RUN ABORTED: {payload.get('reason')}")
    return "\n".join(lines)


def export_run_labels(config: PilotConfig) -> Path:
    """Write ``runs.csv``, one row per saved run, keeping labels already entered."""
    paths = RunPaths(config)
    descriptions = {s.scenario_id: s.description for s in load_scenarios(config)}
    rows: list[dict[str, str]] = []
    for run_path in sorted((paths.root / "runs").glob("*/*/*.json")):
        saved = load_run(run_path)
        scenario_id = saved.result.scenario_id
        rows.append(
            {
                "run_key": run_key(saved.model.name, saved.configuration.value, scenario_id),
                "model": saved.model.name,
                "configuration": saved.configuration.value,
                "scenario_id": scenario_id,
                "scenario_description": " ".join(descriptions.get(scenario_id, "").split()),
                "trace_summary": trace_summary(saved.result.events),
            }
        )
    paths.labels.mkdir(parents=True, exist_ok=True)
    target = paths.labels / "runs.csv"
    _write_merged(target, RUN_COLUMNS, "run_key", RUN_LABEL_COLUMNS, rows)
    return target


def export_labels(config: PilotConfig) -> tuple[Path, Path]:
    """Write ``claims.csv`` and ``replies.csv``, keeping labels already entered."""
    paths = RunPaths(config)
    claim_rows: list[dict[str, str]] = []
    reply_rows: list[dict[str, str]] = []

    for claim_path in sorted((paths.root / "claims").glob("*/*/*.json")):
        claim_file = ClaimFile.model_validate_json(claim_path.read_text(encoding="utf-8"))
        saved = load_run(
            paths.run(claim_file.model, claim_file.configuration, claim_file.scenario_id)
        )
        events = saved.result.events
        replies = {
            event.sequence: str(event.payload.get("reply", ""))
            for event in events
            if event.kind is EventKind.AGENT_REPLY
        }
        run_key = f"{claim_file.model}|{claim_file.configuration.value}|{claim_file.scenario_id}"
        common = {
            "model": claim_file.model,
            "configuration": claim_file.configuration.value,
            "scenario_id": claim_file.scenario_id,
        }
        for verdict in claim_file.verdicts:
            claim = verdict.claim
            attributes = json.dumps(claim.attributes, sort_keys=True)
            claim_rows.append(
                {
                    "claim_key": claim_key(
                        claim_file.model,
                        claim_file.configuration.value,
                        claim_file.scenario_id,
                        claim,
                    ),
                    **common,
                    "turn_id": claim.turn_id,
                    "reply_sequence": str(claim.reply_sequence),
                    "reply_text": replies.get(claim.reply_sequence, ""),
                    "action": claim.action,
                    "status": claim.status.value,
                    "attributes": attributes,
                    "verdict": verdict.verdict.value,
                    "verdict_reason": verdict.reason,
                    "trace_summary": trace_summary(events, claim.reply_sequence),
                }
            )
        for record in claim_file.records:
            extracted = [
                f"{v.claim.status.value} {json.dumps(v.claim.attributes, sort_keys=True)}"
                for v in claim_file.verdicts
                if v.claim.reply_sequence == record.reply_sequence
            ]
            reply_rows.append(
                {
                    "reply_key": f"{run_key}|reply-{record.reply_sequence}",
                    **common,
                    "turn_id": record.turn_id,
                    "reply_sequence": str(record.reply_sequence),
                    "reply_text": replies.get(record.reply_sequence, ""),
                    "extracted_claims": "\n".join(extracted),
                    "parse_error": record.parse_error or "",
                }
            )

    paths.labels.mkdir(parents=True, exist_ok=True)
    claims_csv = paths.labels / "claims.csv"
    replies_csv = paths.labels / "replies.csv"
    _write_merged(claims_csv, CLAIM_COLUMNS, "claim_key", CLAIM_LABEL_COLUMNS, claim_rows)
    _write_merged(replies_csv, REPLY_COLUMNS, "reply_key", REPLY_LABEL_COLUMNS, reply_rows)
    return claims_csv, replies_csv


def read_rows(path: Path) -> list[dict[str, str]]:
    """Read a labeling CSV; a missing file has no rows."""
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_merged(
    path: Path,
    columns: Sequence[str],
    key: str,
    label_columns: Sequence[str],
    rows: list[dict[str, str]],
) -> None:
    existing = {row.get(key, ""): row for row in read_rows(path)}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            previous = existing.get(row[key], {})
            writer.writerow({**row, **{c: previous.get(c, "") for c in label_columns}})
