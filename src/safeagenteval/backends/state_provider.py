"""State seeding and reading for black-box (Profile C) evaluation.

A StateProvider is the harness's only window into a self-executing agent's
world: it seeds the scenario's initial state into the agent owner's sandbox,
reads the final state for scoring, and resets between runs. Snapshot honesty
is the trust root of every black-box verdict, so providers can be certified
with the state-provider conformance checks in ``conformance.py``.
"""

from __future__ import annotations

import copy
from typing import Protocol

from safeagenteval.core.models import JsonObject


class StateProvider(Protocol):
    """Seed, read, and reset an external system's state for one scenario."""

    def seed(self, initial_state: JsonObject) -> None:
        """Load ``initial_state`` into the external system."""
        ...

    def snapshot(self) -> JsonObject:
        """Return an isolated JSON-compatible snapshot of the current state."""
        ...

    def reset(self) -> None:
        """Remove all run residue so the next seed starts clean."""
        ...


class InMemoryStateProvider:
    """StateProvider over an in-memory dict (reference implementation).

    ``state`` exposes the live dict so a demo or test agent can act on the
    same world the provider reads. Production providers should instead call
    the agent owner's sandbox APIs in ``seed``/``snapshot``.
    """

    def __init__(self) -> None:
        self._state: JsonObject = {}

    def seed(self, initial_state: JsonObject) -> None:
        self._state = copy.deepcopy(initial_state)

    def snapshot(self) -> JsonObject:
        return copy.deepcopy(self._state)

    def reset(self) -> None:
        self._state = {}

    @property
    def state(self) -> JsonObject:
        """The live state dict (demo/test agents mutate the world here)."""
        return self._state
