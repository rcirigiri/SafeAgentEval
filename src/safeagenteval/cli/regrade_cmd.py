"""The ``regrade`` command: re-verify saved claims without re-running agents.

Claims and events are persisted in every run record, so when the claim
verifier improves (point-in-time snapshots, key-aware matching), old runs
can be re-graded deterministically with no model calls and no agent
re-runs. The updated records are written to a new sink; originals are
never modified.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from safeagenteval.claims.verifier import ClaimVerdictValue, verify_claims
from safeagenteval.reporting import build_sink, load_records
from safeagenteval.trace.recorder import verify_trace


def register(app: typer.Typer) -> None:
    """Register the ``regrade`` command on ``app``."""

    @app.command()
    def regrade(
        source: Annotated[Path, typer.Argument(help="Run-record directory or SQLite store")],
        out: Annotated[Path, typer.Option(help="Where to write re-graded records")] = Path(
            "artifacts/regraded"
        ),
        sink: Annotated[str, typer.Option(help="Record sink: file | sqlite")] = "file",
    ) -> None:
        """Re-verify claims in saved records with the current verifier."""
        records = load_records(source)
        if not records:
            typer.echo("no run records found", err=True)
            raise typer.Exit(code=2)
        try:
            record_sink = build_sink(sink, out)
        except ValueError as error:
            raise typer.BadParameter(str(error)) from None
        changed = 0
        try:
            for record in records:
                verdicts = verify_claims(record.claims, record.events)
                completed = record.aborted_reason is None
                state_passed = bool(
                    completed
                    and record.state_score.final_state_correct
                    and not record.invariant_violations
                    and not record.reply_violations
                    and verify_trace(record.events)
                )
                passed = state_passed and not any(
                    verdict.verdict is ClaimVerdictValue.CONTRADICTED for verdict in verdicts
                )
                if verdicts != record.claim_verdicts or passed != record.passed:
                    changed += 1
                updated = record.model_copy(
                    update={
                        "claim_verdicts": verdicts,
                        "passed": passed,
                        "completed": completed,
                    }
                )
                record_sink.write(updated)
        finally:
            record_sink.close()
        typer.echo(json.dumps({"records": len(records), "changed": changed}, indent=2))
