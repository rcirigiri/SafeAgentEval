"""Agent adapter for an agent served over HTTP (any language or platform).

The adapter POSTs ``{"messages": [...], "tools": [...]}`` as JSON to the
endpoint and expects an ``AgentTurn`` JSON object back, for example
``{"reply": "...", "tool_calls": [...]}``. Transport uses only the standard
library; the blocking call runs in a worker thread.
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from collections.abc import Sequence

from safeagenteval.core.models import AgentTurn, Message, ToolSpec


class HttpAgentAdapter:
    """Call a remote agent endpoint that speaks the AgentTurn JSON contract."""

    def __init__(self, url: str, *, timeout_seconds: float = 60.0) -> None:
        self._url = url
        self._timeout = timeout_seconds

    async def respond(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolSpec],
    ) -> AgentTurn:
        payload: dict[str, object] = {
            "messages": [message.model_dump(mode="json") for message in messages],
            "tools": [tool.model_dump(mode="json") for tool in tools],
        }
        return await asyncio.to_thread(self._post, payload)

    def _post(self, payload: dict[str, object]) -> AgentTurn:
        request = urllib.request.Request(
            self._url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
        return AgentTurn.model_validate(data)
