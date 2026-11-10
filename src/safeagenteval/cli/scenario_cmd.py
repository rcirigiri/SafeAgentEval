"""The ``explain-scenario`` and ``lint-scenario`` commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from safeagenteval.scenarios.loader import load_scenario


def register(app: typer.Typer) -> None:
    """Register the scenario inspection commands on ``app``."""

    @app.command("explain-scenario")
    def explain_scenario(
        scenario_path: Path,
        benchmark_root: Annotated[Path, typer.Option(help="Benchmark root directory")] = Path(
            "safeorderbench"
        ),
    ) -> None:
        """Print a plain-English summary of a scenario."""
        item = load_scenario(scenario_path, benchmark_root)
        typer.echo(
            f"Scenario: {item.scenario_id} "
            f"({item.domain.value}, {item.category.value}, {item.kind.value})"
        )
        typer.echo(f"What it is about: {item.description}")
        typer.echo(f"Starting state: {json.dumps(item.initial_state, sort_keys=True)}")
        for turn in item.customer_turns:
            typer.echo(f"Customer says ({turn.turn_id}): {turn.message}")
        for clarification in item.clarifications:
            typer.echo(f"If asked about '{clarification.match}': {clarification.answer}")
        typer.echo(f"Acceptable endings: {len(item.authorized_final_states)}")
        for state in item.authorized_final_states:
            typer.echo(f"  ending: {json.dumps(state, sort_keys=True)}")

    @app.command("lint-scenario")
    def lint_scenario(
        scenario_path: Path,
        benchmark_root: Annotated[Path, typer.Option(help="Benchmark root directory")] = Path(
            "safeorderbench"
        ),
    ) -> None:
        """Check a scenario loads and passes model validation.

        All consistency rules live in the ``Scenario`` model; a scenario
        that loads is valid, so lint adds no rules of its own.
        """
        try:
            item = load_scenario(scenario_path, benchmark_root)
        except Exception as error:  # noqa: BLE001 - lint reports load failures
            typer.echo(f"INVALID: {type(error).__name__}: {error}")
            raise typer.Exit(code=1) from None
        typer.echo(f"OK: {item.scenario_id}")
