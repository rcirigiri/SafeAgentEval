from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
GATE = "examples/enterprise/ci_safety_gate.py"
LEGACY_SCENARIO = "banking.confirmation_gate.transfer_confirmation_001"
BANKING_SCENARIO_COUNT = len(list((ROOT / "safeorderbench/public/banking").rglob("*.yaml")))


def _run_example(relative_path: str, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(ROOT / relative_path), *arguments],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def _gate(*arguments: str) -> tuple[int, dict[str, object]]:
    completed = _run_example(GATE, *arguments)
    assert completed.returncode in {0, 1}, completed.stderr
    return completed.returncode, json.loads(completed.stdout)


def test_enterprise_gate_runs_every_banking_scenario_by_default() -> None:
    code, summary = _gate("--agent", "reference")

    assert code == 0
    assert summary["passed"] is True
    assert summary["scenarios_run"] == BANKING_SCENARIO_COUNT
    assert summary["scenarios_passed"] == BANKING_SCENARIO_COUNT


def test_enterprise_gate_rejects_unsafe_agent_without_enforcement() -> None:
    code, summary = _gate("--agent", "unsafe", "--configuration", "C0")

    assert code == 1
    results = summary["results"]
    assert isinstance(results, list)
    failed_kinds = {result["kind"] for result in results if not result["passed"]}
    assert failed_kinds == {"adversarial"}
    assert all(result["unauthorized_action"] for result in results if not result["passed"])


def test_enterprise_gate_rejects_agent_that_relies_on_c2_blocking() -> None:
    code, summary = _gate("--agent", "unsafe", "--configuration", "C2")

    assert code == 1
    results = summary["results"]
    assert isinstance(results, list)
    assert not any(result["unauthorized_action"] for result in results)
    assert all(result["blocked_action_attempts"] for result in results if not result["passed"])


def test_enterprise_gate_can_explicitly_allow_blocked_attempts() -> None:
    code, summary = _gate("--agent", "unsafe", "--configuration", "C2", "--allow-blocked")

    assert code == 0
    assert summary["passed"] is True


def test_enterprise_gate_filters_by_category() -> None:
    code, summary = _gate("--agent", "reference", "--category", "privacy")

    assert code == 0
    results = summary["results"]
    assert isinstance(results, list)
    assert {result["category"] for result in results} == {"privacy"}
    assert summary["scenarios_run"] == 2


def test_enterprise_gate_loads_agent_and_claim_extractor_from_import_specs() -> None:
    code, summary = _gate(
        "--agent",
        "safeagenteval.mocks.banking:FaithfulBankingAgent",
        "--claim-extractor",
        "safeagenteval.mocks.banking:BankingMockClaimExtractor",
        "--scenario",
        LEGACY_SCENARIO,
    )

    assert code == 0
    assert summary["claims_checked"] is True
    assert summary["scenarios_run"] == 1


@pytest.mark.parametrize(
    "arguments",
    [
        ("--agent", "not-a-spec"),
        ("--agent", "safeagenteval.mocks.banking:Missing"),
        ("--scenario", "banking.does_not_exist"),
        ("--claim-extractor", "safeagenteval.mocks.banking:FaithfulBankingAgent"),
    ],
)
def test_enterprise_gate_reports_setup_errors_with_distinct_exit_code(
    arguments: tuple[str, ...],
) -> None:
    completed = _run_example(GATE, *arguments)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert "gate error" in completed.stderr


def test_open_source_example_runs_contributed_scenario() -> None:
    completed = _run_example("examples/open_source/custom_agent_and_scenario.py")

    assert completed.returncode == 0, completed.stderr
    summary = json.loads(completed.stdout)
    assert summary["passed"] is True
    assert summary["trace_verified"] is True


def test_academic_example_runs_full_benchmark_and_findings_hold() -> None:
    completed = _run_example("examples/academic/c0_vs_c2_experiment.py")

    assert completed.returncode == 0, completed.stderr
    record = json.loads(completed.stdout)
    assert record["all_findings_hold"] is True
    assert len(record["scenario_ids"]) == BANKING_SCENARIO_COUNT
    assert [(c["agent"], c["configuration"]) for c in record["conditions"]] == [
        ("reference", "C0"),
        ("reference", "C2"),
        ("unsafe", "C0"),
        ("unsafe", "C2"),
    ]
