"""The ``certify-agent`` and ``certify-state-provider`` commands."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated, cast

import typer

from safeagenteval.agents.session import SessionAgent
from safeagenteval.backends.state_provider import StateProvider
from safeagenteval.cli.common import emit_conformance, import_object
from safeagenteval.conformance import check_session_agent, check_state_provider


def register(app: typer.Typer) -> None:
    """Register the conformance commands on ``app``."""

    @app.command("certify-agent")
    def certify_agent(
        agent: Annotated[str, typer.Option(help="Session agent 'package.module:ClassName'")],
        report: Annotated[Path | None, typer.Option(help="Write the JSON report here")] = None,
    ) -> None:
        """Run the session-agent conformance checks (AGT-01..05)."""
        agent_class = import_object(agent)
        if not callable(agent_class) or not callable(getattr(agent_class, "say", None)):
            raise typer.BadParameter(f"{agent} does not implement SessionAgent.say")

        def factory() -> SessionAgent:
            return cast(SessionAgent, agent_class())

        result = asyncio.run(check_session_agent(factory))
        emit_conformance("agent", agent, result, report)

    @app.command("certify-state-provider")
    def certify_state_provider(
        provider: Annotated[str, typer.Option(help="StateProvider 'package.module:ClassName'")],
        report: Annotated[Path | None, typer.Option(help="Write the JSON report here")] = None,
    ) -> None:
        """Run the state-provider conformance checks (SP-01..04)."""
        provider_class = import_object(provider)
        if not callable(provider_class):
            raise typer.BadParameter(f"{provider} is not callable")

        def factory() -> StateProvider:
            return cast(StateProvider, provider_class())

        result = check_state_provider(factory)
        emit_conformance("provider", provider, result, report)
