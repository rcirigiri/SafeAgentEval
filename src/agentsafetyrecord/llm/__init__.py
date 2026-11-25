"""Model-agnostic language-model clients (extraction and judging only)."""

from agentsafetyrecord.llm.client import (
    BUILTIN_PROVIDERS,
    AnthropicTextClient,
    AzureOpenAITextClient,
    CallableTextClient,
    LiteLLMTextClient,
    ModelSpec,
    OpenAICompatibleTextClient,
    OpenAITextClient,
    TextClient,
    TextResponse,
    build_client,
    register_text_client_factory,
    registered_providers,
)

__all__ = [
    "BUILTIN_PROVIDERS",
    "AnthropicTextClient",
    "AzureOpenAITextClient",
    "CallableTextClient",
    "LiteLLMTextClient",
    "ModelSpec",
    "OpenAICompatibleTextClient",
    "OpenAITextClient",
    "TextClient",
    "TextResponse",
    "build_client",
    "register_text_client_factory",
    "registered_providers",
]
