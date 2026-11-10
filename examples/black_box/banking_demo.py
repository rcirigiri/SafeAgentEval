"""Black-box demo: run the banking demo agents through SafeOrderBench.

The harness sends scripted customer utterances to each session agent
(``say(text)``), the agent executes its own transfers internally, and the
harness grades the final snapshot read through the StateProvider.
No tools are provided to the agent and no calls are executed by the
harness. Prints a JSON summary; exit code 0 iff the safe agent passes
every scenario and the unsafe agent fails every adversarial one.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from safeagenteval.core.models import Domain, ScenarioKind
from safeagenteval.harness.session_runner import run_session_scenario
from safeagenteval.mocks.banking_session import reference_session_pair, unsafe_session_pair
from safeagenteval.scenarios.loader import discover_scenarios
from safeagenteval.trace.recorder import verify_trace

ROOT = Path(__file__).parents[2]


async def main() -> int:
    scenarios = discover_scenarios(ROOT / "safeorderbench", domain=Domain.BANKING)
    results: list[dict[str, object]] = []
    expectations_hold = True
    for scenario in scenarios:
        for label, pair in (("safe", reference_session_pair), ("unsafe", unsafe_session_pair)):
            agent, provider = pair(scenario)
            result = await run_session_scenario(scenario, agent, provider)
            passed = result.passed
            expected = label == "safe" or scenario.kind is ScenarioKind.BENIGN
            expectations_hold = expectations_hold and passed == expected
            results.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "kind": scenario.kind.value,
                    "agent": label,
                    "passed": passed,
                    "expected_pass": expected,
                    "trace_verified": verify_trace(result.events),
                }
            )
    print(json.dumps({"expectations_hold": expectations_hold, "results": results}, indent=2))
    return 0 if expectations_hold else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
