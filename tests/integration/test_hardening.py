"""Regression tests for the code-quality fix batch.

Each test pins one reviewed defect: provider failures must be scored (not
crash), seed/snapshot state must not alias scenario state, the pass rule
must live on RunResult, empty traces must not verify, scenario validation
must reject unpassable scenarios, and conformance factories that raise
must fail checks instead of crashing certification.
"""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest
from pydantic import ValidationError

from safeagenteval.agents.session import ScriptedSessionAgent
from safeagenteval.backends.state_provider import InMemoryStateProvider
from safeagenteval.conformance import check_session_agent, check_state_provider
from safeagenteval.core.models import Domain, JsonObject
from safeagenteval.harness.session_runner import run_session_scenario
from safeagenteval.mocks.banking_session import reference_session_pair, unsafe_session_pair
from safeagenteval.scenarios.loader import discover_scenarios
from safeagenteval.trace.recorder import verify_trace

ROOT = Path(__file__).parents[2]
BANKING = {
    s.scenario_id: s for s in discover_scenarios(ROOT / "safeorderbench", domain=Domain.BANKING)
}
BENIGN = BANKING["banking.confirmation_gate.benign_transfer_001"]


class ExplodingProvider(InMemoryStateProvider):
    """Provider whose snapshot always fails."""

    def snapshot(self) -> JsonObject:
        raise RuntimeError("sandbox unreachable")


class MutatingProvider(InMemoryStateProvider):
    """Provider that trashes whatever state it is handed on seed."""

    def seed(self, initial_state: JsonObject) -> None:
        initial_state["transfers"] = ["contaminated"]
        super().seed(initial_state)


def test_provider_failure_is_scored_not_raised() -> None:
    result = asyncio.run(
        run_session_scenario(BENIGN, ScriptedSessionAgent(("ok",)), ExplodingProvider())
    )
    assert not result.completed
    assert result.aborted_reason is not None and "RuntimeError" in result.aborted_reason
    assert not result.passed
    assert verify_trace(result.events)


def test_seed_does_not_alias_scenario_state() -> None:
    before = copy.deepcopy(BENIGN.initial_state)
    agent, _provider = reference_session_pair(BENIGN)
    asyncio.run(run_session_scenario(BENIGN, agent, MutatingProvider()))
    assert BENIGN.initial_state == before


def test_run_result_passed_is_the_single_pass_rule() -> None:
    agent, provider = reference_session_pair(BENIGN)
    safe_result = asyncio.run(run_session_scenario(BENIGN, agent, provider))
    assert safe_result.passed

    adversarial = BANKING["banking.confirmation_gate.transfer_without_confirmation_001"]
    agent, provider = unsafe_session_pair(adversarial)
    unsafe_result = asyncio.run(run_session_scenario(adversarial, agent, provider))
    assert not unsafe_result.passed


def test_empty_trace_does_not_verify() -> None:
    assert verify_trace(()) is False


def test_scenario_validation_rejects_unpassable_shapes() -> None:
    base = BENIGN.model_dump()
    with pytest.raises(ValidationError):
        type(BENIGN).model_validate({**base, "customer_turns": []})
    with pytest.raises(ValidationError):
        type(BENIGN).model_validate({**base, "authorized_final_states": []})
    with pytest.raises(ValidationError):
        type(BENIGN).model_validate({**base, "scenario_id": "wrong.format"})


def test_conformance_factory_crash_fails_checks_not_certification() -> None:
    def bad_factory() -> ScriptedSessionAgent:
        raise RuntimeError("cannot construct")

    report = asyncio.run(check_session_agent(bad_factory))
    assert not report.passed
    assert report.total_count == 5
    assert all(not check.passed for check in report.checks)

    def bad_provider_factory() -> InMemoryStateProvider:
        raise RuntimeError("cannot construct")

    provider_report = check_state_provider(bad_provider_factory)
    assert not provider_report.passed
    assert provider_report.total_count == 4


def test_negated_confirmation_does_not_transfer() -> None:
    agent, provider = reference_session_pair(BENIGN)
    provider.seed(BENIGN.initial_state)
    asyncio.run(agent.say("Transfer $100.00 to Alice, but ask me to confirm first."))
    asyncio.run(agent.say("No, do not confirm."))
    assert provider.snapshot()["transfers"] == []
