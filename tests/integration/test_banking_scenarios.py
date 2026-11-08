"""Validate every public banking scenario with its scripted reference plans.

Each scenario must be solvable (the safe plan passes under C0 and C2) and, if
adversarial, discriminative (the unsafe plan is flagged under C0 and blocked
under C2). Benign scenarios that require a state change must fail for an agent
that does nothing, so over-refusal is measurable.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from safeagenteval.backends.banking.backend import BankingBackend
from safeagenteval.core.models import (
    Configuration,
    Domain,
    FailureCategory,
    Scenario,
    ScenarioKind,
)
from safeagenteval.harness.runner import RunResult, run_scenario
from safeagenteval.mocks.banking_plans import (
    REFERENCE_PLANS,
    Plan,
    PlanAgent,
    plans_for,
    transfer,
)
from safeagenteval.scenarios.loader import discover_scenarios
from safeagenteval.trace.recorder import EventKind, verify_trace

ROOT = Path(__file__).parents[2]
BENCHMARK_ROOT = ROOT / "safeorderbench"

SCENARIOS = {
    scenario.scenario_id: scenario
    for scenario in discover_scenarios(BENCHMARK_ROOT, domain=Domain.BANKING)
}
ADVERSARIAL = sorted(
    scenario_id
    for scenario_id, scenario in SCENARIOS.items()
    if scenario.kind is ScenarioKind.ADVERSARIAL
)
BENIGN_REQUIRING_ACTION = sorted(
    scenario_id
    for scenario_id, scenario in SCENARIOS.items()
    if scenario.kind is ScenarioKind.BENIGN
    and scenario.initial_state not in scenario.authorized_final_states
)


def _run(scenario: Scenario, plan: Plan, configuration: Configuration) -> RunResult:
    return asyncio.run(
        run_scenario(
            scenario,
            PlanAgent(plan),
            BankingBackend(scenario.initial_state),
            configuration,
        )
    )


def test_every_scenario_has_reference_plans_and_every_plan_has_a_scenario() -> None:
    assert set(SCENARIOS) == set(REFERENCE_PLANS)


def test_seed_set_covers_every_category_with_one_adversarial_and_one_benign() -> None:
    pairs = sorted((scenario.category, scenario.kind) for scenario in SCENARIOS.values())
    expected = sorted((category, kind) for category in FailureCategory for kind in ScenarioKind)
    assert pairs == expected


def test_scenario_files_are_stored_under_their_category() -> None:
    banking_root = BENCHMARK_ROOT / "public" / "banking"
    for path in banking_root.rglob("*.yaml"):
        category = path.parent.name
        assert f"banking.{category}.{path.stem}" in SCENARIOS, path


def test_adversarial_scenarios_have_unsafe_plans_and_benign_ones_do_not() -> None:
    for scenario_id, scenario in SCENARIOS.items():
        has_unsafe = bool(REFERENCE_PLANS[scenario_id].unsafe)
        assert has_unsafe is (scenario.kind is ScenarioKind.ADVERSARIAL), scenario_id


@pytest.mark.parametrize("scenario_id", sorted(SCENARIOS))
@pytest.mark.parametrize("configuration", [Configuration.C0, Configuration.C2])
def test_safe_plan_passes(scenario_id: str, configuration: Configuration) -> None:
    scenario = SCENARIOS[scenario_id]
    result = _run(scenario, plans_for(scenario).safe, configuration)

    assert result.completed
    assert result.state_score.violations == ()
    assert result.state_score.final_state_correct, result.final_state
    assert result.state_score.blocked_action_attempts == 0
    assert verify_trace(result.events)


@pytest.mark.parametrize("scenario_id", ADVERSARIAL)
def test_unsafe_plan_is_flagged_under_c0(scenario_id: str) -> None:
    scenario = SCENARIOS[scenario_id]
    result = _run(scenario, plans_for(scenario).unsafe, Configuration.C0)

    assert result.state_score.unauthorized_action, result.state_score


@pytest.mark.parametrize("scenario_id", ADVERSARIAL)
def test_c2_blocks_the_unsafe_plan_and_keeps_an_authorized_state(scenario_id: str) -> None:
    scenario = SCENARIOS[scenario_id]
    result = _run(scenario, plans_for(scenario).unsafe, Configuration.C2)

    assert result.state_score.violations == ()
    assert result.state_score.blocked_action_attempts >= 1
    assert result.state_score.final_state_correct, result.final_state


@pytest.mark.parametrize("scenario_id", BENIGN_REQUIRING_ACTION)
def test_doing_nothing_fails_benign_scenarios_that_require_action(scenario_id: str) -> None:
    result = _run(SCENARIOS[scenario_id], {}, Configuration.C0)

    assert result.state_score.final_state_correct is False


def test_timeout_after_commit_hides_the_commit_from_the_agent_but_not_the_score() -> None:
    result = _run(
        SCENARIOS["banking.partial_failure.timeout_after_commit_001"],
        {"request": (transfer("t1"),)},
        Configuration.C0,
    )
    payload = next(event.payload for event in result.events if event.kind is EventKind.TOOL_RESULT)

    assert payload["fault"] == "timeout_after_commit"
    assert payload["agent_visible_result"]["status"] == "timeout"  # type: ignore[index,call-overload]
    assert payload["result"]["committed"] is True  # type: ignore[index,call-overload]
    assert result.state_score.successful_commits == 1
    assert result.state_score.final_state_correct


def test_discovery_filters_by_category_and_kind() -> None:
    found = discover_scenarios(
        BENCHMARK_ROOT,
        domain=Domain.BANKING,
        category=FailureCategory.PRIVACY,
        kind=ScenarioKind.ADVERSARIAL,
    )

    assert [scenario.scenario_id for scenario in found] == [
        "banking.privacy.other_customer_balance_001"
    ]
