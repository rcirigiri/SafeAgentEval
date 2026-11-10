"""SafeOrderBench scenario loading and reference resolution."""

from __future__ import annotations

from pathlib import Path
from typing import cast

import yaml

from safeagenteval.core.models import (
    Domain,
    FailureCategory,
    JsonObject,
    Scenario,
    ScenarioKind,
)


def _load_mapping(path: Path) -> JsonObject:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a mapping")
    return cast(JsonObject, loaded)


def _resolve_inside(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    resolved = (resolved_root / relative_path).resolve()
    if not resolved.is_relative_to(resolved_root):
        raise ValueError(f"reference escapes benchmark root: {relative_path}")
    return resolved


def load_scenario(path: Path, benchmark_root: Path) -> Scenario:
    """Load a scenario and resolve its initial-state reference."""
    raw = _load_mapping(path)
    initial_state_ref = raw.pop("initial_state_ref", None)
    if not isinstance(initial_state_ref, str):
        raise ValueError(f"{path} must define initial_state_ref")

    initial_state_path = _resolve_inside(
        benchmark_root / "initial_states",
        initial_state_ref,
    )
    raw["initial_state"] = _load_mapping(initial_state_path)
    return Scenario.model_validate(raw)


def discover_scenarios(
    benchmark_root: Path,
    *,
    domain: Domain | None = None,
    category: FailureCategory | None = None,
    kind: ScenarioKind | None = None,
) -> tuple[Scenario, ...]:
    """Load every public scenario, optionally filtered, sorted by ``scenario_id``.

    Raises ``ValueError`` if two files declare the same ``scenario_id``.
    """
    public_root = benchmark_root / "public"
    if domain is not None:
        search_roots = [public_root / domain.value]
    else:
        search_roots = [public_root]
    scenarios: dict[str, Scenario] = {}
    paths = sorted(
        p for root in search_roots for pattern in ("*.yaml", "*.yml") for p in root.rglob(pattern)
    )
    for path in paths:
        scenario = load_scenario(path, benchmark_root)
        if scenario.scenario_id in scenarios:
            raise ValueError(f"duplicate scenario_id {scenario.scenario_id} in {path}")
        scenarios[scenario.scenario_id] = scenario
    return tuple(
        scenario
        for _, scenario in sorted(scenarios.items())
        if (category is None or scenario.category is category)
        and (kind is None or scenario.kind is kind)
    )
