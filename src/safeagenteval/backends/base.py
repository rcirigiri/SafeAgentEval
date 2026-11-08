"""Deterministic backend interface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from safeagenteval.core.models import BackendExecution, JsonObject, ToolCall, ToolSpec


class DomainBackend(Protocol):
    """Backend contract required by the evaluation harness."""

    @property
    def tools(self) -> Sequence[ToolSpec]:
        """Return tools exposed to the agent."""
        ...

    def execute(self, call: ToolCall) -> BackendExecution:
        """Execute one admitted tool request."""
        ...

    def normalize_arguments(self, call: ToolCall) -> JsonObject:
        """Return canonical arguments used to bind calls to declared intents.

        Must be pure and must not change state. Normalize only representation
        (for example ``"100"`` to ``"100.00"``), never meaning.
        """
        ...

    def snapshot(self) -> JsonObject:
        """Return an isolated JSON-compatible state snapshot."""
        ...
