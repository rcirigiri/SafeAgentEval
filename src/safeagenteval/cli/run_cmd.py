"""The ``run`` command: evaluate a session agent on black-box scenarios."""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, cast

import typer

from safeagenteval.agents.session import SessionAgent
from safeagenteval.backends.state_provider import StateProvider
from safeagenteval.claims.llm_extractor import LLMClaimExtractor
from safeagenteval.cli.common import import_object, parse_model_spec
from safeagenteval.core.models import Domain, Scenario
from safeagenteval.harness.session_runner import run_session_scenario
from safeagenteval.llm.client import ModelSpec, build_client
from safeagenteval.llm.prompts import CLAIM_EXTRACTOR_PROMPT
from safeagenteval.mocks.banking_session import reference_session_pair, unsafe_session_pair
from safeagenteval.reporting import RecordSink, SavedRunRecord, build_leaderboard, build_sink
from safeagenteval.scenarios.loader import discover_scenarios, load_scenario

SessionPair = tuple[SessionAgent, StateProvider]


def _session_pair_factory(
    spec: str, state_provider_spec: str | None
) -> Callable[[Scenario], SessionPair]:
    """Build (session agent, state provider) pairs for black-box scenarios."""
    if spec == "session-reference":
        return reference_session_pair
    if spec == "session-unsafe":
        return unsafe_session_pair
    agent_class = import_object(spec)
    if not callable(agent_class) or not callable(getattr(agent_class, "say", None)):
        raise typer.BadParameter(f"{spec} does not implement SessionAgent.say")
    if state_provider_spec is None:
        raise typer.BadParameter(
            "black-box runs with a custom session agent require "
            "--state-provider 'package.module:ClassName'"
        )
    provider_class = import_object(state_provider_spec)
    if not callable(provider_class):
        raise typer.BadParameter(f"{state_provider_spec} is not callable")

    def build(_scenario: Scenario) -> SessionPair:
        return cast(SessionAgent, agent_class()), cast(StateProvider, provider_class())

    return build


def _select_scenarios(
    suite: Path, domain: Domain, requested: list[str], category: list[str]
) -> tuple[Scenario, ...]:
    scenarios = discover_scenarios(suite, domain=domain)
    if requested:
        selected: dict[str, Scenario] = {}
        unknown: list[str] = []
        by_id = {item.scenario_id: item for item in scenarios}
        for name in requested:
            candidate = Path(name)
            if candidate.is_file() and candidate.suffix in (".yaml", ".yml"):
                item = load_scenario(candidate, suite)
                selected[item.scenario_id] = item
            elif name in by_id:
                selected[name] = by_id[name]
            else:
                unknown.append(name)
        if unknown:
            raise typer.BadParameter(f"unknown scenario(s): {', '.join(unknown)}")
        scenarios = tuple(selected.values())
    if category:
        scenarios = tuple(item for item in scenarios if item.category.value in category)
    return scenarios


async def _run_all(
    scenarios: tuple[Scenario, ...],
    repeats: int,
    build_pair: Callable[[Scenario], SessionPair],
    agent_label: str,
    sink: RecordSink,
    extractor_spec: ModelSpec | None = None,
    *,
    concurrency: int = 1,
    retries: int = 0,
    retry_backoff: float = 1.0,
) -> list[SavedRunRecord]:
    """Run every scenario/repeat; write one record each to ``sink``.

    Runs are independent: up to ``concurrency`` execute at once, each with
    its own fresh agent/provider pair and its own ``run_id``. A run that
    aborts (agent, extractor, or provider raised) is retried with a fresh
    pair up to ``retries`` times with exponential backoff; a completed run
    that merely fails grading is never retried. Records are returned in
    scenario/repeat order regardless of completion order.
    """
    extractor_client = build_client(extractor_spec) if extractor_spec is not None else None
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(item: Scenario, repeat: int) -> SavedRunRecord:
        async with semaphore:
            attempts = 0
            while True:
                attempts += 1
                run_id = uuid.uuid4().hex
                extractor = (
                    LLMClaimExtractor(
                        extractor_client,
                        CLAIM_EXTRACTOR_PROMPT,
                        json.dumps(item.initial_state, sort_keys=True),
                    )
                    if extractor_client is not None
                    else None
                )
                session_agent, provider = build_pair(item)
                result = await run_session_scenario(
                    item, session_agent, provider, claim_extractor=extractor, run_id=run_id
                )
                if result.completed or attempts > retries:
                    break
                await asyncio.sleep(retry_backoff * (2 ** (attempts - 1)))
            record = SavedRunRecord(
                scenario_id=result.scenario_id,
                repeat=repeat,
                run_id=run_id,
                attempts=attempts,
                agent=agent_label,
                passed=result.passed,
                completed=result.completed,
                aborted_reason=result.aborted_reason,
                final_state=result.final_state,
                state_score=result.state_score,
                events=result.events,
                claims=result.claims,
                claim_verdicts=result.claim_verdicts,
                reply_violations=result.reply_violations,
            )
            sink.write(record)
            return record

    try:
        tasks = [
            asyncio.create_task(one(item, repeat))
            for item in scenarios
            for repeat in range(repeats)
        ]
        return list(await asyncio.gather(*tasks))
    finally:
        sink.close()


def register(app: typer.Typer) -> None:
    """Register the ``run`` command on ``app``."""

    @app.command()
    def run(
        agent: Annotated[
            str,
            typer.Option(
                help="'session-reference'/'session-unsafe' (black-box demo), "
                "or a SessionAgent 'package.module:ClassName'"
            ),
        ] = "session-reference",
        suite: Annotated[Path, typer.Option(help="Benchmark root directory")] = Path(
            "safeorderbench"
        ),
        scenario: Annotated[
            list[str], typer.Option(help="Scenario id or YAML path (repeatable)")
        ] = [],  # noqa: B006
        category: Annotated[list[str], typer.Option(help="Limit to a category (repeatable)")] = [],  # noqa: B006
        domain: Annotated[str, typer.Option(help="Scenario domain, e.g. banking")] = "banking",
        repeats: Annotated[int, typer.Option(help="Runs per scenario; rates aggregate")] = 1,
        state_provider: Annotated[
            str | None,
            typer.Option(help="StateProvider 'package.module:ClassName' for custom agents"),
        ] = None,
        extractor_model: Annotated[
            str | None,
            typer.Option(
                help="Extract reply claims with this 'provider:model' "
                "(key from OPENAI_API_KEY / ANTHROPIC_API_KEY)"
            ),
        ] = None,
        extractor_api_key_env: Annotated[
            str | None,
            typer.Option(help="Env var holding the extractor key (default: provider's var)"),
        ] = None,
        extractor_base_url: Annotated[
            str | None,
            typer.Option(help="OpenAI-compatible endpoint URL for the extractor model"),
        ] = None,
        min_pass_rate: Annotated[
            float,
            typer.Option(
                help="Exit 0 only if the aggregate pass rate reaches this "
                "threshold (pre-deployment CI gate)"
            ),
        ] = 1.0,
        concurrency: Annotated[
            int,
            typer.Option(
                help="Max runs in flight at once (each run needs its own "
                "isolated agent/provider pair and sandbox partition)"
            ),
        ] = 1,
        retries: Annotated[
            int,
            typer.Option(help="Retries for aborted runs (fresh pair each attempt)"),
        ] = 0,
        retry_backoff: Annotated[
            float, typer.Option(help="Base seconds for exponential retry backoff")
        ] = 1.0,
        sink: Annotated[
            str, typer.Option(help="Record sink: file (one JSON per run) | sqlite (one DB)")
        ] = "file",
        out: Annotated[Path, typer.Option(help="Directory (file sink) or DB path (sqlite)")] = Path(
            "artifacts/cli_runs"
        ),
    ) -> None:
        """Run a session agent on black-box scenarios; one JSON record per run.

        The agent is driven by scripted customer utterances and executes
        its own tools internally; the harness seeds and reads its world
        through a StateProvider and grades the final state.
        """
        try:
            domain_value = Domain(domain)
        except ValueError:
            raise typer.BadParameter(f"unknown domain {domain!r}") from None
        if repeats < 1:
            raise typer.BadParameter("repeats must be at least 1")
        if concurrency < 1:
            raise typer.BadParameter("concurrency must be at least 1")
        if retries < 0 or retry_backoff < 0:
            raise typer.BadParameter("retries and retry-backoff must be non-negative")
        if not 0.0 < min_pass_rate <= 1.0:
            raise typer.BadParameter("min-pass-rate must be in (0, 1]")
        extractor_spec = (
            parse_model_spec(extractor_model, extractor_api_key_env, extractor_base_url)
            if extractor_model
            else None
        )
        scenarios = _select_scenarios(suite, domain_value, scenario, category)
        if not scenarios:
            typer.echo("no scenarios matched", err=True)
            raise typer.Exit(code=2)
        build_pair = _session_pair_factory(agent, state_provider)

        try:
            record_sink = build_sink(sink, out)
        except ValueError as error:
            raise typer.BadParameter(str(error)) from None
        records = asyncio.run(
            _run_all(
                scenarios,
                repeats,
                build_pair,
                agent,
                record_sink,
                extractor_spec,
                concurrency=concurrency,
                retries=retries,
                retry_backoff=retry_backoff,
            )
        )
        board = build_leaderboard(records)
        typer.echo(json.dumps(board, indent=2, sort_keys=True))
        pass_rate = sum(1 for record in records if record.passed) / len(records)
        raise typer.Exit(code=0 if pass_rate >= min_pass_rate else 1)
