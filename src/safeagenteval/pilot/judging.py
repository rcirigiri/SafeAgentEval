"""Post-hoc judging of saved runs at each visibility level.

Judging reads saved traces only, so it never re-runs an agent. Like extraction,
it is resumable: a judgement whose file exists is skipped, and an API failure
is not saved, so the next invocation retries it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path

from safeagenteval.agents.chat import ChatClient
from safeagenteval.agents.providers import ModelSpec, build_client
from safeagenteval.core.models import Configuration, FrozenModel
from safeagenteval.judges.llm_judge import Judgement, LLMJudge
from safeagenteval.judges.transcript import JudgeVisibility
from safeagenteval.pilot.config import PilotConfig, RunPaths, sha256_text
from safeagenteval.pilot.runner import RunSummary, load_run

ClientFactory = Callable[[ModelSpec], ChatClient]


class JudgementFile(FrozenModel):
    """One judge's verdict on one saved run."""

    judge: ModelSpec
    judge_prompt_sha256: str
    model: str
    configuration: Configuration
    scenario_id: str
    judgement: Judgement


async def judge_pilot(
    config: PilotConfig,
    *,
    judges: tuple[str, ...] | None = None,
    visibilities: tuple[JudgeVisibility, ...] | None = None,
    limit: int | None = None,
    concurrency: int = 8,
    client_factory: ClientFactory = build_client,
    progress: Callable[[str], None] = print,
) -> RunSummary:
    """Judge every saved run that lacks a judgement, up to ``limit`` new judgements."""
    if config.judge_prompt is None or not config.judges:
        raise ValueError("the config defines no judges")
    paths = RunPaths(config)
    prompt = config.judge_prompt.read_text(encoding="utf-8")
    prompt_hash = sha256_text(prompt)
    specs = [config.judge(name) for name in judges] if judges else list(config.judges)
    levels = visibilities or config.judge_visibilities
    clients: dict[str, ChatClient] = {}

    pending: list[tuple[ModelSpec, JudgeVisibility, Path, Path]] = []
    skipped = 0
    for run_path in sorted((paths.root / "runs").glob("*/*/*.json")):
        model, configuration, scenario_id = (
            run_path.parent.parent.name,
            Configuration(run_path.parent.name),
            run_path.stem,
        )
        for spec in specs:
            for visibility in levels:
                target = paths.judgement(spec.name, visibility, model, configuration, scenario_id)
                if target.exists():
                    skipped += 1
                else:
                    pending.append((spec, visibility, run_path, target))
    if limit is not None:
        pending = pending[:limit]

    semaphore = asyncio.Semaphore(concurrency)
    failures: list[str] = []
    completed = 0

    async def judge_one(
        spec: ModelSpec, visibility: JudgeVisibility, run: Path, target: Path
    ) -> None:
        nonlocal completed
        saved = load_run(run)
        label = (
            f"{spec.name}/{visibility.value}/{saved.model.name}/"
            f"{saved.configuration.value}/{saved.result.scenario_id}"
        )
        if spec.name not in clients:
            clients[spec.name] = client_factory(spec)
        judge = LLMJudge(clients[spec.name], prompt, visibility)
        async with semaphore:
            try:
                judgement = await judge.judge(saved.result.events)
            except Exception as error:  # noqa: BLE001 - retried on the next invocation
                failures.append(f"{label}: {type(error).__name__}: {error}")
                progress(f"judge API failure, will retry next time: {label}: {error}")
                return
        record = JudgementFile(
            judge=spec,
            judge_prompt_sha256=prompt_hash,
            model=saved.model.name,
            configuration=saved.configuration,
            scenario_id=saved.result.scenario_id,
            judgement=judgement,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(record.model_dump_json(indent=2), encoding="utf-8")
        completed += 1
        verdict = judgement.passed
        shown = "unparsed" if verdict is None else ("pass" if verdict else "fail")
        progress(f"judged {label}: {shown}")

    await asyncio.gather(*(judge_one(*item) for item in pending))
    return RunSummary(completed=completed, skipped=skipped, api_failures=tuple(failures))


def load_judgement(path: Path) -> JudgementFile:
    """Load a saved judgement file."""
    return JudgementFile.model_validate_json(path.read_text(encoding="utf-8"))
