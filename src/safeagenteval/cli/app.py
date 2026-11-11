"""SafeAgentEval command-line interface (black-box / Profile C surface).

Commands:
- ``run``: evaluate a session agent on black-box scenarios, save run records.
- ``judge``: grade saved run records with an LLM judge; report agreement.
- ``matrix``: run one suite against several agents (vendors) and compare.
- ``explain-scenario`` / ``lint-scenario``: inspect a scenario in plain English.
- ``certify-agent`` / ``certify-state-provider``: conformance checks.
- ``report`` / ``view`` / ``build-site``: summarize runs, render traces/pages.
- ``new-session-agent``: scaffold a starter project.
- ``version``: print the installed version.

Only black-box execution exists: the harness sends customer utterances to
a session agent, which executes its own tools internally, and grades the
final state read through its StateProvider.
"""

from __future__ import annotations

import typer

from safeagenteval import __version__
from safeagenteval.cli import (
    certify_cmd,
    judge_cmd,
    matrix_cmd,
    regrade_cmd,
    report_cmd,
    run_cmd,
    scaffold,
    scenario_cmd,
)

app = typer.Typer(
    help="Evaluate black-box session agents against state-aware safety scenarios.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Run SafeAgentEval commands (loading a local ``.env`` if present)."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv ships with the [models] extra
        return
    load_dotenv()


@app.command()
def version() -> None:
    """Print the installed SafeAgentEval version."""
    typer.echo(__version__)


run_cmd.register(app)
regrade_cmd.register(app)
judge_cmd.register(app)
matrix_cmd.register(app)
scenario_cmd.register(app)
certify_cmd.register(app)
report_cmd.register(app)
scaffold.register(app)
