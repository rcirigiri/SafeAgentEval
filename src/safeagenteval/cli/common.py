"""Shared helpers for CLI commands."""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import typer

from safeagenteval.conformance import ConformanceReport
from safeagenteval.core.models import JsonObject
from safeagenteval.llm.client import ModelSpec

_DEFAULT_KEY_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def parse_model_spec(
    value: str, api_key_env: str | None = None, base_url: str | None = None
) -> ModelSpec:
    """Parse ``provider:model`` (e.g. ``anthropic:claude-sonnet-5``) into a spec.

    The API key is never taken on the command line; it is read from the
    environment variable named by ``api_key_env`` or the provider default.
    ``base_url`` reaches OpenAI-compatible endpoints (e.g. a hosted
    open-weight model) whose key lives in a differently named variable.
    """
    provider, separator, model = value.partition(":")
    if not separator or provider not in _DEFAULT_KEY_ENV or not model:
        raise typer.BadParameter(
            f"expected 'provider:model' with provider openai|anthropic|gemini, got {value!r}"
        )
    return ModelSpec(
        name=model,
        provider=provider,  # type: ignore[arg-type]
        model=model,
        api_key_env=api_key_env or _DEFAULT_KEY_ENV[provider],
        base_url=base_url,
        temperature=None,  # current models deprecate/ignore the parameter
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
