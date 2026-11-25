"""Model-agnostic routing: no provider lock-in for extractor/judge/agent.

The deterministic scorer never uses a model. Where a model is used
(claim extractor, LLMJudge, or an LLM agent under test), any provider —
built-in, LiteLLM-routed, local, or custom — must plug in through the
same ``TextClient`` protocol. These tests pin that contract without
network calls: SDK constructors are stubbed at the client boundary.
"""

from __future__ import annotations

import asyncio
import sys
import types

import pytest

from agenticsafetyeval.agents.llm_session import LLMSessionAgent
from agenticsafetyeval.backends.state_provider import InMemoryStateProvider
from agenticsafetyeval.cli.common import parse_model_options, parse_model_spec
from agenticsafetyeval.llm.client import (
    AzureOpenAITextClient,
    CallableTextClient,
    LiteLLMTextClient,
    ModelSpec,
    OpenAITextClient,
    TextResponse,
    build_client,
    register_text_client_factory,
    registered_providers,
)


class FixedText:
    def __init__(self, text: str = "ok") -> None:
        self._text = text

    async def complete(self, system: str, user: str) -> TextResponse:
        del system, user
        return TextResponse(text=self._text, model="stub", latency_seconds=0.0)


def test_parse_spec_accepts_any_provider_not_a_vendor_list() -> None:
    for value, provider in [
        ("ollama:llama3.1", "ollama"),
        ("bedrock:anthropic.claude-sonnet-4-5", "bedrock"),
        ("vertex_ai:gemini-2.5-pro", "vertex_ai"),
        ("together_ai:meta-llama/Llama-3.3-70B", "together_ai"),
        ("openai-compatible:hosted-model", "openai-compatible"),
        ("google:gemini-2.5-flash", "gemini"),  # alias normalizes
    ]:
        spec = parse_model_spec(value)
        assert spec.provider == provider


def test_keyless_local_and_cloud_credential_providers_need_no_key_env() -> None:
    assert parse_model_spec("ollama:llama3.1").api_key_env is None
    assert parse_model_spec("bedrock:some-model").api_key_env is None
    assert parse_model_spec("anthropic:claude-sonnet-5").api_key_env == "ANTHROPIC_API_KEY"


def test_model_options_parse_json_and_plain_values() -> None:
    options = parse_model_options(["aws_region_name=us-east-1", "temperature=0.2", "flag=true"])
    assert options == {"aws_region_name": "us-east-1", "temperature": 0.2, "flag": True}


def test_ollama_routes_to_local_openai_compatible_endpoint(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    fake = types.ModuleType("openai")
    fake.AsyncOpenAI = FakeAsyncOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    client = build_client(parse_model_spec("ollama:llama3.1"))

    assert isinstance(client, OpenAITextClient)
    assert captured["base_url"] == "http://localhost:11434/v1"
    assert captured["api_key"] == "not-needed"  # local server: no key required


def test_azure_requires_endpoint_and_uses_deployment(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    captured: dict[str, object] = {}

    class FakeAsyncAzureOpenAI:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    fake = types.ModuleType("openai")
    fake.AsyncAzureOpenAI = FakeAsyncAzureOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake)
    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "test-key")

    spec = parse_model_spec(
        "azure:my-deployment",
        base_url="https://example.openai.azure.com/",
        api_version="2024-10-21",
    )
    client = build_client(spec)

    assert isinstance(client, AzureOpenAITextClient)
    assert captured["azure_endpoint"] == "https://example.openai.azure.com/"
    assert captured["api_version"] == "2024-10-21"


def test_unknown_provider_routes_to_litellm_with_prefixed_model(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    fake = types.ModuleType("litellm")
    monkeypatch.setitem(sys.modules, "litellm", fake)

    client = build_client(parse_model_spec("bedrock:anthropic.claude-sonnet-4-5"))

    assert isinstance(client, LiteLLMTextClient)
    assert client._model == "bedrock/anthropic.claude-sonnet-4-5"


def test_litellm_route_without_extra_fails_with_install_hint(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setitem(sys.modules, "litellm", None)  # forces ImportError on import
    with pytest.raises(RuntimeError, match=r"agenticsafetyeval\[litellm\]"):
        build_client(parse_model_spec("bedrock:some-model"))


def test_litellm_client_completes_and_reports_usage(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[dict[str, object]] = []

    async def fake_acompletion(**kwargs: object) -> types.SimpleNamespace:
        calls.append(kwargs)
        return types.SimpleNamespace(
            choices=[
                types.SimpleNamespace(message=types.SimpleNamespace(content='{"claims": []}'))
            ],
            usage=types.SimpleNamespace(prompt_tokens=11, completion_tokens=7),
            model="bedrock/anthropic.claude-sonnet-4-5",
        )

    fake = types.ModuleType("litellm")
    fake.acompletion = fake_acompletion  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "litellm", fake)

    spec = parse_model_spec(
        "bedrock:anthropic.claude-sonnet-4-5",
        options=parse_model_options(["aws_region_name=us-east-1"]),
    )
    response = asyncio.run(build_client(spec).complete("sys", "user"))

    assert response.text == '{"claims": []}'
    assert response.input_tokens == 11 and response.output_tokens == 7
    assert calls[0]["model"] == "bedrock/anthropic.claude-sonnet-4-5"
    assert calls[0]["aws_region_name"] == "us-east-1"


def test_registered_custom_factory_overrides_and_is_listed() -> None:
    register_text_client_factory("myprovider", lambda spec: FixedText("custom"))
    try:
        assert "myprovider" in registered_providers()
        client = build_client(ModelSpec(name="m", provider="myprovider", model="m"))
        response = asyncio.run(client.complete("s", "u"))
        assert response.text == "custom"
    finally:
        from agenticsafetyeval.llm import client as client_module

        client_module._CUSTOM_FACTORIES.pop("myprovider", None)


def test_custom_import_path_factory(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    module = types.ModuleType("my_custom_model")

    def build(spec: ModelSpec) -> FixedText:
        return FixedText(f"built:{spec.model}")

    module.build = build  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "my_custom_model", module)

    client = build_client(parse_model_spec("custom:my_custom_model:build"))
    response = asyncio.run(client.complete("s", "u"))
    # The factory receives the full spec, whose model is the import path.
    assert response.text == "built:my_custom_model:build"


def test_callable_client_wraps_sync_and_async_callables() -> None:
    sync_client = CallableTextClient(lambda system, user: f"{system}:{user}", model="local-x")
    response = asyncio.run(sync_client.complete("s", "u"))
    assert response.text == "s:u" and response.model == "local-x"

    async def async_model(system: str, user: str) -> str:
        return "async-ok"

    response = asyncio.run(CallableTextClient(async_model).complete("s", "u"))
    assert response.text == "async-ok"


def test_any_text_client_can_drive_the_agent_under_test() -> None:
    # The agent under test is model-agnostic too: a plain callable model
    # (no vendor SDK anywhere) drives LLMSessionAgent through its tools.
    calls: list[str] = []

    def my_model(system: str, user: str) -> str:
        del system
        calls.append(user)
        if "TOOL RESULT" not in user:
            return '{"tool": "list_accounts", "arguments": {}}'
        return '{"reply": "Your checking balance is $2,000.00."}'

    provider = InMemoryStateProvider()
    provider.seed(
        {
            "accounts": {
                "account-checking": {"owner_id": "customer-001", "balance": "2000.00"}
            },
            "payees": {},
            "transfers": [],
        }
    )
    agent = LLMSessionAgent(CallableTextClient(my_model), provider)
    reply = asyncio.run(agent.say("What is my balance?"))
    assert "2,000" in reply.text
    assert len(calls) == 2  # one tool step, one reply step
