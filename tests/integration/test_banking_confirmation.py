from __future__ import annotations

import asyncio
from itertools import pairwise
from pathlib import Path

from safeagenteval.backends.banking.backend import BankingBackend
from safeagenteval.claims.verifier import ClaimVerdictValue
from safeagenteval.core.models import Configuration, Scenario, ToolStatus
from safeagenteval.harness.runner import run_scenario
from safeagenteval.mocks.banking import (
    BankingMockClaimExtractor,
    FaithfulBankingAgent,
    PrematureCommitBankingAgent,
)
from safeagenteval.scenarios.loader import load_scenario
from safeagenteval.trace.recorder import EventKind

ROOT = Path(__file__).parents[2]
BENCHMARK_ROOT = ROOT / "safeorderbench"
SCENARIO_PATH = (
    BENCHMARK_ROOT / "public" / "banking" / "confirmation_gate" / "transfer_confirmation_001.yaml"
)


def _scenario() -> Scenario:
    return load_scenario(SCENARIO_PATH, BENCHMARK_ROOT)


def test_faithful_agent_passes_c0_vertical_slice() -> None:
    scenario = _scenario()
    result = asyncio.run(
        run_scenario(
            scenario,
            FaithfulBankingAgent(),
            BankingBackend(scenario.initial_state),
            Configuration.C0,
            BankingMockClaimExtractor(),
        )
    )

    assert result.state_score.final_state_correct is True
    assert result.state_score.unauthorized_action is False
    assert result.state_score.successful_commits == 1
    assert result.state_score.blocked_action_attempts == 0
    assert result.claim_verdicts
    assert all(verdict.verdict is ClaimVerdictValue.VERIFIED for verdict in result.claim_verdicts)


def test_c0_detects_premature_commit_and_contradicting_claim() -> None:
    scenario = _scenario()
    result = asyncio.run(
        run_scenario(
            scenario,
            PrematureCommitBankingAgent(),
            BankingBackend(scenario.initial_state),
            Configuration.C0,
            BankingMockClaimExtractor(),
        )
    )

    assert result.state_score.final_state_correct is True
    assert result.state_score.unauthorized_action is True
    assert "committed before trusted confirmation" in result.state_score.violations[0]
    assert any(
        verdict.verdict is ClaimVerdictValue.CONTRADICTED for verdict in result.claim_verdicts
    )


def test_c2_blocks_premature_commit_then_allows_confirmed_commit() -> None:
    scenario = _scenario()
    result = asyncio.run(
        run_scenario(
            scenario,
            PrematureCommitBankingAgent(),
            BankingBackend(scenario.initial_state),
            Configuration.C2,
            BankingMockClaimExtractor(),
        )
    )

    assert result.state_score.final_state_correct is True
    assert result.state_score.unauthorized_action is False
    assert result.state_score.blocked_action_attempts == 1
    assert result.state_score.successful_commits == 1
    assert all(verdict.verdict is ClaimVerdictValue.VERIFIED for verdict in result.claim_verdicts)
    statuses = [
        result_payload.get("status")
        for event in result.events
        if event.kind is EventKind.TOOL_RESULT
        and isinstance(result_payload := event.payload.get("result"), dict)
    ]
    assert statuses.count(ToolStatus.DENIED.value) == 1


def test_trace_is_hash_linked() -> None:
    scenario = _scenario()
    result = asyncio.run(
        run_scenario(
            scenario,
            FaithfulBankingAgent(),
            BankingBackend(scenario.initial_state),
            Configuration.C0,
        )
    )

    assert result.events[0].previous_hash == "GENESIS"
    for previous, current in pairwise(result.events):
        assert current.previous_hash == previous.event_hash
