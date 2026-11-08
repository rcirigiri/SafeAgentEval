"""SafeAgentEval command-line interface (black-box / Profile C surface).

Commands:
- ``run``: evaluate a session agent on black-box scenarios, save run records.
- ``explain-scenario`` / ``lint-scenario``: inspect a scenario in plain English.
- ``certify-agent`` / ``certify-state-provider``: Profile C conformance checks.
- ``report`` / ``view`` / ``build-site``: summarize runs, render traces/pages.
- ``new-session-agent``: scaffold a Profile C starter project.
- ``version``: print the installed version.

Mediated execution (AgentAdapter + gate + DomainBackend) was removed from
this surface in the black-box focus; it remains in the library
(``safeagenteval.harness.runner``, ``safeagenteval.pilot``) for research use.
"""

from __future__ import annotations

import asyncio
import importlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, cast

import typer

from safeagenteval import __version__
from safeagenteval.agents.session import SessionAgent
from safeagenteval.backends.state_provider import StateProvider
from safeagenteval.conformance import check_session_agent, check_state_provider
from safeagenteval.core.models import (
    Domain,
    ExecutionMode,
    JsonObject,
    Scenario,
)
from safeagenteval.harness.runner import RunResult
from safeagenteval.harness.session_runner import run_session_scenario
from safeagenteval.mocks.retail_session import reference_session_pair, unsafe_session_pair
from safeagenteval.reporting import build_leaderboard, build_markdown_report, load_run_files
from safeagenteval.reporting.html import render_trace_html
from safeagenteval.scenarios.loader import discover_scenarios, load_scenario
from safeagenteval.trace.recorder import verify_trace

app = typer.Typer(
    help="Evaluate tool-using agents against state-aware safety scenarios.",
    no_args_is_help=True,
)


@app.callback()
def main() -> None:
    """Run SafeAgentEval commands."""


@app.command()
def version() -> None:
    """Print the installed SafeAgentEval version."""
    typer.echo(__version__)


def _import_object(spec: str) -> object:
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise typer.BadParameter(f"expected 'package.module:ClassName', got {spec!r}")
    try:
        return getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as error:
        raise typer.BadParameter(f"cannot import {spec!r}: {error}") from error


SessionPair = tuple[SessionAgent, StateProvider]
_SESSION_SPECS = ("session-reference", "session-unsafe")


def _session_pair_factory(
    spec: str, state_provider_spec: str | None
) -> Callable[[Scenario], SessionPair]:
    """Build (session agent, state provider) pairs for black-box scenarios."""
    if spec == "session-reference":
        return reference_session_pair
    if spec == "session-unsafe":
        return unsafe_session_pair
    agent_class = _import_object(spec)
    if not callable(agent_class) or not callable(getattr(agent_class, "say", None)):
        raise typer.BadParameter(f"{spec} does not implement SessionAgent.say")
    if state_provider_spec is None:
        raise typer.BadParameter(
            "black-box runs with a custom session agent require "
            "--state-provider 'package.module:ClassName'"
        )
    provider_class = _import_object(state_provider_spec)
    if not callable(provider_class):
        raise typer.BadParameter(f"{state_provider_spec} is not callable")

    def build(_scenario: Scenario) -> SessionPair:
        return cast(SessionAgent, agent_class()), cast(StateProvider, provider_class())

    return build


def _run_passed(result: RunResult) -> bool:
    return bool(
        result.completed
        and result.state_score.final_state_correct
        and not result.state_score.unauthorized_action
        and verify_trace(result.events)
    )


@app.command()
def run(
    agent: Annotated[
        str,
        typer.Option(
            help="'session-reference'/'session-unsafe' (black-box demo), "
            "or a SessionAgent 'package.module:ClassName'"
        ),
    ] = "session-reference",
    suite: Annotated[Path, typer.Option(help="Benchmark root directory")] = Path("safeorderbench"),
    scenario: Annotated[
        list[str], typer.Option(help="Scenario id or YAML path (repeatable)")
    ] = [],  # noqa: B006
    category: Annotated[list[str], typer.Option(help="Limit to a category (repeatable)")] = [],  # noqa: B006
    domain: Annotated[str, typer.Option(help="Scenario domain: retail, banking, ...")] = "retail",
    repeats: Annotated[int, typer.Option(help="Runs per scenario; rates aggregate")] = 1,
    state_provider: Annotated[
        str | None,
        typer.Option(help="StateProvider 'package.module:ClassName' for custom session agents"),
    ] = None,
    out: Annotated[Path, typer.Option(help="Directory for run records")] = Path(
        "artifacts/cli_runs"
    ),
) -> None:
    """Run a session agent on black-box scenarios; one JSON record per run.

    The agent is driven by scripted customer utterances and executes its own
    tools internally; the harness seeds and reads its world through a
    StateProvider and grades the final state (Agent Contract Profile C).
    Mediated execution (Paths 1/2) was removed from the CLI surface; the
    mediated library remains available for research use (see
    ``safeagenteval.harness.runner`` and the pilot package).
    """
    try:
        domain_value = Domain(domain)
    except ValueError:
        raise typer.BadParameter(f"unknown domain {domain!r}") from None
    if repeats < 1:
        raise typer.BadParameter("repeats must be at least 1")
    if agent in ("reference", "unsafe"):
        typer.echo(
            f"{agent} is a mediated agent; mediated mode was removed from the CLI. "
            "Use a session agent (Profile C, docs/agent_contract.md).",
            err=True,
        )
        raise typer.Exit(code=2)
    scenarios = discover_scenarios(suite, domain=domain_value, include_versioned=True)
    if scenario:
        # A --scenario value is either a scenario_id or a path to a YAML file.
        selected: dict[str, Scenario] = {}
        for name in scenario:
            candidate = Path(name)
            if candidate.is_file() and candidate.suffix in (".yaml", ".yml"):
                item = load_scenario(candidate, suite)
                selected[item.scenario_id] = item
        for item in scenarios:
            if item.scenario_id in scenario and item.scenario_id not in selected:
                selected[item.scenario_id] = item
        scenarios = tuple(selected.values())
    if category:
        scenarios = tuple(item for item in scenarios if item.category.value in category)
    if not scenarios:
        typer.echo("no scenarios matched", err=True)
        raise typer.Exit(code=2)
    mediated = [
        item.scenario_id for item in scenarios if item.execution_mode is not ExecutionMode.BLACK_BOX
    ]
    if mediated:
        typer.echo(
            "mediated scenarios are not runnable from the CLI (removed in the "
            f"black-box focus): {', '.join(mediated)}",
            err=True,
        )
        raise typer.Exit(code=2)
    build_pair = _session_pair_factory(agent, state_provider)

    out.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    for item in scenarios:
        for repeat in range(repeats):
            session_agent, provider = build_pair(item)
            result = asyncio.run(run_session_scenario(item, session_agent, provider))
            record: dict[str, object] = {
                "scenario_id": result.scenario_id,
                "configuration": result.configuration.value,
                "execution_mode": result.execution_mode.value,
                "repeat": repeat,
                "agent": agent,
                "passed": _run_passed(result),
                "completed": result.completed,
                "aborted_reason": result.aborted_reason,
                "final_state": result.final_state,
                "state_score": result.state_score.model_dump(mode="json"),
                "events": [event.model_dump(mode="json") for event in result.events],
            }
            suffix = "" if repeats == 1 else f".r{repeat + 1}"
            (out / f"{result.scenario_id}{suffix}.json").write_text(
                json.dumps(record, indent=2, sort_keys=True), encoding="utf-8"
            )
            records.append(record)

    board = build_leaderboard(records)
    typer.echo(json.dumps(board, indent=2, sort_keys=True))
    raise typer.Exit(code=0 if board["passed"] == board["runs"] else 1)


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
    accounts = item.initial_state.get("accounts")
    if isinstance(accounts, dict):
        for account_id, account in accounts.items():
            if isinstance(account, dict):
                typer.echo(f"Starting account {account_id}: balance {account.get('balance')}")
    for turn in item.customer_turns:
        typer.echo(f"Customer says ({turn.turn_id}): {turn.message}")
    for intent in item.intents:
        typer.echo(f"Approved action: {intent.tool} {dict(intent.arguments)}")
    typer.echo(f"Acceptable endings: {len(item.authorized_final_states)}")
    for state in item.authorized_final_states:
        state_accounts = state.get("accounts")
        if isinstance(state_accounts, dict):
            for account_id, account in state_accounts.items():
                if isinstance(account, dict):
                    typer.echo(f"  ending account {account_id}: balance {account.get('balance')}")
        transfers = state.get("transfers")
        if isinstance(transfers, list):
            typer.echo(f"  ending transfers: {len(transfers)}")


@app.command("lint-scenario")
def lint_scenario(
    scenario_path: Path,
    benchmark_root: Annotated[Path, typer.Option(help="Benchmark root directory")] = Path(
        "safeorderbench"
    ),
) -> None:
    """Check a scenario loads and is internally consistent."""
    problems: list[str] = []
    try:
        item = load_scenario(scenario_path, benchmark_root)
    except Exception as error:  # noqa: BLE001 - lint reports load failures
        typer.echo(f"INVALID: {type(error).__name__}: {error}")
        raise typer.Exit(code=1) from None
    allowed = set(item.authorization.allowed_tools)
    for intent in item.intents:
        if intent.tool not in allowed:
            problems.append(
                f"intent {intent.intent_id} uses tool {intent.tool} not in allowed_tools"
            )
    intent_ids = {intent.intent_id for intent in item.intents}
    for turn in item.customer_turns:
        if turn.confirms_intent_id is not None and turn.confirms_intent_id not in intent_ids:
            problems.append(
                f"turn {turn.turn_id} confirms unknown intent {turn.confirms_intent_id}"
            )
    if not item.authorized_final_states:
        problems.append("no authorized_final_states")
    if problems:
        for problem in problems:
            typer.echo(f"INVALID: {problem}")
        raise typer.Exit(code=1)
    typer.echo(f"OK: {item.scenario_id}")


@app.command("certify-agent")
def certify_agent(
    agent: Annotated[str, typer.Option(help="Session agent 'package.module:ClassName'")],
    report: Annotated[Path | None, typer.Option(help="Write the JSON report here")] = None,
) -> None:
    """Run the Profile C conformance checks against a SessionAgent adapter."""
    agent_class = _import_object(agent)
    if not callable(agent_class) or not callable(getattr(agent_class, "say", None)):
        raise typer.BadParameter(f"{agent} does not implement SessionAgent.say")

    def factory() -> SessionAgent:
        return cast(SessionAgent, agent_class())

    result = asyncio.run(check_session_agent(factory))
    payload: JsonObject = {
        "agent": agent,
        "subject": result.subject,
        "profile": result.profile.value,
        "passed": result.passed,
        "passed_count": result.passed_count,
        "total_count": result.total_count,
        "checks": [check.model_dump(mode="json") for check in result.checks],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if report is not None:
        report.write_text(text + "\n", encoding="utf-8")
    typer.echo(text)
    raise typer.Exit(code=0 if result.passed else 1)


@app.command("certify-state-provider")
def certify_state_provider(
    provider: Annotated[str, typer.Option(help="StateProvider 'package.module:ClassName'")],
    report: Annotated[Path | None, typer.Option(help="Write the JSON report here")] = None,
) -> None:
    """Run conformance checks against a StateProvider (seed/snapshot/reset)."""
    provider_class = _import_object(provider)
    if not callable(provider_class):
        raise typer.BadParameter(f"{provider} is not callable")

    def factory() -> StateProvider:
        return cast(StateProvider, provider_class())

    result = check_state_provider(factory)
    payload: JsonObject = {
        "provider": provider,
        "subject": result.subject,
        "profile": result.profile.value,
        "passed": result.passed,
        "passed_count": result.passed_count,
        "total_count": result.total_count,
        "checks": [check.model_dump(mode="json") for check in result.checks],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if report is not None:
        report.write_text(text + "\n", encoding="utf-8")
    typer.echo(text)
    raise typer.Exit(code=0 if result.passed else 1)


@app.command()
def report(runs_dir: Path) -> None:
    """Print a Markdown report and leaderboard summary for saved run records."""
    records = load_run_files(runs_dir)
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
    data = json.loads(run_file.read_text(encoding="utf-8"))
    events_data = data.get("events") if isinstance(data, dict) else None
    if not isinstance(events_data, list):
        typer.echo("run file has no events list", err=True)
        raise typer.Exit(code=2)
    from safeagenteval.trace.recorder import TraceEvent

    events = tuple(TraceEvent.model_validate(event) for event in events_data)
    out.write_text(
        render_trace_html(events, title=f"Trace: {data.get('scenario_id', run_file.name)}"),
        encoding="utf-8",
    )
    typer.echo(str(out))


@app.command("build-site")
def build_site(
    runs_dir: Path,
    out: Annotated[Path, typer.Option(help="HTML file to write")] = Path("site/index.html"),
) -> None:
    """Build a static HTML results site from saved run records."""
    from safeagenteval.reporting.site import render_site_html

    records = load_run_files(runs_dir)
    if not records:
        typer.echo("no run records found", err=True)
        raise typer.Exit(code=2)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_site_html(records), encoding="utf-8")
    typer.echo(str(out))


@app.command("new-session-agent")
def new_session_agent(
    name: str, out: Annotated[Path, typer.Option(help="Parent directory")] = Path(".")
) -> None:
    """Scaffold a Profile C starter: session agent + state provider."""
    root = out / name
    package = root / name.replace("-", "_")
    package.mkdir(parents=True, exist_ok=True)
    (package / "__init__.py").write_text('"""Session-agent starter package."""\n', encoding="utf-8")
    (package / "agent.py").write_text(_STARTER_SESSION_AGENT, encoding="utf-8")
    (root / "README.md").write_text(
        f"# {name}\n\nProfile C starter (see docs/agent_contract.md). Certify it with:\n\n"
        f"```bash\nsafeagenteval certify-agent --agent {package.name}.agent:StarterSessionAgent\n"
        f"safeagenteval certify-state-provider "
        f"--provider {package.name}.agent:StarterStateProvider\n"
        "```\n",
        encoding="utf-8",
    )
    typer.echo(str(root))


_STARTER_SESSION_AGENT = '''"""Profile C starter: a session agent plus its state provider.

Replace the echo logic with calls into your agent, and the in-memory
provider with seed/snapshot/reset against your sandbox. See
docs/agent_contract.md (Profile C).
"""

from __future__ import annotations

import copy

from safeagenteval.agents.session import SessionReply
from safeagenteval.core.models import JsonObject


class StarterSessionAgent:
    """Utterance in, reply out; executes its own tools internally."""

    def __init__(self) -> None:
        self._turns = 0

    async def say(self, customer_text: str) -> SessionReply:
        self._turns += 1
        # TODO: forward customer_text to your agent and return its reply.
        # Report structured outcomes as metadata (checked, never trusted).
        return SessionReply(text=f"You said: {customer_text}", metadata={"turns": self._turns})


class StarterStateProvider:
    """Seed, read, and reset your sandbox state for one scenario."""

    def __init__(self) -> None:
        self._state: JsonObject = {}

    def seed(self, initial_state: JsonObject) -> None:
        self._state = copy.deepcopy(initial_state)

    def snapshot(self) -> JsonObject:
        return copy.deepcopy(self._state)

    def reset(self) -> None:
        self._state = {}
'''
