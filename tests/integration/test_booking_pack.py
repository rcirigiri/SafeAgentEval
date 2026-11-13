"""SafeBookBench pilot: booking scenarios load and discriminate."""

from __future__ import annotations

import asyncio
from pathlib import Path

from safeagenteval.core.models import Domain, ScenarioKind
from safeagenteval.harness.session_runner import run_session_scenario
from safeagenteval.mocks.booking_session import reference_booking_pair, unsafe_booking_pair
from safeagenteval.scenarios.loader import discover_scenarios

ROOT = Path(__file__).parents[2]
BENCH = ROOT / "safeorderbench"


def test_booking_pack_loads() -> None:
    scenarios = discover_scenarios(BENCH, domain=Domain.BOOKING)
    assert len(scenarios) == 14
    kinds = {scenario.kind for scenario in scenarios}
    assert kinds == {ScenarioKind.ADVERSARIAL, ScenarioKind.BENIGN}


def test_booking_pack_discriminates() -> None:
    async def run_all() -> dict[str, dict[str, bool]]:
        outcomes: dict[str, dict[str, bool]] = {}
        for scenario in discover_scenarios(BENCH, domain=Domain.BOOKING):
            outcomes[scenario.scenario_id] = {}
            for label, pair in (
                ("safe", reference_booking_pair),
                ("unsafe", unsafe_booking_pair),
            ):
                agent, provider = pair(scenario)
                result = await run_session_scenario(scenario, agent, provider)
                outcomes[scenario.scenario_id][label] = result.passed
        return outcomes

    scenarios = discover_scenarios(BENCH, domain=Domain.BOOKING)
    kinds = {scenario.scenario_id: scenario.kind for scenario in scenarios}
    outcomes = asyncio.run(run_all())
    for scenario_id, outcome in outcomes.items():
        assert outcome["safe"], f"safe agent failed {scenario_id}"
        if kinds[scenario_id] is ScenarioKind.ADVERSARIAL:
            assert not outcome["unsafe"], f"unsafe agent passed {scenario_id}"
        else:
            assert outcome["unsafe"], f"unsafe agent failed benign {scenario_id}"
