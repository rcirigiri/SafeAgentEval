"""Export harness-validation results that back the paper's validation tables.

Runs every public banking scenario with the scripted reference, unsafe, and
do-nothing agents under C0 and C2, plus the claim-verification study, and
writes one JSON record. Usage::

    python scripts/export_validation_results.py paper/results/harness_validation.json
"""

from __future__ import annotations

import asyncio
import json
import platform
import sys
from pathlib import Path

from safeagenteval import __version__
from safeagenteval.agents.base import AgentAdapter
from safeagenteval.backends.banking.backend import BankingBackend
from safeagenteval.claims.verifier import ClaimVerdictValue
from safeagenteval.core.models import Configuration, Domain, Scenario
from safeagenteval.harness.runner import run_scenario
from safeagenteval.mocks.banking import (
    BankingMockClaimExtractor,
    FaithfulBankingAgent,
    PrematureCommitBankingAgent,
)
from safeagenteval.mocks.banking_plans import PlanAgent, reference_agent, unsafe_agent
from safeagenteval.scenarios.loader import discover_scenarios
from safeagenteval.trace.recorder import verify_trace

ROOT = Path(__file__).parents[1]
BENCHMARK_ROOT = ROOT / "safeorderbench"
CLAIMS_SCENARIO_ID = "banking.confirmation_gate.transfer_confirmation_001"


def _agents(scenario: Scenario) -> dict[str, AgentAdapter]:
    return {
        "reference": reference_agent(scenario),
        "unsafe": unsafe_agent(scenario),
        "do_nothing": PlanAgent({}),
    }


def run_grid() -> list[dict[str, object]]:
    """One row per scenario x agent x configuration."""
    rows: list[dict[str, object]] = []
    for scenario in discover_scenarios(BENCHMARK_ROOT, domain=Domain.BANKING):
        for configuration in (Configuration.C0, Configuration.C2):
            for agent_name, agent in _agents(scenario).items():
                result = asyncio.run(
                    run_scenario(
                        scenario, agent, BankingBackend(scenario.initial_state), configuration
                    )
                )
                rows.append(
                    {
                        "scenario_id": scenario.scenario_id,
                        "category": scenario.category.value,
                        "kind": scenario.kind.value,
                        "agent": agent_name,
                        "configuration": configuration.value,
                        "final_state_correct": result.state_score.final_state_correct,
                        "unauthorized_action": result.state_score.unauthorized_action,
                        "blocked_action_attempts": result.state_score.blocked_action_attempts,
                        "successful_commits": result.state_score.successful_commits,
                        "violations": list(result.state_score.violations),
                        "trace_verified": verify_trace(result.events),
                        "events": len(result.events),
                    }
                )
    return rows


def run_claims_study() -> list[dict[str, object]]:
    """Claim verdicts for the faithful and premature scripted agents."""
    scenario = next(
        s
        for s in discover_scenarios(BENCHMARK_ROOT, domain=Domain.BANKING)
        if s.scenario_id == CLAIMS_SCENARIO_ID
    )
    rows: list[dict[str, object]] = []
    for agent_name, agent_class in (
        ("faithful", FaithfulBankingAgent),
        ("premature", PrematureCommitBankingAgent),
    ):
        for configuration in (Configuration.C0, Configuration.C2):
            result = asyncio.run(
                run_scenario(
                    scenario,
                    agent_class(),
                    BankingBackend(scenario.initial_state),
                    configuration,
                    BankingMockClaimExtractor(),
                )
            )
            rows.append(
                {
                    "agent": agent_name,
                    "configuration": configuration.value,
                    "claims": len(result.claim_verdicts),
                    "verified": sum(
                        v.verdict is ClaimVerdictValue.VERIFIED for v in result.claim_verdicts
                    ),
                    "contradicted": sum(
                        v.verdict is ClaimVerdictValue.CONTRADICTED for v in result.claim_verdicts
                    ),
                    "unauthorized_action": result.state_score.unauthorized_action,
                    "final_state_correct": result.state_score.final_state_correct,
                }
            )
    return rows


def main() -> int:
    """Write the validation record to the path given on the command line."""
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    record = {
        "safeagenteval_version": __version__,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "grid": run_grid(),
        "claims_study": run_claims_study(),
    }
    output = Path(sys.argv[1])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
