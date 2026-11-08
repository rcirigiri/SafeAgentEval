"""Pilot command line.

python -m safeagenteval.pilot plan experiments/configs/pilot_v1.yaml
python -m safeagenteval.pilot run experiments/configs/pilot_v1.yaml --limit 2
python -m safeagenteval.pilot extract experiments/configs/pilot_v1.yaml
python -m safeagenteval.pilot judge experiments/configs/pilot_v1.yaml --limit 6
python -m safeagenteval.pilot export-labels experiments/configs/pilot_v1.yaml
python -m safeagenteval.pilot analyze experiments/configs/pilot_v1.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from safeagenteval.agents.providers import ModelSpec
from safeagenteval.judges.transcript import JudgeVisibility
from safeagenteval.pilot.analysis import analyze
from safeagenteval.pilot.config import PilotConfig, load_config, load_env_file
from safeagenteval.pilot.extraction import extract_pilot
from safeagenteval.pilot.judging import judge_pilot
from safeagenteval.pilot.labels import export_labels, export_run_labels
from safeagenteval.pilot.runner import RunSummary, plan_runs, run_pilot

PLACEHOLDER = "REPLACE_ME"


def _problems(specs: Sequence[ModelSpec]) -> list[str]:
    """Placeholder model ids and unset key variables (names only, never values)."""
    problems = [
        f"{spec.name}: model id is {PLACEHOLDER}" for spec in specs if spec.model == PLACEHOLDER
    ]
    problems += sorted(
        {
            f"environment variable {spec.api_key_env} is not set"
            for spec in specs
            if not os.environ.get(spec.api_key_env)
        }
    )
    return problems


def _agent_specs(config: PilotConfig, models: tuple[str, ...] | None) -> list[ModelSpec]:
    return [config.model(name) for name in models] if models else list(config.models)


def _judge_specs(config: PilotConfig, judges: tuple[str, ...] | None) -> list[ModelSpec]:
    return [config.judge(name) for name in judges] if judges else list(config.judges)


def _report(summary: RunSummary) -> int:
    print(
        f"completed {summary.completed}, already done {summary.skipped}, "
        f"API failures {len(summary.api_failures)}"
    )
    return 1 if summary.api_failures else 0


def main(argv: list[str] | None = None) -> int:
    """Run one pilot subcommand."""
    parser = argparse.ArgumentParser(prog="python -m safeagenteval.pilot")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "run", "extract", "judge", "export-labels", "analyze"):
        command = commands.add_parser(name)
        command.add_argument("config", type=Path)
        command.add_argument("--models", nargs="+", help="model names from the config")
        if name in ("run", "judge"):
            command.add_argument("--limit", type=int, help="stop after this many new items")
        if name == "judge":
            command.add_argument("--judges", nargs="+", help="judge names from the config")
            command.add_argument(
                "--visibility",
                nargs="+",
                choices=[level.value for level in JudgeVisibility],
                help="limit to these visibility levels",
            )
            command.add_argument("--concurrency", type=int, default=8)
    args = parser.parse_args(argv)

    load_env_file(Path(".env"))
    config = load_config(args.config)
    models = tuple(args.models) if args.models else None

    if args.command == "plan":
        plans = plan_runs(config, models)
        done = Counter(plan.model for plan in plans if plan.done)
        total = Counter(plan.model for plan in plans)
        for model in total:
            print(f"{model}: {done[model]}/{total[model]} runs done")
        specs = [*_agent_specs(config, models), config.extractor, *config.judges]
        for problem in _problems(specs):
            print(f"not ready: {problem}")
        return 0

    if args.command in ("run", "extract", "judge"):
        if args.command == "run":
            specs = _agent_specs(config, models)
        elif args.command == "extract":
            specs = [config.extractor]
        else:
            if not config.judges:
                print("not ready: the config defines no judges", file=sys.stderr)
                return 2
            specs = _judge_specs(config, tuple(args.judges) if args.judges else None)
        problems = _problems(specs)
        for problem in problems:
            print(f"not ready: {problem}", file=sys.stderr)
        if problems:
            return 2
        if args.command == "run":
            return _report(asyncio.run(run_pilot(config, models=models, limit=args.limit)))
        if args.command == "extract":
            return _report(asyncio.run(extract_pilot(config)))
        return _report(
            asyncio.run(
                judge_pilot(
                    config,
                    judges=tuple(args.judges) if args.judges else None,
                    visibilities=(
                        tuple(JudgeVisibility(v) for v in args.visibility)
                        if args.visibility
                        else None
                    ),
                    limit=args.limit,
                    concurrency=args.concurrency,
                )
            )
        )

    if args.command == "export-labels":
        for path in (*export_labels(config), export_run_labels(config)):
            print(f"wrote {path}")
        return 0

    analyze(config)
    print(f"wrote {config.output_dir / 'analysis.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
