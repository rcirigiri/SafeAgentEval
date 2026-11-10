"""Enterprise scaling: concurrency, retries, async providers, sinks, matrix."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from typer.testing import CliRunner

import safeagenteval.cli.run_cmd as run_cmd
from safeagenteval.agents.session import SessionReply
from safeagenteval.backends.state_provider import InMemoryStateProvider
from safeagenteval.cli import app
from safeagenteval.cli.judge_cmd import _sample
from safeagenteval.core.models import Domain, JsonObject
from safeagenteval.harness.session_runner import run_session_scenario
from safeagenteval.mocks.banking_session import reference_session_pair
from safeagenteval.reporting import FileRecordSink, build_leaderboard, load_records
from safeagenteval.scenarios.loader import discover_scenarios

ROOT = Path(__file__).parents[2]
BENCHMARK = ROOT / "safeorderbench"
BANKING = {s.scenario_id: s for s in discover_scenarios(BENCHMARK, domain=Domain.BANKING)}
runner = CliRunner()


class AsyncProvider:
    """Provider whose seed/snapshot/reset are coroutines (network-shaped)."""

    def __init__(self) -> None:
        self._inner = InMemoryStateProvider()
        self.run_context: str | None = None

    def set_run_context(self, run_id: str | None) -> None:
        self.run_context = run_id

    async def seed(self, initial_state: JsonObject) -> None:
        self._inner.seed(initial_state)

    async def snapshot(self) -> JsonObject:
        return self._inner.snapshot()

    async def reset(self) -> None:
        self._inner.reset()

    @property
    def state(self) -> JsonObject:
        return self._inner.state


def test_async_provider_and_run_context_are_supported() -> None:
    scenario = BANKING["banking.confirmation_gate.benign_transfer_001"]
    provider = AsyncProvider()
    from safeagenteval.mocks.banking_session import BankingDemoAgent

    agent = BankingDemoAgent(provider._inner, safe=True)  # acts on the same world
    result = asyncio.run(run_session_scenario(scenario, agent, provider, run_id="run-123"))
    assert result.passed
    assert provider.run_context == "run-123"
    started = [e for e in result.events if e.kind.value == "run_started"]
    assert started[0].payload["run_id"] == "run-123"


def test_run_all_retries_aborted_runs_with_fresh_pair(tmp_path: Path) -> None:
    scenario = BANKING["banking.confirmation_gate.benign_transfer_001"]

    class FlakyAgent:
        async def say(self, customer_text: str) -> SessionReply:
            del customer_text
            raise RuntimeError("sandbox timeout")

    builds = {"n": 0}

    def build_pair(_scenario):  # type: ignore[no-untyped-def]
        # First attempt's agent always raises (run aborts); the retry gets
        # the working reference pair and completes.
        builds["n"] += 1
        agent, provider = reference_session_pair(scenario)
        if builds["n"] == 1:
            return FlakyAgent(), provider
        return agent, provider

    sink = FileRecordSink(tmp_path)
    records = asyncio.run(
        run_cmd._run_all((scenario,), 1, build_pair, "flaky", sink, retries=1, retry_backoff=0.0)
    )
    assert len(records) == 1
    assert records[0].attempts == 2
    assert records[0].completed and records[0].run_id


def test_cli_concurrency_and_sqlite_sink(tmp_path: Path) -> None:
    db = tmp_path / "runs.sqlite"
    ran = runner.invoke(
        app,
        [
            "run",
            "--agent",
            "session-reference",
            "--scenario",
            "banking.confirmation_gate.benign_transfer_001",
            "--scenario",
            "banking.privacy.own_balance_001",
            "--repeats",
            "2",
            "--concurrency",
            "4",
            "--sink",
            "sqlite",
            "--out",
            str(db),
        ],
    )
    assert ran.exit_code == 0, ran.output
    records = load_records(db)
    assert len(records) == 4
    assert len({record.run_id for record in records}) == 4
    assert build_leaderboard(records)["pass_rate"] == 1.0
    reported = runner.invoke(app, ["report", str(db)])
    assert reported.exit_code == 0, reported.output


def test_matrix_command_compares_agents(tmp_path: Path) -> None:
    out = tmp_path / "matrix"
    ran = runner.invoke(
        app,
        [
            "matrix",
            "--agent",
            "safe=session-reference",
            "--agent",
            "unsafe=session-unsafe",
            "--scenario",
            "banking.confirmation_gate.benign_transfer_001",
            "--scenario",
            "banking.confirmation_gate.transfer_without_confirmation_001",
            "--out",
            str(out),
        ],
    )
    assert ran.exit_code == 1, ran.output  # unsafe agent below the 1.0 gate
    payload = json.loads(ran.output)
    assert payload["agents"]["safe"]["pass_rate"] == 1.0
    assert payload["agents"]["unsafe"]["pass_rate"] == 0.5
    assert (out / "safe").is_dir() and (out / "unsafe").is_dir()


def test_judge_sampling_is_deterministic() -> None:
    scenario = BANKING["banking.confirmation_gate.benign_transfer_001"]
    agent, provider = reference_session_pair(scenario)
    result = asyncio.run(run_session_scenario(scenario, agent, provider))
    from safeagenteval.reporting import SavedRunRecord

    records = [
        SavedRunRecord(
            scenario_id=scenario.scenario_id,
            repeat=i,
            run_id=f"run-{i}",
            agent="stub",
            passed=True,
            completed=True,
            final_state=result.final_state,
            state_score=result.state_score,
            events=result.events,
        )
        for i in range(20)
    ]
    assert _sample(records, 1.0) == records
    first = _sample(records, 0.5)
    assert first == _sample(records, 0.5)  # stable subset
    assert 0 < len(first) < len(records)
