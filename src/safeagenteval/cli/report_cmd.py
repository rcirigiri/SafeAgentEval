"""The ``report``, ``view``, and ``build-site`` commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from safeagenteval.reporting import build_leaderboard, build_markdown_report, load_records
from safeagenteval.reporting.html import render_trace_html
from safeagenteval.reporting.report import SavedRunRecord
from safeagenteval.reporting.site import render_site_html


def register(app: typer.Typer) -> None:
    """Register the reporting commands on ``app``."""

    @app.command()
    def report(runs_dir: Path) -> None:
        """Print a Markdown report and leaderboard summary for saved runs."""
        records = load_records(runs_dir)
        if not records:
            typer.echo("no run records found", err=True)
            raise typer.Exit(code=2)
        typer.echo(build_markdown_report(records))
        typer.echo(json.dumps(build_leaderboard(records), indent=2, sort_keys=True))

    @app.command()
    def view(
        run_file: Path,
        out: Annotated[Path, typer.Option(help="HTML file to write")] = Path("trace.html"),
    ) -> None:
        """Render a saved run record's trace as a static HTML file."""
        try:
            record = SavedRunRecord.model_validate_json(run_file.read_text(encoding="utf-8"))
        except Exception as error:  # noqa: BLE001 - report invalid records cleanly
            typer.echo(f"invalid run record: {error}", err=True)
            raise typer.Exit(code=2) from None
        out.write_text(
            render_trace_html(record.events, title=f"Trace: {record.scenario_id}"),
            encoding="utf-8",
        )
        typer.echo(str(out))

    @app.command("build-site")
    def build_site(
        runs_dir: Path,
        out: Annotated[Path, typer.Option(help="HTML file to write")] = Path("site/index.html"),
    ) -> None:
        """Build a static HTML results site from saved run records."""
        records = load_records(runs_dir)
        if not records:
            typer.echo("no run records found", err=True)
            raise typer.Exit(code=2)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(render_site_html(records), encoding="utf-8")
        typer.echo(str(out))
