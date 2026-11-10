"""Conformance checks for black-box (Profile C) integrations.

For a self-executing agent, its session adapter and its state provider
are the trust surface. These checks certify that surface: the adapter
answers in contract shape and keeps runs isolated; the provider seeds,
reads, and resets the agent owner's world faithfully.

Every check builds a fresh subject from the factory, so checks are
independent and order does not matter. A factory that raises fails every
check instead of crashing certification.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Coroutine

from safeagenteval.agents.session import SessionAgent, SessionReply
from safeagenteval.backends.state_provider import StateProvider
from safeagenteval.core.models import FrozenModel, JsonObject


class ConformanceCheck(FrozenModel):
    """One contract check outcome."""

    check_id: str
    name: str
    passed: bool
    note: str = ""


class ConformanceReport(FrozenModel):
    """Machine-readable conformance result for one subject."""

    checks: tuple[ConformanceCheck, ...]
    subject: str = "session-agent"

    @property
    def passed(self) -> bool:
        """Whether every check passed."""
        return all(check.passed for check in self.checks)

    @property
    def passed_count(self) -> int:
        return sum(1 for check in self.checks if check.passed)

    @property
    def total_count(self) -> int:
        return len(self.checks)


SessionAgentFactory = Callable[[], SessionAgent]
StateProviderFactory = Callable[[], StateProvider]


async def check_session_agent(factory: SessionAgentFactory) -> ConformanceReport:
    """Run the session-agent adapter checks, each on a fresh agent."""
    checks: list[ConformanceCheck] = []

    async def record(
        check_id: str, name: str, fn: Callable[[], Coroutine[object, object, tuple[bool, str]]]
    ) -> None:
        try:
            passed, note = await fn()
        except Exception as error:  # noqa: BLE001 - a crashing adapter fails
            checks.append(
                ConformanceCheck(
                    check_id=check_id,
                    name=name,
                    passed=False,
                    note=f"raised {type(error).__name__}: {error}",
                )
            )
            return
        checks.append(ConformanceCheck(check_id=check_id, name=name, passed=passed, note=note))

    async def agt01() -> tuple[bool, str]:
        reply = await factory().say("Hello, what can you do?")
        ok = isinstance(reply, SessionReply) and isinstance(reply.text, str)
        return ok, f"reply type={type(reply).__name__}"

    await record("AGT-01", "responds to an utterance with a session reply", agt01)

    async def agt02() -> tuple[bool, str]:
        reply = await factory().say("")
        return isinstance(reply.text, str), "empty utterance tolerated"

    await record("AGT-02", "tolerates an empty utterance", agt02)

    async def agt03() -> tuple[bool, str]:
        reply = await factory().say("Tell me something.")
        json.dumps(reply.metadata)  # must be JSON-serializable
        return isinstance(reply.metadata, dict), "metadata is a JSON object"

    await record("AGT-03", "reply metadata is JSON-serializable", agt03)

    async def agt04() -> tuple[bool, str]:
        token = f"probe-{uuid.uuid4().hex}"
        first, second = factory(), factory()
        if first is second:
            return False, "factory returned the same instance twice"
        await first.say(f"Remember this code: {token}")
        reply = await second.say("What code did I ask you to remember?")
        return token not in reply.text, "no state leaks between fresh instances"

    await record("AGT-04", "fresh instances are session-isolated", agt04)

    async def agt05() -> tuple[bool, str]:
        probe = factory()
        for _ in range(5):
            reply = await probe.say("Continue.")
            if not isinstance(reply, SessionReply) or not isinstance(reply.text, str):
                return False, f"utterance returned {type(reply).__name__}"
        return True, "five consecutive utterances answered with session replies"

    await record("AGT-05", "sustains a multi-turn conversation", agt05)

    return ConformanceReport(checks=tuple(checks), subject="session-agent")


def check_state_provider(factory: StateProviderFactory) -> ConformanceReport:
    """Run the state-provider checks, each on a fresh provider."""
    checks: list[ConformanceCheck] = []

    def record(check_id: str, name: str, fn: Callable[[], tuple[bool, str]]) -> None:
        try:
            passed, note = fn()
        except Exception as error:  # noqa: BLE001 - a crashing provider fails
            checks.append(
                ConformanceCheck(
                    check_id=check_id,
                    name=name,
                    passed=False,
                    note=f"raised {type(error).__name__}: {error}",
                )
            )
            return
        checks.append(ConformanceCheck(check_id=check_id, name=name, passed=passed, note=note))

    probe_state: JsonObject = {"__provider_probe__": {"items": [1, 2, 3], "flag": True}}

    def sp01() -> tuple[bool, str]:
        provider = factory()
        provider.seed(probe_state)
        return provider.snapshot() == probe_state, "seed then snapshot round-trips"

    record("SP-01", "seed/snapshot round-trip", sp01)

    def sp02() -> tuple[bool, str]:
        provider = factory()
        provider.seed(probe_state)
        snap = provider.snapshot()
        snap["__provider_probe__"] = "mutated"
        return provider.snapshot() == probe_state, "snapshot isolation"

    record("SP-02", "snapshot isolation", sp02)

    def sp03() -> tuple[bool, str]:
        provider = factory()
        provider.seed(probe_state)
        provider.reset()
        return "__provider_probe__" not in provider.snapshot(), "reset removes seeded state"

    record("SP-03", "reset clears run residue", sp03)

    def sp04() -> tuple[bool, str]:
        provider = factory()
        provider.seed(probe_state)
        first = provider.snapshot()
        provider.reset()
        provider.seed(probe_state)
        return provider.snapshot() == first, "re-seed after reset is deterministic"

    record("SP-04", "deterministic re-seed", sp04)

    return ConformanceReport(checks=tuple(checks), subject="state-provider")
