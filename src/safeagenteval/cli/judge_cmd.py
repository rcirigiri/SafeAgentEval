"""The ``judge`` command: grade saved run records with an LLM judge.

The judge sees only the configured visibility view of each recorded run
(replies, or replies plus seeded/final state) — never the scenario's
authorized states. Its verdict is reported *alongside* the deterministic
verdict, with agreement flagged; the deterministic verdict remains the
score of record. This command is how judge-versus-deterministic agreement
(the measurement reported in the research) is reproduced externally.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Annotated

import typer

from safeagenteval.cli.common import parse_model_spec
from safeagenteval.judges.llm_judge import LLMJudge
from safeagenteval.judges.transcript import JudgeVisibility
from safeagenteval.llm.client import ModelSpec, build_client
from safeagenteval.llm.prompts import JUDGE_PROMPT
from safeagenteval.reporting import SavedRunRecord, load_records


async def _judge_all(
    records: list[SavedRunRecord],
    spec: ModelSpec,
    visibility: JudgeVisibility,
    concurrency: int = 4,
) -> list[dict[str, object]]:
    judge = LLMJudge(build_client(spec), JUDGE_PROMPT, visibility)
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def one(record: SavedRunRecord) -> dict[str, object]:
        async with semaphore:
            judgement = await judge.judge(record.events)
        judge_passed = judgement.passed
        return {
            "scenario_id": record.scenario_id,
            "repeat": record.repeat,
            "agent": record.agent,
            "deterministic_passed": record.passed,
            "judge_verdict": (judgement.assessment.verdict.value if judgement.assessment else None),
            "judge_agrees": (judge_passed == record.passed) if judge_passed is not None else None,
            "issues": list(judgement.assessment.issues) if judgement.assessment else [],
            "parse_error": judgement.parse_error,
            "model": judgement.response.model,
        }

    return list(await asyncio.gather(*(one(record) for record in records)))


def _sample(records: list[SavedRunRecord], sample_rate: float) -> list[SavedRunRecord]:
    """Deterministically keep a ``sample_rate`` fraction of records.

    Sampling is by stable hash of the run's identity, so re-running the
    judge on the same store judges the same subset.
    """
    if sample_rate >= 1.0:
        return records
    kept: list[SavedRunRecord] = []
    for record in records:
        identity = f"{record.agent}|{record.scenario_id}|{record.repeat}|{record.run_id}"
        fraction = int(hashlib.sha256(identity.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        if fraction < sample_rate:
            kept.append(record)
    return kept


def register(app: typer.Typer) -> None:
    """Register the ``judge`` command on ``app``."""

    @app.command()
    def judge(
        runs: Annotated[Path, typer.Argument(help="Directory of saved run records")],
        model: Annotated[
            str,
            typer.Option(help="'provider:model' (key from OPENAI_API_KEY / ANTHROPIC_API_KEY)"),
        ],
        visibility: Annotated[
            str, typer.Option(help="What the judge sees: replies | with_state")
        ] = "replies",
        sample_rate: Annotated[
            float,
            typer.Option(help="Judge only this fraction of records (deterministic sampling)"),
        ] = 1.0,
        concurrency: Annotated[int, typer.Option(help="Max judge calls in flight at once")] = 4,
        api_key_env: Annotated[
            str | None,
            typer.Option(help="Env var holding the key (default: provider's standard var)"),
        ] = None,
        base_url: Annotated[
            str | None,
            typer.Option(help="OpenAI-compatible endpoint URL (e.g. a hosted open-weight model)"),
        ] = None,
        out: Annotated[
            Path | None, typer.Option(help="Optional file for the JSON judgements")
        ] = None,
    ) -> None:
        """Judge saved runs with an LLM; report agreement with the deterministic verdict."""
        try:
            visibility_value = JudgeVisibility(visibility)
        except ValueError:
            raise typer.BadParameter(
                f"unknown visibility {visibility!r} (replies | with_state)"
            ) from None
        if not 0.0 < sample_rate <= 1.0:
            raise typer.BadParameter("sample-rate must be in (0, 1]")
        if concurrency < 1:
            raise typer.BadParameter("concurrency must be at least 1")
        all_records = load_records(runs)
        if not all_records:
            typer.echo("no run records found", err=True)
            raise typer.Exit(code=2)
        records = _sample(all_records, sample_rate)
        rows = asyncio.run(
            _judge_all(
                records,
                parse_model_spec(model, api_key_env, base_url),
                visibility_value,
                concurrency,
            )
        )
        judged = [row for row in rows if row["judge_agrees"] is not None]
        payload: dict[str, object] = {
            "runs": len(rows),
            "sampled_from": len(all_records),
            "judged": len(judged),
            "agreement_rate": (
                round(sum(1 for row in judged if row["judge_agrees"]) / len(judged), 4)
                if judged
                else 0.0
            ),
            "judgements": rows,
        }
        text = json.dumps(payload, indent=2, sort_keys=True)
        if out is not None:
            out.write_text(text + "\n", encoding="utf-8")
        typer.echo(text)
