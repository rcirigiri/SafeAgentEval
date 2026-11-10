"""The ``new-session-agent`` scaffolding command."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated

import typer

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def register(app: typer.Typer) -> None:
    """Register the scaffolding command on ``app``."""

    @app.command("new-session-agent")
    def new_session_agent(
        name: str, out: Annotated[Path, typer.Option(help="Parent directory")] = Path(".")
    ) -> None:
        """Scaffold a starter project: session agent + state provider."""
        if not _NAME.match(name):
            raise typer.BadParameter(
                f"name must start with a letter and contain only letters, digits, '-'/'_', "
                f"got {name!r}"
            )
        root = out / name
        if root.exists():
            raise typer.BadParameter(f"{root} already exists; refusing to overwrite")
        package = root / name.replace("-", "_")
        package.mkdir(parents=True)
        (package / "__init__.py").write_text(
            '"""Session-agent starter package."""\n', encoding="utf-8"
        )
        (package / "agent.py").write_text(_STARTER_SESSION_AGENT, encoding="utf-8")
        (root / "README.md").write_text(
            f"# {name}\n\nStarter project (see docs/agent_contract.md). Certify it with:\n\n"
            f"```bash\nsafeagenteval certify-agent \\\n"
            f"  --agent {package.name}.agent:StarterSessionAgent\n"
            f"safeagenteval certify-state-provider "
            f"--provider {package.name}.agent:StarterStateProvider\n"
            "```\n",
            encoding="utf-8",
        )
        typer.echo(str(root))


_STARTER_SESSION_AGENT = '''"""Starter: a session agent plus its state provider.

Replace the echo logic with calls into your agent, and the in-memory
provider with seed/snapshot/reset against your sandbox. See
docs/agent_contract.md.
"""

from __future__ import annotations

import copy

from safeagenteval.agents.session import SessionReply
from safeagenteval.core.models import JsonObject


class StarterSessionAgent:
    """Utterance in, reply out; executes its own tools internally."""

    def __init__(self) -> None:
        self._turns = 0

    async def say(self, customer_text: str) -> SessionReply:
        self._turns += 1
        # TODO: forward customer_text to your agent and return its reply.
        # Report structured outcomes as metadata (checked, never trusted).
        return SessionReply(text=f"You said: {customer_text}", metadata={"turns": self._turns})


class StarterStateProvider:
    """Seed, read, and reset your sandbox state for one scenario."""

    def __init__(self) -> None:
        self._state: JsonObject = {}

    def seed(self, initial_state: JsonObject) -> None:
        self._state = copy.deepcopy(initial_state)

    def snapshot(self) -> JsonObject:
        return copy.deepcopy(self._state)

    def reset(self) -> None:
        self._state = {}
'''
