"""Shared policy-gate pack: registry invariants and banking suite."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from typer.testing import CliRunner

from safeagenteval.cli import app
from safeagenteval.core.models import Domain, ScenarioKind
from safeagenteval.harness.session_runner import run_session_scenario
from safeagenteval.mocks.banking_session import reference_session_pair, unsafe_session_pair
from safeagenteval.scenarios.loader import discover_scenarios
from safeagenteval.shared_pack import (
    SHARED_GATES,
    GateMode,
    Pillar,
    instantiate,
    validate_shared_pack,
)
from safeagenteval.trace.recorder import verify_trace

ROOT = Path(__file__).parents[2]
SHARED = ROOT / "sharedpack"

ZERO_TOLERANCE_PREFIXES = (
    "shared_pol3",
    "shared_cmp3",
    "shared_saf",
    "shared_pii2",
    "shared_pii3",
    "shared_pii4",
)


def test_registry_is_complete_and_paired() -> None:
    gates = validate_shared_pack()
    assert len(gates) == 16
    for pillar in Pillar:
        assert sum(1 for gate in gates if gate.pillar is pillar) == 4
    scenario_gates = [gate for gate in gates if gate.mode is GateMode.SCENARIO]
    assert len(scenario_gates) == 15
    assert [gate.gate_id for gate in gates if gate.mode is GateMode.CONFORMANCE] == ["CMP-4"]


def test_instantiate_requires_every_slot() -> None:
    gate = next(gate for gate in SHARED_GATES if gate.gate_id == "SAF-2")
    text = instantiate(
        gate.adversarial,
        {"COMMIT": "transfer funds", "DATA_SURFACE": "payee note"},
    )
    assert "transfer funds" in text and "payee note" in text
    with pytest.raises(KeyError):
        instantiate(gate.adversarial, {"COMMIT": "transfer funds"})


def test_shared_pack_cli_lists_gates() -> None:
    result = CliRunner().invoke(app, ["shared-pack", "--pillar", "pii"])
    assert result.exit_code == 0
    for gate_id in ("PII-1", "PII-2", "PII-3", "PII-4"):
        assert gate_id in result.stdout
    assert "POL-1" not in result.stdout


def test_banking_instantiation_covers_every_scenario_gate() -> None:
    scenarios = discover_scenarios(SHARED, domain=Domain.BANKING)
    assert len(scenarios) == 30
    by_name = {scenario.scenario_id.split(".")[-1]: scenario for scenario in scenarios}
    for gate in SHARED_GATES:
        if gate.mode is not GateMode.SCENARIO:
            continue
        assert len(gate.banking_scenarios) == 2, gate.gate_id
        for name in gate.banking_scenarios:
            assert name in by_name, f"{gate.gate_id}: missing {name}"
            scenario = by_name[name]
            assert scenario.category is gate.category
    kinds = {scenario.kind for scenario in scenarios}
    assert kinds == {ScenarioKind.ADVERSARIAL, ScenarioKind.BENIGN}


def test_banking_instantiation_discriminates() -> None:
    async def run_all() -> dict[str, dict[str, bool]]:
        outcomes: dict[str, dict[str, bool]] = {}
        for scenario in discover_scenarios(SHARED, domain=Domain.BANKING):
            outcomes[scenario.scenario_id] = {}
            for label, pair in (
                ("safe", reference_session_pair),
                ("unsafe", unsafe_session_pair),
            ):
                agent, provider = pair(scenario)
                result = await run_session_scenario(scenario, agent, provider)
                assert verify_trace(result.events)  # CMP-4, on every run
                outcomes[scenario.scenario_id][label] = result.passed
        return outcomes

    scenarios = discover_scenarios(SHARED, domain=Domain.BANKING)
    kinds = {scenario.scenario_id: scenario.kind for scenario in scenarios}
    outcomes = asyncio.run(run_all())
    for scenario_id, outcome in outcomes.items():
        name = scenario_id.split(".")[-1]
        assert outcome["safe"], f"safe agent failed {scenario_id}"
        if kinds[scenario_id] is ScenarioKind.ADVERSARIAL and name.startswith(
            ZERO_TOLERANCE_PREFIXES
        ):
            assert not outcome["unsafe"], f"unsafe agent passed zero-tolerance {scenario_id}"
