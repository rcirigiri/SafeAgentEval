"""Model-agnostic text clients for claim extraction and judging.

AgenticSafetyEval does not lock evaluation to a single model provider. The
deterministic scorer never uses a model at all; models appear only as
(a) the agent under test, (b) the claim extractor, and (c) the LLMJudge.
All three reach models through the small ``TextClient`` protocol in this
module, so any endpoint that can complete a system/user exchange can be
swapped in without touching scoring, scenarios, or the harness:

- Built in, no extra dependency beyond ``.[models]``: OpenAI, Anthropic,
  Gemini (OpenAI-compatible endpoint), any OpenAI-compatible server
  (``openai-compatible``, e.g. vLLM / LM Studio / a hosted open-weight
  model), Ollama (local, no API key), and Azure OpenAI.
- Via the optional ``.[litellm]`` extra: every LiteLLM provider route
  (AWS Bedrock, Vertex AI, Cohere, Together, Groq, ...) addressed as
  ``provider:model`` — for example ``bedrock:anthropic.claude-...``.
- Custom: register a factory with ``register_text_client_factory``,
  wrap any sync/async callable in ``CallableTextClient``, implement the
  ``TextClient`` protocol directly, or point ``custom:`` at an importable
  ``package.module:Factory`` on the CLI.

These clients are evaluation-side components: they never supply ground
truth. The agent under test is always a black-box session agent driven
through ``agenticsafetyeval.agents.session``.
"""

from __future__ import annotations

import importlib
import inspect
import os
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any, Protocol

from pydantic import Field, field_validator

from agenticsafetyeval.core.models import FrozenModel, JsonObject

_PROVIDER_ALIASES = {
    "google": "gemini",
    "azure-openai": "azure",
    "azure_openai": "azure",
    "compatible": "openai-compatible",
}

#: Providers served by a built-in client (everything else routes to
#: LiteLLM when it is installed, or to a registered custom factory).
BUILTIN_PROVIDERS = (
    "openai",
    "anthropic",
    "gemini",
    "azure",
    "ollama",
    "openai-compatible",
    "custom",
)

OLLAMA_BASE_URL = "http://localhost:11434/v1"
GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
_NO_KEY_PLACEHOLDER = "not-needed"


class ModelSpec(FrozenModel):
    """How to reach one model. Secrets come from the env, never the spec.

    ``provider`` is deliberately *not* an enum of three vendors: it is
    the routing key understood by ``build_client`` — a built-in provider
    name, ``litellm``, any LiteLLM provider name (``bedrock``, ...), or
    a name registered with ``register_text_client_factory``.
    ``api_key_env`` names the environment variable holding the key; it
    may be ``None`` for local/keyless endpoints (Ollama) and for
    providers that resolve credentials themselves (Bedrock, Vertex).
    ``options`` carries provider-specific keyword arguments (for
    example ``{"aws_region_name": "us-east-1"}`` for LiteLLM routes or
    ``{"api_version": "2024-10-21"}``-style extras) without new fields
    per vendor.
    """

    name: str = Field(pattern=r"^[A-Za-z0-9_.:\-/]+$")
    provider: str = Field(pattern=r"^[A-Za-z0-9_.\-]+$")
    model: str = Field(min_length=1)
    api_key_env: str | None = None
    base_url: str | None = None
    api_version: str | None = None
    temperature: float | None = 0.0
    max_tokens: int = Field(default=1024, ge=1)
    options: JsonObject = {}

    @field_validator("provider", mode="before")
    @classmethod
    def _normalize_provider(cls, value: object) -> object:
        if isinstance(value, str):
            lowered = value.strip().lower()
            return _PROVIDER_ALIASES.get(lowered, lowered)
        return value


class TextResponse(FrozenModel):
    """One text completion, plus operational facts."""

    text: str = ""
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_seconds: float = Field(ge=0)


class TextClient(Protocol):
    """A model endpoint that completes a single system/user exchange.

    Implement this protocol (structural — no subclassing required) to
    plug in any custom or local model.
    """

    async def complete(self, system: str, user: str) -> TextResponse:
        """Return the model's reply text."""
        ...


#: What a plain callable model looks like: sync or async, returning
#: either raw text or a full ``TextResponse``.
CompletionCallable = Callable[[str, str], "str | TextResponse | Awaitable[str | TextResponse]"]
TextClientFactory = Callable[[ModelSpec], TextClient]

_CUSTOM_FACTORIES: dict[str, TextClientFactory] = {}


def register_text_client_factory(provider: str, factory: TextClientFactory) -> None:
    """Register ``factory`` for ``provider`` (overrides any built-in).

    This is the extension point for models no built-in or LiteLLM route
    covers: ``register_text_client_factory("myprovider", build_mine)``
    then ``ModelSpec(provider="myprovider", ...)`` or the CLI string
    ``myprovider:some-model`` reaches your client.
    """
    key = _PROVIDER_ALIASES.get(provider.strip().lower(), provider.strip().lower())
    _CUSTOM_FACTORIES[key] = factory


def registered_providers() -> tuple[str, ...]:
    """Provider names with a registered custom factory, sorted."""
    return tuple(sorted(_CUSTOM_FACTORIES))


class CallableTextClient:
    """Adapt any sync/async ``(system, user) -> str | TextResponse`` callable.

    The fastest way to wrap a custom or local model: pass a function
    that calls it, and this class supplies latency accounting and the
    ``TextClient`` shape the extractor, judge, and LLM session agent
    expect.
    """

    def __init__(self, func: CompletionCallable, *, model: str = "custom") -> None:
        self._func = func
        self._model = model

    async def complete(self, system: str, user: str) -> TextResponse:
        started = time.perf_counter()
        result = self._func(system, user)
        if inspect.isawaitable(result):
            result = await result
        if isinstance(result, TextResponse):
            return result
        return TextResponse(
            text=str(result),
            model=self._model,
            latency_seconds=time.perf_counter() - started,
        )


def _api_key(spec: ModelSpec, *, default_env: str | None = None, required: bool = True) -> str:
    env_name = spec.api_key_env or default_env
    if env_name is None:
        if required:
            raise RuntimeError(f"no API-key environment variable configured for {spec.name}")
        return _NO_KEY_PLACEHOLDER
    key = os.environ.get(env_name)
    if not key:
        if not required:
            return _NO_KEY_PLACEHOLDER
        raise RuntimeError(f"environment variable {env_name} is not set for {spec.name}")
    return key


class _ChatCompletionsClient:
    """Shared completion logic for OpenAI-style chat-completions clients.

    OpenAI (and every compatible endpoint) and Azure OpenAI expose the
    same ``chat.completions.create`` call shape; they differ only in how
    the underlying SDK client is constructed. Subclasses build it and
    pass it here, so the completion behaviour lives in exactly one place.
    """

    def __init__(self, spec: ModelSpec, client: Any) -> None:
        self._spec = spec
        self._client: Any = client

    async def complete(self, system: str, user: str) -> TextResponse:
        started = time.perf_counter()
        kwargs: JsonObject = {
            "model": self._spec.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": self._spec.max_tokens,
        }
        if self._spec.temperature is not None:
            kwargs["temperature"] = self._spec.temperature
        response = await self._client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        usage = response.usage
        return TextResponse(
            text=choice.message.content or "",
            model=response.model or "",
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            latency_seconds=time.perf_counter() - started,
        )


class OpenAITextClient(_ChatCompletionsClient):
    """Chat-completions client for OpenAI and OpenAI-compatible endpoints."""

    def __init__(self, spec: ModelSpec) -> None:
        from openai import AsyncOpenAI

        # Hosted OpenAI/Gemini require a real key; a keyless local
        # compatible server (Ollama, vLLM) accepts a placeholder.
        keyless = spec.provider in {"ollama", "openai-compatible"} and not spec.api_key_env
        default_env = {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}.get(spec.provider)
        client = AsyncOpenAI(
            api_key=_api_key(spec, default_env=default_env, required=not keyless),
            base_url=spec.base_url,
            max_retries=5,
            timeout=120,
        )
        super().__init__(spec, client)


# Backwards-friendly alias: this client serves every compatible endpoint.
OpenAICompatibleTextClient = OpenAITextClient


class AzureOpenAITextClient(_ChatCompletionsClient):
    """Azure OpenAI client; ``model`` is the deployment name."""

    def __init__(self, spec: ModelSpec) -> None:
        from openai import AsyncAzureOpenAI

        if not spec.base_url:
            raise RuntimeError(
                "azure provider requires base_url (the Azure OpenAI endpoint, "
                "e.g. https://<resource>.openai.azure.com/)"
            )
        client = AsyncAzureOpenAI(
            api_key=_api_key(spec, default_env="AZURE_OPENAI_API_KEY"),
            azure_endpoint=spec.base_url,
            api_version=spec.api_version
            or os.environ.get("AZURE_OPENAI_API_VERSION")
            or "2024-10-21",
            max_retries=5,
            timeout=120,
        )
        super().__init__(spec, client)


class AnthropicTextClient:
    """Messages-API client for Anthropic models (text only)."""

    def __init__(self, spec: ModelSpec) -> None:
        from anthropic import AsyncAnthropic

        self._spec = spec
        self._client = AsyncAnthropic(
            api_key=_api_key(spec, default_env="ANTHROPIC_API_KEY"),
            base_url=spec.base_url,
            max_retries=5,
            timeout=120,
        )

    async def complete(self, system: str, user: str) -> TextResponse:
        started = time.perf_counter()
        kwargs: dict[str, Any] = {}
        if self._spec.temperature is not None:
            kwargs["temperature"] = self._spec.temperature
        response = await self._client.messages.create(
            model=self._spec.model,
            system=system,
            messages=[{"role": "user", "content": user}],
            max_tokens=self._spec.max_tokens,
            **kwargs,
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


class LiteLLMTextClient:
    """Any LiteLLM route: Bedrock, Vertex AI, Cohere, Together, Groq, ...

    ``spec.model`` is used verbatim when ``provider == "litellm"``;
    otherwise the LiteLLM model string is ``"<provider>/<model>"``
    (unless ``model`` already carries the prefix). Credentials are
    resolved by LiteLLM from the environment (AWS chain, Google ADC,
    provider API keys) unless ``api_key_env`` names a variable to pass
    explicitly. Requires ``pip install "agenticsafetyeval[litellm]"``.
    """

    def __init__(self, spec: ModelSpec) -> None:
        try:
            import litellm  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError(
                f"provider {spec.provider!r} needs LiteLLM: "
                'pip install "agenticsafetyeval[litellm]", or register a custom '
                "factory with register_text_client_factory()"
            ) from error
        self._litellm = litellm
        self._spec = spec
        if spec.provider == "litellm" or "/" in spec.model:
            self._model = spec.model
        else:
            self._model = f"{spec.provider}/{spec.model}"

    async def complete(self, system: str, user: str) -> TextResponse:
        started = time.perf_counter()
        kwargs: JsonObject = dict(self._spec.options)
        if self._spec.temperature is not None:
            kwargs.setdefault("temperature", self._spec.temperature)
        kwargs.setdefault("max_tokens", self._spec.max_tokens)
        if self._spec.base_url:
            kwargs.setdefault("api_base", self._spec.base_url)
        if self._spec.api_key_env:
            kwargs["api_key"] = _api_key(self._spec)
        if self._spec.api_version:
            kwargs.setdefault("api_version", self._spec.api_version)
        response = await self._litellm.acompletion(
            model=self._model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            **kwargs,
        )
        choice = response.choices[0]
        content = getattr(choice.message, "content", "") or ""
        usage = getattr(response, "usage", None)
        return TextResponse(
            text=str(content),
            model=str(getattr(response, "model", "") or self._model),
            input_tokens=getattr(usage, "prompt_tokens", None),
            output_tokens=getattr(usage, "completion_tokens", None),
            latency_seconds=time.perf_counter() - started,
        )


def _build_custom(spec: ModelSpec) -> TextClient:
    """Resolve ``custom:package.module:Factory`` into a client.

    The factory may be a ``TextClient`` class/factory taking the spec,
    a no-argument factory, or a plain callable ``(system, user) -> str``
    (wrapped in ``CallableTextClient``).
    """
    module_name, separator, attribute = spec.model.partition(":")
    if not separator or not module_name or not attribute:
        raise RuntimeError(
            f"custom provider expects model 'package.module:Factory', got {spec.model!r}"
        )
    try:
        factory = getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as error:
        raise RuntimeError(f"cannot import custom model factory {spec.model!r}: {error}") from error
    try:
        built = factory(spec)
    except TypeError:
        built = factory()
    if hasattr(built, "complete"):
        return built  # type: ignore[no-any-return]
    if callable(built):
        return CallableTextClient(built, model=spec.name)
    raise RuntimeError(f"custom factory {spec.model!r} did not produce a TextClient or callable")


def build_client(spec: ModelSpec) -> TextClient:
    """Create the text client for ``spec`` — provider-agnostic routing.

    Order: a registered custom factory wins (so built-ins can be
    overridden), then built-in providers, then LiteLLM for any other
    provider name (``bedrock``, ``vertex_ai``, ``together_ai``, ...).
    Gemini is reached through its OpenAI-compatible endpoint and Ollama
    through its local one; an explicit ``base_url`` always wins.
    """
    factory = _CUSTOM_FACTORIES.get(spec.provider)
    if factory is not None:
        return factory(spec)
    if spec.provider == "anthropic":
        return AnthropicTextClient(spec)
    if spec.provider == "azure":
        return AzureOpenAITextClient(spec)
    if spec.provider == "custom":
        return _build_custom(spec)
    if spec.provider == "gemini" and spec.base_url is None:
        spec = spec.model_copy(update={"base_url": GEMINI_OPENAI_BASE_URL})
    if spec.provider == "ollama" and spec.base_url is None:
        spec = spec.model_copy(update={"base_url": OLLAMA_BASE_URL})
    if spec.provider in {"openai", "gemini", "ollama", "openai-compatible"}:
        return OpenAITextClient(spec)
    return LiteLLMTextClient(spec)
