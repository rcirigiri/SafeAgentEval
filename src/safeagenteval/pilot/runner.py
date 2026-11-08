"""Run real models through the benchmark, saving one trace file per run.

Runs are resumable: a run whose file exists is skipped. A run interrupted by an
API failure is not saved, so the next invocation retries it instead of scoring
an infrastructure error as agent behavior.
"""

from __future__ import annotations

import json
import platform
from collections.abc import Callable
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path

from safeagenteval import __version__
from safeagenteval.agents.chat import ChatAgent, ChatClient, ChatResponse
from safeagenteval.agents.providers import ModelSpec, build_client
from safeagenteval.backends.banking.factory import banking_backend_for
from safeagenteval.core.models import Configuration, Domain, FrozenModel, Scenario
from safeagenteval.harness.runner import RunResult, run_scenario
from safeagenteval.pilot.config import PilotConfig, RunPaths, agent_system_prompt, sha256_text
from safeagenteval.scenarios.loader import discover_scenarios

ClientFactory = Callable[[ModelSpec], ChatClient]


class SavedRun(FrozenModel):
    """What is written for one completed run."""

    model: ModelSpec
    configuration: Configuration
    system_prompt: str
    result: RunResult
    responses: tuple[ChatResponse, ...]


class RunPlan(FrozenModel):
    """One planned run."""

    model: str
    configuration: Configuration
    scenario_id: str
    done: bool


def load_scenarios(config: PilotConfig) -> tuple[Scenario, ...]:
    """Discover the scenarios the pilot covers."""
    if config.domain is not Domain.BANKING:
        raise NotImplementedError("the pilot runner supports the banking domain only")
    return discover_scenarios(config.benchmark_root, domain=config.domain)


def plan_runs(config: PilotConfig, models: tuple[str, ...] | None = None) -> list[RunPlan]:
    """List every model x configuration x scenario run and whether it is done."""
    paths = RunPaths(config)
    selected = models or tuple(model.name for model in config.models)
    for name in selected:
        config.model(name)
    scenarios = load_scenarios(config)
    return [
        RunPlan(
            model=name,
            configuration=configuration,
            scenario_id=scenario.scenario_id,
            done=paths.run(name, configuration, scenario.scenario_id).exists(),
        )
        for name in selected
        for configuration in config.configurations
        for scenario in scenarios
    ]


def write_manifest(config: PilotConfig) -> None:
    """Record the exact configuration, prompts and environment once."""
    paths = RunPaths(config)
    if paths.manifest.exists():
        return
    paths.root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "experiment_id": config.experiment_id,
        "created_at": datetime.now(UTC).isoformat(),
        "safeagenteval_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "sdk_versions": {name: _version(name) for name in ("openai", "anthropic")},
        "config": config.model_dump(mode="json"),
        "agent_prompt_sha256": sha256_text(config.agent_prompt.read_text(encoding="utf-8")),
        "extractor_prompt_sha256": sha256_text(config.extractor_prompt.read_text(encoding="utf-8")),
        "judge_prompt_sha256": (
            sha256_text(config.judge_prompt.read_text(encoding="utf-8"))
            if config.judge_prompt is not None
            else None
        ),
    }
    paths.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")


def _version(distribution: str) -> str | None:
    try:
        return metadata.version(distribution)
    except metadata.PackageNotFoundError:
        return None


class RunSummary(FrozenModel):
    """Counts reported after a pilot invocation."""

    completed: int = 0
    skipped: int = 0
    api_failures: tuple[str, ...] = ()


async def run_pilot(
    config: PilotConfig,
    *,
    models: tuple[str, ...] | None = None,
    limit: int | None = None,
    client_factory: ClientFactory = build_client,
    progress: Callable[[str], None] = print,
) -> RunSummary:
    """Run every pending planned run, up to ``limit`` new runs."""
    write_manifest(config)
    paths = RunPaths(config)
    template = config.agent_prompt.read_text(encoding="utf-8")
    scenarios = {scenario.scenario_id: scenario for scenario in load_scenarios(config)}
    clients: dict[str, ChatClient] = {}
    completed = skipped = 0
    failures: list[str] = []

    for plan in plan_runs(config, models):
        label = f"{plan.model}/{plan.configuration.value}/{plan.scenario_id}"
        if plan.done:
            skipped += 1
            continue
        if limit is not None and completed >= limit:
            break
        spec = config.model(plan.model)
        if spec.name not in clients:
            clients[spec.name] = client_factory(spec)
        scenario = scenarios[plan.scenario_id]
        prompt = agent_system_prompt(template, scenario, config.session_customer_id)
        agent = ChatAgent(clients[spec.name], prompt)
        result = await run_scenario(
            scenario,
            agent,
            banking_backend_for(scenario),
            plan.configuration,
            max_agent_steps_per_customer_turn=config.max_agent_steps_per_customer_turn,
        )
        if agent.api_error is not None:
            failures.append(f"{label}: {agent.api_error}")
            progress(f"API failure, will retry next time: {label}: {agent.api_error}")
            continue
        saved = SavedRun(
            model=spec,
            configuration=plan.configuration,
            system_prompt=prompt,
            result=result,
            responses=tuple(agent.responses),
        )
        target = paths.run(spec.name, plan.configuration, plan.scenario_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(saved.model_dump_json(indent=2), encoding="utf-8")
        completed += 1
        progress(
            f"done {label}: authorized_state={result.state_score.final_state_correct} "
            f"unauthorized={result.state_score.unauthorized_action} "
            f"blocked={result.state_score.blocked_action_attempts}"
        )
    return RunSummary(completed=completed, skipped=skipped, api_failures=tuple(failures))


def load_run(path: Path) -> SavedRun:
    """Load a saved run file."""
    return SavedRun.model_validate_json(path.read_text(encoding="utf-8"))
