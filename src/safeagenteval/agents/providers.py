"""Chat clients for OpenAI-compatible and Anthropic endpoints.

OpenAI-compatible covers OpenAI, OpenRouter, Together, Groq, vLLM and Ollama
through ``base_url``. Provider SDKs are imported lazily and installed with the
``models`` extra: ``pip install -e ".[models]"``.
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import Field

from safeagenteval.agents.chat import ChatClient, ChatEntry, ChatResponse, parse_tool_arguments
from safeagenteval.core.models import FrozenModel, ToolCall, ToolSpec


class ModelSpec(FrozenModel):
    """How to reach one model. Secrets are read from ``api_key_env``, never stored."""

    name: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    provider: Literal["openai", "anthropic"]
    model: str
    api_key_env: str
    base_url: str | None = None
    temperature: float | None = 0.0
    max_tokens: int = Field(default=1024, ge=1)
    token_limit_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    seed: int | None = None
    api: Literal["chat", "responses"] = "chat"
    reasoning_effort: str | None = None


# --- OpenAI-compatible ------------------------------------------------------


def to_openai_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """Convert tool specs to OpenAI function-calling definitions."""
    return [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.input_schema,
            },
        }
        for tool in tools
    ]


def to_openai_messages(system: str, history: Sequence[ChatEntry]) -> list[dict[str, Any]]:
    """Convert a neutral history to OpenAI chat-completions messages."""
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for entry in history:
        if entry.role == "user":
            messages.append({"role": "user", "content": entry.content})
        elif entry.role == "tool":
            messages.append(
                {"role": "tool", "tool_call_id": entry.tool_call_id, "content": entry.content}
            )
        else:
            message: dict[str, Any] = {"role": "assistant", "content": entry.content or None}
            if entry.tool_calls:
                message["tool_calls"] = [
                    {
                        "id": call.call_id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, sort_keys=True),
                        },
                    }
                    for call in entry.tool_calls
                ]
            messages.append(message)
    return messages


def parse_openai_response(response: Any, latency_seconds: float) -> ChatResponse:
    """Normalize an OpenAI chat-completions response."""
    choice = response.choices[0]
    message = choice.message
    calls = tuple(
        ToolCall(
            call_id=call.id or "",
            name=call.function.name,
            arguments=parse_tool_arguments(call.function.arguments),
        )
        for call in (message.tool_calls or ())
    )
    usage = response.usage
    return ChatResponse(
        text=message.content or "",
        tool_calls=calls,
        model=response.model or "",
        stop_reason=choice.finish_reason,
        input_tokens=getattr(usage, "prompt_tokens", None),
        output_tokens=getattr(usage, "completion_tokens", None),
        latency_seconds=latency_seconds,
    )


class OpenAIChatClient:
    """Chat-completions client for any OpenAI-compatible endpoint."""

    def __init__(self, spec: ModelSpec) -> None:
        from openai import AsyncOpenAI

        self._spec = spec
        self._client = AsyncOpenAI(
            api_key=_api_key(spec), base_url=spec.base_url, max_retries=5, timeout=120
        )

    async def complete(
        self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
    ) -> ChatResponse:
        """Request one completion."""
        request: dict[str, Any] = {
            "model": self._spec.model,
            "messages": to_openai_messages(system, history),
            self._spec.token_limit_parameter: self._spec.max_tokens,
        }
        if tools:
            request["tools"] = to_openai_tools(tools)
        if self._spec.temperature is not None:
            request["temperature"] = self._spec.temperature
        if self._spec.seed is not None:
            request["seed"] = self._spec.seed
        if self._spec.reasoning_effort is not None:
            request["reasoning_effort"] = self._spec.reasoning_effort
        started = time.perf_counter()
        response = await self._client.chat.completions.create(**request)
        return parse_openai_response(response, time.perf_counter() - started)


# --- OpenAI Responses API -----------------------------------------------------


def to_responses_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """Convert tool specs to Responses-API function tools (non-strict schemas)."""
    return [
        {
            "type": "function",
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
            "strict": False,
        }
        for tool in tools
    ]


def to_responses_input(history: Sequence[ChatEntry]) -> list[dict[str, Any]]:
    """Convert a neutral history to Responses-API input items.

    Reasoning items are not replayed, so each request is stateless and the
    history stays provider-neutral.
    """
    items: list[dict[str, Any]] = []
    for entry in history:
        if entry.role == "user":
            items.append({"role": "user", "content": entry.content})
        elif entry.role == "tool":
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": entry.tool_call_id,
                    "output": entry.content,
                }
            )
        else:
            if entry.content:
                items.append({"role": "assistant", "content": entry.content})
            items.extend(
                {
                    "type": "function_call",
                    "call_id": call.call_id,
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, sort_keys=True),
                }
                for call in entry.tool_calls
            )
    return items


def parse_responses_response(response: Any, latency_seconds: float) -> ChatResponse:
    """Normalize a Responses-API response."""
    texts: list[str] = []
    calls: list[ToolCall] = []
    for item in response.output:
        if item.type == "message":
            texts.extend(part.text for part in item.content if part.type == "output_text")
        elif item.type == "function_call":
            calls.append(
                ToolCall(
                    call_id=item.call_id or "",
                    name=item.name,
                    arguments=parse_tool_arguments(item.arguments),
                )
            )
    usage = response.usage
    incomplete = getattr(response, "incomplete_details", None)
    return ChatResponse(
        text="\n".join(texts).strip(),
        tool_calls=tuple(calls),
        model=response.model or "",
        stop_reason=getattr(incomplete, "reason", None) or response.status,
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        latency_seconds=latency_seconds,
    )


class OpenAIResponsesClient:
    """Responses-API client, required for tool use by some OpenAI reasoning models."""

    def __init__(self, spec: ModelSpec) -> None:
        from openai import AsyncOpenAI

        self._spec = spec
        self._client = AsyncOpenAI(
            api_key=_api_key(spec), base_url=spec.base_url, max_retries=5, timeout=300
        )

    async def complete(
        self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
    ) -> ChatResponse:
        """Request one response without server-side storage."""
        request: dict[str, Any] = {
            "model": self._spec.model,
            "instructions": system,
            "input": to_responses_input(history),
            "max_output_tokens": self._spec.max_tokens,
            "store": False,
        }
        if tools:
            request["tools"] = to_responses_tools(tools)
        if self._spec.temperature is not None:
            request["temperature"] = self._spec.temperature
        if self._spec.reasoning_effort is not None:
            request["reasoning"] = {"effort": self._spec.reasoning_effort}
        started = time.perf_counter()
        response = await self._client.responses.create(**request)
        return parse_responses_response(response, time.perf_counter() - started)


# --- Anthropic --------------------------------------------------------------


def to_anthropic_tools(tools: Sequence[ToolSpec]) -> list[dict[str, Any]]:
    """Convert tool specs to Anthropic tool definitions."""
    return [
        {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
        for tool in tools
    ]


def to_anthropic_messages(history: Sequence[ChatEntry]) -> list[dict[str, Any]]:
    """Convert a neutral history to Anthropic messages.

    Tool results become ``tool_result`` blocks in a user message, and
    consecutive same-role messages are merged, as the API requires alternation.
    """
    messages: list[dict[str, Any]] = []
    for entry in history:
        role = "assistant" if entry.role == "assistant" else "user"
        blocks: list[dict[str, Any]] = []
        if entry.role == "tool":
            blocks.append(
                {"type": "tool_result", "tool_use_id": entry.tool_call_id, "content": entry.content}
            )
        else:
            if entry.content:
                blocks.append({"type": "text", "text": entry.content})
            blocks.extend(
                {"type": "tool_use", "id": call.call_id, "name": call.name, "input": call.arguments}
                for call in entry.tool_calls
            )
        if not blocks:
            continue
        if messages and messages[-1]["role"] == role:
            messages[-1]["content"].extend(blocks)
        else:
            messages.append({"role": role, "content": blocks})
    return messages


def parse_anthropic_response(response: Any, latency_seconds: float) -> ChatResponse:
    """Normalize an Anthropic messages response."""
    texts: list[str] = []
    calls: list[ToolCall] = []
    for block in response.content:
        if block.type == "text":
            texts.append(block.text)
        elif block.type == "tool_use":
            arguments = block.input if isinstance(block.input, dict) else {}
            calls.append(ToolCall(call_id=block.id, name=block.name, arguments=arguments))
    usage = response.usage
    return ChatResponse(
        text="\n".join(texts).strip(),
        tool_calls=tuple(calls),
        model=response.model or "",
        stop_reason=response.stop_reason,
        input_tokens=getattr(usage, "input_tokens", None),
        output_tokens=getattr(usage, "output_tokens", None),
        latency_seconds=latency_seconds,
    )


class AnthropicChatClient:
    """Messages-API client for Anthropic models."""

    def __init__(self, spec: ModelSpec) -> None:
        from anthropic import AsyncAnthropic

        self._spec = spec
        self._client = AsyncAnthropic(
            api_key=_api_key(spec), base_url=spec.base_url, max_retries=5, timeout=120
        )

    async def complete(
        self, system: str, history: Sequence[ChatEntry], tools: Sequence[ToolSpec]
    ) -> ChatResponse:
        """Request one completion."""
        request: dict[str, Any] = {
            "model": self._spec.model,
            "system": system,
            "messages": to_anthropic_messages(history),
            "max_tokens": self._spec.max_tokens,
        }
        if tools:
            request["tools"] = to_anthropic_tools(tools)
        if self._spec.temperature is not None:
            request["temperature"] = self._spec.temperature
        started = time.perf_counter()
        response = await self._client.messages.create(**request)
        return parse_anthropic_response(response, time.perf_counter() - started)


def build_client(spec: ModelSpec) -> ChatClient:
    """Create the client for ``spec``."""
    if spec.provider == "anthropic":
        return AnthropicChatClient(spec)
    if spec.api == "responses":
        return OpenAIResponsesClient(spec)
    return OpenAIChatClient(spec)


def _api_key(spec: ModelSpec) -> str:
    key = os.environ.get(spec.api_key_env)
    if not key:
        raise RuntimeError(f"environment variable {spec.api_key_env} is not set for {spec.name}")
    return key
