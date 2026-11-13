"""Text-only language-model clients for claim extraction and judging.

These clients exist solely so the framework can (a) extract typed claims
from agent replies and (b) run an LLMJudge over a recorded run. They are
evaluation-side components: they never act as the agent under test and
never supply ground truth. The agent under test is always a black-box
session agent driven through ``safeagenteval.agents.session``.
"""

from __future__ import annotations

import os
import time
from collections.abc import Sequence
from typing import Literal, Protocol

from pydantic import Field

from safeagenteval.core.models import FrozenModel


class ModelSpec(FrozenModel):
    """How to reach one evaluation-side model. Secrets come from the env."""

    name: str = Field(pattern=r"^[A-Za-z0-9_.-]+$")
    provider: Literal["openai", "anthropic", "gemini"]
    model: str
    api_key_env: str
    base_url: str | None = None
    temperature: float | None = 0.0
    max_tokens: int = Field(default=1024, ge=1)


class TextResponse(FrozenModel):
    """One text completion, plus operational facts."""

    text: str = ""
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_seconds: float = Field(ge=0)


class TextClient(Protocol):
    """A model endpoint that completes a single system/user exchange."""

    async def complete(self, system: str, user: str) -> TextResponse:
        """Return the model's reply text."""
        ...


class OpenAITextClient:
    """Chat-completions client for any OpenAI-compatible endpoint (text only)."""

    def __init__(self, spec: ModelSpec) -> None:
        from openai import AsyncOpenAI

        self._spec = spec
        self._client = AsyncOpenAI(
            api_key=_api_key(spec), base_url=spec.base_url, max_retries=5, timeout=120
        )

    async def complete(self, system: str, user: str) -> TextResponse:
        started = time.perf_counter()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        if self._spec.temperature is None:
            response = await self._client.chat.completions.create(
                model=self._spec.model,
                messages=messages,  # type: ignore[arg-type]
                max_completion_tokens=self._spec.max_tokens,
            )
        else:
            response = await self._client.chat.completions.create(
                model=self._spec.model,
                messages=messages,  # type: ignore[arg-type]
                max_completion_tokens=self._spec.max_tokens,
                temperature=self._spec.temperature,
            )
        choice = response.choices[0]
        usage = response.usage
        return TextResponse(
            text=choice.message.content or "",
            model=response.model or "",
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            latency_seconds=time.perf_counter() - started,
        )


class AnthropicTextClient:
    """Messages-API client for Anthropic models (text only)."""

    def __init__(self, spec: ModelSpec) -> None:
        from anthropic import AsyncAnthropic

        self._spec = spec
        self._client = AsyncAnthropic(
            api_key=_api_key(spec), base_url=spec.base_url, max_retries=5, timeout=120
        )

    async def complete(self, system: str, user: str) -> TextResponse:
        started = time.perf_counter()
        if self._spec.temperature is None:
            response = await self._client.messages.create(
                model=self._spec.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=self._spec.max_tokens,
            )
        else:
            response = await self._client.messages.create(
                model=self._spec.model,
                system=system,
                messages=[{"role": "user", "content": user}],
                max_tokens=self._spec.max_tokens,
                temperature=self._spec.temperature,
            )
        texts: Sequence[str] = tuple(
            str(getattr(block, "text", ""))
            for block in response.content
            if getattr(block, "type", "") == "text"
        )
        usage = response.usage
        return TextResponse(
            text="\n".join(texts).strip(),
            model=response.model or "",
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            latency_seconds=time.perf_counter() - started,
        )


GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"


def build_client(spec: ModelSpec) -> TextClient:
    """Create the text client for ``spec``.

    Gemini is reached through its OpenAI-compatible endpoint, so it
    reuses the OpenAI client with a default base URL; an explicit
    ``base_url`` on the spec always wins.
    """
    if spec.provider == "anthropic":
        return AnthropicTextClient(spec)
    if spec.provider == "gemini" and spec.base_url is None:
        spec = spec.model_copy(update={"base_url": GEMINI_OPENAI_BASE_URL})
    return OpenAITextClient(spec)


def _api_key(spec: ModelSpec) -> str:
    key = os.environ.get(spec.api_key_env)
    if not key:
        raise RuntimeError(f"environment variable {spec.api_key_env} is not set for {spec.name}")
    return key
