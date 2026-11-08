"""Provider-neutral adapter that drives a chat model with tool calling."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import Field

from safeagenteval.core.models import (
    AgentTurn,
    FrozenModel,
    JsonObject,
    Message,
    Role,
    ToolCall,
    ToolSpec,
)


class ChatEntry(FrozenModel):
    """One message in a provider-neutral chat history.

    Assistant entries carry the tool calls exactly as the provider emitted them
    (with provider ids); tool entries reference those ids.
    """

    role: Literal["user", "assistant", "tool"]
    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    tool_call_id: str | None = None
    tool_name: str | None = None


class ChatResponse(FrozenModel):
    """One model completion, plus the operational facts the paper reports."""

    text: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    model: str
    stop_reason: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_seconds: float = Field(ge=0)


class ChatClient(Protocol):
    """A model endpoint that completes a chat history with optional tools."""

    async def complete(
        self,
        system: str,
        history: Sequence[ChatEntry],
        tools: Sequence[ToolSpec],
    ) -> ChatResponse:
        """Return the model's next message."""
        ...


def parse_tool_arguments(raw: str | None) -> JsonObject:
    """Parse a provider's JSON argument string, keeping malformed input visible.

    Malformed arguments are preserved under ``_unparsed_arguments`` so the
    backend rejects the call and the trace still shows what the model sent.
    """
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return {"_unparsed_arguments": raw}
    return parsed if isinstance(parsed, dict) else {"_unparsed_arguments": raw}


class ChatAgent:
    """AgentAdapter backed by a ChatClient.

    The harness passes the full normalized conversation on every step but does
    not retain the agent's own tool calls, so this adapter keeps the
    provider-format history itself. Create one instance per scenario run.

    ``api_error`` is set when the client raised, so a runner can tell an
    infrastructure failure (retry later) from agent behavior (score it).
    """

    def __init__(self, client: ChatClient, system_prompt: str) -> None:
        self._client = client
        self._system_prompt = system_prompt
        self._history: list[ChatEntry] = []
        self._seen = 0
        self._provider_ids: dict[str, str] = {}
        self._generated = 0
        self.responses: list[ChatResponse] = []
        self.api_error: str | None = None

    async def respond(self, messages: Sequence[Message], tools: Sequence[ToolSpec]) -> AgentTurn:
        """Forward new conversation messages to the model and return its turn."""
        for message in messages[self._seen :]:
            if message.role is Role.CUSTOMER:
                self._history.append(ChatEntry(role="user", content=message.content))
            elif message.role is Role.TOOL:
                self._history.append(self._tool_entry(message.content))
        self._seen = len(messages)

        try:
            response = await self._client.complete(self._system_prompt, self._history, tools)
        except Exception as error:
            self.api_error = f"{type(error).__name__}: {error}"
            raise
        self.responses.append(response)

        if response.text or response.tool_calls:
            self._history.append(
                ChatEntry(role="assistant", content=response.text, tool_calls=response.tool_calls)
            )
        return AgentTurn(
            reply=response.text,
            tool_calls=tuple(self._harness_call(call) for call in response.tool_calls),
        )

    def _harness_call(self, call: ToolCall) -> ToolCall:
        """Give each call a run-unique id; remember the provider id for replies."""
        if call.call_id:
            harness_id = call.call_id
        else:
            self._generated += 1
            harness_id = f"call-{self._generated}"
        suffix = 1
        candidate = harness_id
        while candidate in self._provider_ids:
            suffix += 1
            candidate = f"{harness_id}#{suffix}"
        self._provider_ids[candidate] = call.call_id or candidate
        return call.model_copy(update={"call_id": candidate})

    def _tool_entry(self, content: str) -> ChatEntry:
        result = json.loads(content)
        harness_id = str(result.get("call_id", ""))
        return ChatEntry(
            role="tool",
            content=content,
            tool_call_id=self._provider_ids.get(harness_id, harness_id),
            tool_name=str(result.get("name", "")),
        )
