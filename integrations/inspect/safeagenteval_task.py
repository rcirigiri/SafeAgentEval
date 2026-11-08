"""Inspect (UK AISI) integration: expose banking scenarios as an Inspect task.

Requires the optional ``inspect_ai`` package; importing this module without it
raises a clear ImportError. Each scenario becomes one sample whose input is
the customer request and whose target is the authorized-completion summary.
Scoring is delegated to SafeAgentEval's deterministic state scorer, not to
string matching: the solver is expected to drive the agent under test, and the
scorer placeholder below documents where a deployment plugs its agent loop.

This module is the integration surface shipped with SafeAgentEval. Running it
inside an Inspect evaluation additionally requires an agent solver configured
for the model under test.
"""

from __future__ import annotations

from pathlib import Path

try:
    from inspect_ai import Task, task
    from inspect_ai.dataset import Sample
except ImportError as error:  # pragma: no cover - optional dependency
    raise ImportError(
        "inspect_ai is required for this integration: pip install inspect-ai"
    ) from error

from safeagenteval.core.models import Domain
from safeagenteval.scenarios.loader import discover_scenarios

BENCHMARK_ROOT = Path(__file__).parents[2] / "safeorderbench"


@task
def safeagenteval_banking() -> Task:
    """One Inspect sample per public banking scenario."""
    samples = []
    for scenario in discover_scenarios(BENCHMARK_ROOT, domain=Domain.BANKING):
        prompt = "\n".join(turn.message for turn in scenario.customer_turns)
        samples.append(
            Sample(
                id=scenario.scenario_id,
                input=prompt,
                target="authorized final state reached with no unauthorized action",
                metadata={
                    "category": scenario.category.value,
                    "kind": scenario.kind.value,
                    "scenario_id": scenario.scenario_id,
                },
            )
        )
    return Task(dataset=samples)
