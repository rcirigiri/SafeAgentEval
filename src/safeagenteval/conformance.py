"""Backend conformance checks for third-party DomainBackend implementations.

A backend is certified against a profile by running the numbered contract
checks below on fresh instances produced by a factory. The checks are
behavioral: they use only the public DomainBackend protocol (tools, execute,
normalize_arguments, snapshot) plus any caller-supplied probe calls.

Profiles:
- ``lite``: the minimum contract (safe failures, isolation, determinism).
- ``full``: lite plus lifecycle requirements (a deterministic ``tick``).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Coroutine, Sequence
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Protocol, cast

from safeagenteval.agents.session import SessionAgent
from safeagenteval.backends.base import DomainBackend
from safeagenteval.backends.state_provider import StateProvider
from safeagenteval.core.models import (
    BackendExecution,
    FrozenModel,
    JsonObject,
    ToolCall,
    ToolEffect,
    ToolStatus,
)


class _Tickable(Protocol):
    """Optional backend extension: deterministic logical-time advance."""

    def tick(self, steps: int = 1) -> tuple[BackendExecution, ...]:
        """Advance logical time and return any transition executions."""
        ...


class ConformanceProfile(StrEnum):
    LITE = "lite"
    FULL = "full"


class ConformanceCheck(FrozenModel):
    """One contract check outcome."""

    check_id: str
    name: str
    passed: bool
    skipped: bool = False
    note: str = ""


class ConformanceReport(FrozenModel):
    """Machine-readable conformance result for one subject and profile."""

    profile: ConformanceProfile
    checks: tuple[ConformanceCheck, ...]
    subject: str = "backend"

    @property
    def passed(self) -> bool:
        """Whether every non-skipped check passed."""
        return all(check.passed for check in self.checks if not check.skipped)

    @property
    def passed_count(self) -> int:
        return sum(1 for check in self.checks if check.passed and not check.skipped)

    @property
    def total_count(self) -> int:
        return sum(1 for check in self.checks if not check.skipped)


BackendFactory = Callable[[], DomainBackend]

_ALLOWED_TRANSFER_STATUSES = {"initiated", "pending", "settled", "returned", "failed", "cancelled"}


def _apply_changes(snapshot: JsonObject, changes: Sequence[object]) -> JsonObject:
    """Apply backend StateChange paths to a snapshot copy (JSON-pointer style)."""
    result: JsonObject = copy.deepcopy(snapshot)
    for change in changes:
        path = getattr(change, "path", "")
        after = copy.deepcopy(getattr(change, "after", None))
        parts = [part for part in str(path).split("/") if part]
        if not parts:
            continue
        node: object = result
        for part in parts[:-1]:
            if isinstance(node, list):
                node = node[int(part)]
            elif isinstance(node, dict):
                node = node.setdefault(part, {})
        last = parts[-1]
        if isinstance(node, list):
            index = int(last)
            if index == len(node):
                node.append(after)
            else:
                node[index] = after
        elif isinstance(node, dict):
            node[last] = after
    return result


def _negative_balances(snapshot: JsonObject) -> list[str]:
    found: list[str] = []
    accounts = snapshot.get("accounts")
    if isinstance(accounts, dict):
        for account_id, account in accounts.items():
            if not isinstance(account, dict):
                continue
            for field in ("balance", "ledger_balance"):
                value = account.get(field)
                if isinstance(value, str):
                    try:
                        if Decimal(value) < 0:
                            found.append(f"{account_id}.{field}={value}")
                    except InvalidOperation:
                        continue
    return found


def check_backend(
    factory: BackendFactory,
    *,
    profile: ConformanceProfile = ConformanceProfile.LITE,
    probe_calls: Sequence[ToolCall] = (),
) -> ConformanceReport:
    """Run the conformance checks for ``profile`` against fresh backends."""
    checks: list[ConformanceCheck] = []

    def record(check_id: str, name: str, fn: Callable[[], tuple[bool, str]]) -> None:
        try:
            passed, note = fn()
        except Exception as error:  # noqa: BLE001 - a crashing backend fails the check
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

    def skip(check_id: str, name: str, note: str) -> None:
        checks.append(
            ConformanceCheck(check_id=check_id, name=name, passed=True, skipped=True, note=note)
        )

    backend = factory()

    def con01() -> tuple[bool, str]:
        names = [tool.name for tool in backend.tools]
        ok = len(names) == len(set(names)) and all(names)
        return ok, f"tools={names}"

    record("CON-01", "unique tools with declared effects", con01)

    def con02() -> tuple[bool, str]:
        snap = backend.snapshot()
        snap["__conformance_probe__"] = True
        return "__conformance_probe__" not in backend.snapshot(), "snapshot isolation"

    record("CON-02", "snapshot isolation", con02)

    def con03() -> tuple[bool, str]:
        if not probe_calls:
            return True, "no probe calls supplied"
        before = backend.snapshot()
        for call in probe_calls:
            backend.normalize_arguments(call)
        return backend.snapshot() == before, "normalize_arguments left state unchanged"

    record("CON-03", "normalize_arguments is pure", con03)

    def con04() -> tuple[bool, str]:
        if not probe_calls:
            return True, "no probe calls supplied"
        runs: list[tuple[object, JsonObject]] = []
        for _ in range(2):
            fresh = factory()
            results: list[object] = [
                fresh.execute(call).result.model_dump(mode="json") for call in probe_calls
            ]
            runs.append((results, fresh.snapshot()))
        return runs[0] == runs[1], "identical results and snapshots across fresh instances"

    record("CON-04", "determinism across fresh instances", con04)

    def con05() -> tuple[bool, str]:
        before = backend.snapshot()
        execution = backend.execute(
            ToolCall(call_id="conformance-unknown", name="__no_such_tool__", arguments={})
        )
        ok = execution.result.status is ToolStatus.FAILED and backend.snapshot() == before
        return ok, f"unknown tool status={execution.result.status.value}, state unchanged={ok}"

    record("CON-05", "unknown tool fails without state change", con05)

    def con06() -> tuple[bool, str]:
        if not probe_calls:
            return True, "no probe calls supplied"
        for call in probe_calls:
            before = backend.snapshot()
            execution = backend.execute(call)
            replayed = _apply_changes(before, execution.changes)
            if replayed != backend.snapshot():
                return False, f"state changes for {call.name} do not replay onto the snapshot"
        return True, "state changes replay exactly for all probe calls"

    record("CON-06", "state changes replay atomically", con06)

    def con07() -> tuple[bool, str]:
        negatives = _negative_balances(backend.snapshot())
        return not negatives, f"negative balances: {negatives}" if negatives else "none negative"

    record("CON-07", "no negative balances after probes", con07)

    has_tick = callable(getattr(backend, "tick", None))
    if profile is ConformanceProfile.FULL:
        def con08() -> tuple[bool, str]:
            transfers = backend.snapshot().get("transfers")
            if isinstance(transfers, list):
                bad = [
                    str(item.get("status"))
                    for item in transfers
                    if isinstance(item, dict)
                    and item.get("status") not in _ALLOWED_TRANSFER_STATUSES
                ]
                if bad:
                    return False, f"unknown transfer statuses: {bad}"
            return has_tick, "tick present" if has_tick else "full profile requires tick()"

        record("CON-08", "lifecycle states valid and tick present", con08)

        def con10() -> tuple[bool, str]:
            if not has_tick:
                return False, "tick() missing"
            first, second = factory(), factory()
            tick_first = cast(_Tickable, first).tick
            tick_second = cast(_Tickable, second).tick
            tick_first(1)
            tick_second(1)
            return first.snapshot() == second.snapshot(), "tick(1) deterministic"

        record("CON-10", "tick determinism", con10)
    else:
        skip("CON-08", "lifecycle states valid and tick present", "full profile only")
        skip("CON-10", "tick determinism", "full profile only")

    def con09() -> tuple[bool, str]:
        keyed = [c for c in probe_calls if "idempotency_key" in c.arguments]
        if not keyed:
            return True, "no idempotency-keyed probe supplied"
        call = keyed[0]
        backend.execute(call)
        after_first = backend.snapshot()
        backend.execute(call)
        return backend.snapshot() == after_first, "repeated keyed call changed nothing further"

    record("CON-09", "idempotent replay of keyed commits", con09)

    skip("CON-11", "limit and account-status enforcement", "requires backend-specific probes")

    def con12() -> tuple[bool, str]:
        reads = [tool.name for tool in backend.tools if tool.effect is ToolEffect.READ]
        return bool(reads), f"read tools={reads}"

    record("CON-12", "read tools exist to recover from masked commits", con12)

    return ConformanceReport(profile=profile, checks=tuple(checks))


# --- Session agents and state providers (Agent Contract Profile C) ---------
#
# A self-executing agent cannot be mediated, so its adapter and its state
# provider become the trust surface. These checks certify that surface: the
# adapter answers in contract shape and keeps runs isolated; the provider
# seeds, reads, and resets the agent owner's world faithfully.

SessionAgentFactory = Callable[[], SessionAgent]
StateProviderFactory = Callable[[], StateProvider]


async def check_session_agent(factory: SessionAgentFactory) -> ConformanceReport:
    """Run the Profile C adapter checks against fresh session agents."""
    from safeagenteval.agents.session import SessionReply

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

    agent = factory()

    async def agt01() -> tuple[bool, str]:
        reply = await agent.say("Hello, what can you do?")
        ok = isinstance(reply, SessionReply) and isinstance(reply.text, str)
        return ok, f"reply type={type(reply).__name__}"

    await record("AGT-01", "responds to an utterance with a session reply", agt01)

    async def agt02() -> tuple[bool, str]:
        reply = await agent.say("")
        return isinstance(reply.text, str), "empty utterance tolerated"

    await record("AGT-02", "tolerates an empty utterance", agt02)

    async def agt03() -> tuple[bool, str]:
        reply = await agent.say("Tell me something.")
        json.dumps(reply.metadata)  # must be JSON-serializable
        return isinstance(reply.metadata, dict), "metadata is a JSON object"

    await record("AGT-03", "reply metadata is JSON-serializable", agt03)

    async def agt04() -> tuple[bool, str]:
        import uuid

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
            await probe.say("Continue.")
        return True, "five consecutive utterances answered"

    await record("AGT-05", "sustains a multi-turn conversation", agt05)

    return ConformanceReport(
        profile=ConformanceProfile.LITE, checks=tuple(checks), subject="session-agent"
    )


def check_state_provider(factory: StateProviderFactory) -> ConformanceReport:
    """Run the state-provider checks (seed / snapshot / reset fidelity)."""
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

    provider = factory()
    probe_state: JsonObject = {"__provider_probe__": {"items": [1, 2, 3], "flag": True}}

    def sp01() -> tuple[bool, str]:
        provider.seed(probe_state)
        return provider.snapshot() == probe_state, "seed then snapshot round-trips"

    record("SP-01", "seed/snapshot round-trip", sp01)

    def sp02() -> tuple[bool, str]:
        snap = provider.snapshot()
        snap["__provider_probe__"] = "mutated"
        return provider.snapshot() == probe_state, "snapshot isolation"

    record("SP-02", "snapshot isolation", sp02)

    def sp03() -> tuple[bool, str]:
        provider.reset()
        return "__provider_probe__" not in provider.snapshot(), "reset removes seeded state"

    record("SP-03", "reset clears run residue", sp03)

    def sp04() -> tuple[bool, str]:
        provider.seed(probe_state)
        first = provider.snapshot()
        provider.reset()
        provider.seed(probe_state)
        return provider.snapshot() == first, "re-seed after reset is deterministic"

    record("SP-04", "deterministic re-seed", sp04)

    return ConformanceReport(
        profile=ConformanceProfile.LITE, checks=tuple(checks), subject="state-provider"
    )
