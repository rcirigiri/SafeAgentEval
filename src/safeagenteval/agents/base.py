"""Agent-under-test interface."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from safeagenteval.core.models import AgentTurn, Message, ToolSpec


class AgentAdapter(Protocol):
    """Minimal interface required to evaluate an agent."""

    async def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> AgentTurn:
        """Return the agent's next reply and optional tool requests."""
        ...
