"""Shared helpers for CLI commands."""

from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

import typer

from agentsafetyrecord.conformance import ConformanceReport
from agentsafetyrecord.core.models import JsonObject
from agentsafetyrecord.llm.client import ModelSpec

# Default credential variable per provider. ``None`` means the provider
# resolves credentials itself (LiteLLM routes such as Bedrock/Vertex) or
# needs none (local Ollama). Any other provider name is accepted too and
# routed through LiteLLM — AgentSafetyRecord is not locked to this list.
_DEFAULT_KEY_ENV: dict[str, str | None] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
    "azure": "AZURE_OPENAI_API_KEY",
    "ollama": None,
    "openai-compatible": None,
    "litellm": None,
    "bedrock": None,
    "vertex_ai": None,
    "custom": None,
}

_PROVIDER_NAME = re.compile(r"^[A-Za-z0-9_.\-]+$")

MODEL_SPEC_HELP = (
    "'provider:model' — built-in: openai, anthropic, gemini, azure, "
    "ollama (local, no key), openai-compatible (any compatible endpoint "
    "via --*-base-url); any LiteLLM provider (e.g. bedrock, vertex_ai, "
    "together_ai) via the [litellm] extra; or custom:package.module:Factory"
)


def parse_model_options(values: list[str]) -> JsonObject:
    """Parse repeatable ``key=value`` model options (value may be JSON)."""
    options: JsonObject = {}
    for entry in values:
        key, separator, raw = entry.partition("=")
        if not separator or not key.strip():
            raise typer.BadParameter(f"expected 'key=value' model option, got {entry!r}")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = raw
        options[key.strip()] = parsed
    return options


def parse_model_spec(
    value: str,
    api_key_env: str | None = None,
    base_url: str | None = None,
    api_version: str | None = None,
    options: JsonObject | None = None,
) -> ModelSpec:
    """Parse ``provider:model`` (e.g. ``anthropic:claude-sonnet-5-5``) into a spec.

    The provider segment is any routing key ``build_client`` understands
    — built-in, LiteLLM, or custom — never a hard-coded vendor list.
    The API key is never taken on the command line; it is read from the
    environment variable named by ``api_key_env`` or the provider
    default (keyless providers such as Ollama need none). ``base_url``
    reaches OpenAI-compatible endpoints (e.g. a hosted open-weight
    model) whose key lives in a differently named variable.
    """
    provider, separator, model = value.partition(":")
    provider = provider.strip().lower()
    if not separator or not _PROVIDER_NAME.match(provider) or not model:
        raise typer.BadParameter(
            f"expected 'provider:model' (see --help for providers), got {value!r}"
        )
    return ModelSpec(
        name=model,
        provider=provider,
        model=model,
        api_key_env=api_key_env or _DEFAULT_KEY_ENV.get(provider),
        base_url=base_url,
        api_version=api_version,
        temperature=None,  # current models deprecate/ignore the parameter
        options=options or {},
    )


def import_object(spec: str) -> object:
    """Import ``package.module:ClassName`` or raise a clean CLI error."""
    module_name, separator, attribute = spec.partition(":")
    if not separator or not module_name or not attribute:
        raise typer.BadParameter(f"expected 'package.module:ClassName', got {spec!r}")
    try:
        return getattr(importlib.import_module(module_name), attribute)
    except (ImportError, AttributeError) as error:
        raise typer.BadParameter(f"cannot import {spec!r}: {error}") from error


def emit_conformance(
    subject_key: str, subject: str, result: ConformanceReport, report: Path | None
) -> None:
    """Print (and optionally save) a conformance report; exit by its verdict."""
    payload: JsonObject = {
        subject_key: subject,
        "subject": result.subject,
        "passed": result.passed,
        "passed_count": result.passed_count,
        "total_count": result.total_count,
        "checks": [check.model_dump(mode="json") for check in result.checks],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    if report is not None:
        report.write_text(text + "\n", encoding="utf-8")
    typer.echo(text)
    raise typer.Exit(code=0 if result.passed else 1)
