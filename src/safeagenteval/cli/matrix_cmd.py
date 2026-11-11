"""The ``matrix`` command: run one suite against several agents (vendors).

Each agent gets the identical scenarios, repeats, and grading; records are
written per agent and the summary compares pass rates side by side. This
is the vendor-selection shape: same exam, same conditions, one table.
Agents run one after another (their sandboxes are independent); the runs
inside each agent use the run command's concurrency.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Annotated

import typer

from safeagenteval.cli import run_cmd
from safeagenteval.core.models import Domain
from safeagenteval.reporting import build_leaderboard, build_sink


def _parse_agents(entries: list[str]) -> list[tuple[str, str]]:
    agents: list[tuple[str, str]] = []
    for entry in entries:
        label, separator, spec = entry.partition("=")
        if not separator or not label or not spec:
            raise typer.BadParameter(f"expected 'label=agent-spec', got {entry!r}")
        agents.append((label, spec))
    if not agents:
        raise typer.BadParameter("at least one --agent 'label=spec' is required")
    return agents


def register(app: typer.Typer) -> None:
    """Register the ``matrix`` command on ``app``."""

    @app.command()
    def matrix(
        agent: Annotated[
            list[str],
            typer.Option(help="'label=agent-spec' (repeatable): the vendors to compare"),
        ],
        suite: Annotated[Path, typer.Option(help="Benchmark root directory")] = Path(
            "safeorderbench"
        ),
        domain: Annotated[str, typer.Option(help="Scenario domain, e.g. banking")] = "banking",
        scenario: Annotated[
            list[str], typer.Option(help="Scenario id or YAML path (repeatable)")
        ] = [],  # noqa: B006
        category: Annotated[list[str], typer.Option(help="Limit to a category (repeatable)")] = [],  # noqa: B006
        repeats: Annotated[int, typer.Option(help="Runs per scenario per agent")] = 1,
        concurrency: Annotated[int, typer.Option(help="Max runs in flight per agent")] = 1,
        retries: Annotated[int, typer.Option(help="Retries for aborted runs")] = 0,
        state_provider: Annotated[
            str | None,
            typer.Option(help="StateProvider 'package.module:ClassName' for custom agents"),
        ] = None,
        provider_trust: Annotated[
            str,
            typer.Option(help="Who operated the StateProvider: harness | auditor | self_reported"),
        ] = "self_reported",
        provider_probe: Annotated[
            bool, typer.Option(help="Require a randomized provider probe round-trip per run")
        ] = False,
        min_pass_rate: Annotated[
            float, typer.Option(help="Exit 0 only if every agent reaches this pass rate")
        ] = 1.0,
        sink: Annotated[str, typer.Option(help="Record sink: file | sqlite")] = "file",
        out: Annotated[Path, typer.Option(help="Base output directory")] = Path("artifacts/matrix"),
    ) -> None:
        """Run the same suite against every agent; compare pass rates."""
        agents = _parse_agents(agent)
        try:
            domain_value = Domain(domain)
        except ValueError:
            raise typer.BadParameter(f"unknown domain {domain!r}") from None
        if repeats < 1 or concurrency < 1 or retries < 0:
            raise typer.BadParameter("repeats/concurrency must be >= 1, retries >= 0")
        if not 0.0 < min_pass_rate <= 1.0:
            raise typer.BadParameter("min-pass-rate must be in (0, 1]")
        if provider_trust not in {"harness", "auditor", "self_reported"}:
            raise typer.BadParameter("provider-trust must be harness | auditor | self_reported")
        scenarios = run_cmd._select_scenarios(suite, domain_value, scenario, category)
        if not scenarios:
            typer.echo("no scenarios matched", err=True)
            raise typer.Exit(code=2)

        summary: dict[str, object] = {}
        all_ok = True
        for label, spec in agents:
            build_pair = run_cmd._session_pair_factory(spec, state_provider)
            sink_path = out / label if sink == "file" else out / f"{label}.sqlite"
            try:
                record_sink = build_sink(sink, sink_path)
            except ValueError as error:
                raise typer.BadParameter(str(error)) from None
            records = asyncio.run(
                run_cmd._run_all(
                    scenarios,
                    repeats,
                    build_pair,
                    label,
                    record_sink,
                    concurrency=concurrency,
                    retries=retries,
                    provider_trust=provider_trust,
                    provider_probe=provider_probe,
                )
            )
            board = build_leaderboard(records)
            summary[label] = board
            rate = sum(1 for record in records if record.passed) / len(records)
            all_ok = all_ok and rate >= min_pass_rate
        typer.echo(json.dumps({"agents": summary}, indent=2, sort_keys=True))
        raise typer.Exit(code=0 if all_ok else 1)
