"""Session-agent interface for black-box (Profile C) evaluation.

A session agent is a CCE-shaped agent: it receives one customer utterance at
a time, keeps its own conversation state, and executes its own tools
internally. The harness cannot mediate its actions; it grades the agent's
world afterwards through a StateProvider. See docs/agent_contract.md.
"""

from __future__ import annotations

import json
import uuid
from typing import Protocol
from urllib import request as urllib_request

from safeagenteval.core.models import FrozenModel, JsonObject


class SessionReply(FrozenModel):
    """One reply from a session agent.

    ``metadata`` is untrusted, agent-reported structured data (for example
    which internal tool it called). It is recorded as a claim to be checked
    against the final state, never as ground truth.
    """

    text: str = ""
    metadata: JsonObject = {}


class SessionAgent(Protocol):
    """An agent driven by customer utterances, one turn at a time.

    One instance serves one run (one session). Implementations must not leak
    state between instances.
    """

    async def say(self, customer_text: str) -> SessionReply:
        """Respond to one customer utterance."""
        ...


class ScriptedSessionAgent:
    """Session agent that returns canned replies in order (tests and demos).

    The last reply repeats if more utterances arrive than were scripted.
    """

    def __init__(self, replies: tuple[str, ...] = ("Okay.",)) -> None:
        if not replies:
            raise ValueError("at least one scripted reply is required")
        self._replies = replies
        self._index = 0

    async def say(self, customer_text: str) -> SessionReply:
        del customer_text
        reply = self._replies[min(self._index, len(self._replies) - 1)]
        self._index += 1
        return SessionReply(text=reply)


class HttpSessionAgentAdapter:
    """Drive a session agent over HTTP (CCE-shaped services).

    POSTs ``{"session_id", "transcript", "language", "channel"}`` as JSON and
    reads the reply from the ``reply`` (or ``text``) field, with optional
    ``metadata``. The session id is generated per adapter instance, so one
    instance is one run.
    """

    def __init__(self, url: str, *, session_id: str | None = None, timeout: float = 30.0) -> None:
        self._url = url
        self._session_id = session_id or f"sae-{uuid.uuid4().hex}"
        self._timeout = timeout

    @property
    def session_id(self) -> str:
        return self._session_id

    async def say(self, customer_text: str) -> SessionReply:
        import asyncio

        return await asyncio.to_thread(self._say_sync, customer_text)

    def _say_sync(self, customer_text: str) -> SessionReply:
        body = json.dumps(
            {
                "session_id": self._session_id,
                "transcript": customer_text,
                "language": "en",
                "channel": "chat",
            }
        ).encode("utf-8")
        http_request = urllib_request.Request(
            self._url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib_request.urlopen(http_request, timeout=self._timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("session agent must return a JSON object")
        text = payload.get("reply", payload.get("text", ""))
        metadata = payload.get("metadata", {})
        return SessionReply(
            text=str(text),
            metadata=metadata if isinstance(metadata, dict) else {},
        )
