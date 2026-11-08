"""End-to-end scenario orchestration."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from typing import cast

from safeagenteval.agents.base import AgentAdapter
from safeagenteval.backends.base import DomainBackend
from safeagenteval.claims.verifier import (
    ActionClaim,
    ClaimExtractor,
    ClaimVerdict,
    verify_claims,
)
from safeagenteval.core.models import (
    BackendExecution,
    Configuration,
    ExecutionMode,
    FrozenModel,
    JsonObject,
    Message,
    Role,
    Scenario,
    ToolResult,
    ToolStatus,
)
from safeagenteval.faults.injector import FaultInjector, InjectedExecution
from safeagenteval.policies.enforcement import ActionEnforcer, TrustedSessionState
from safeagenteval.policies.intents import IntentResolver, canonical_json
from safeagenteval.scoring.state import StateScore, score_state
from safeagenteval.trace.recorder import EventKind, TraceEvent, TraceRecorder, utc_now


class RunResult(FrozenModel):
    """Complete evidence and deterministic scores for one run."""

    scenario_id: str
    configuration: Configuration
    execution_mode: ExecutionMode = ExecutionMode.MEDIATED
    final_state: JsonObject
    events: tuple[TraceEvent, ...]
    state_score: StateScore
    claims: tuple[ActionClaim, ...]
    claim_verdicts: tuple[ClaimVerdict, ...]
    aborted_reason: str | None = None

    @property
    def completed(self) -> bool:
        """Whether every scripted customer turn ran to completion."""
        return self.aborted_reason is None


class _RunAborted(Exception):
    """Internal signal that the run must stop and be scored as aborted."""


def intent_key(tool_name: str, resolved_intent_id: str | None, normalized: JsonObject) -> str:
    """Key used to count commits: the declared intent, else the call content."""
    if resolved_intent_id is not None:
        return f"intent:{resolved_intent_id}"
    return f"content:{tool_name}:{canonical_json(normalized)}"


async def run_scenario(
    scenario: Scenario,
    agent: AgentAdapter,
    backend: DomainBackend,
    configuration: Configuration,
    claim_extractor: ClaimExtractor | None = None,
    *,
    max_agent_steps_per_customer_turn: int = 8,
    clock: Callable[[], datetime] = utc_now,
) -> RunResult:
    """Run one scenario through the trusted evaluation boundary.

    Agent or claim-extractor exceptions and step-limit overruns do not raise;
    they are recorded as a ``run_aborted`` event and the partial run is scored,
    so a crashing or looping agent still yields evidence.
    """
    recorder = TraceRecorder(clock)
    session = TrustedSessionState()
    tools = tuple(backend.tools)
    tool_effects = {tool.name: tool.effect.value for tool in tools}
    enforcer = ActionEnforcer(configuration, scenario.authorization, tools)
    resolver = IntentResolver(scenario.intents, backend)
    faults = FaultInjector(scenario.fault_schedule)
    messages: list[Message] = []
    claims: list[ActionClaim] = []
    aborted_reason: str | None = None

    recorder.record(
        EventKind.RUN_STARTED,
        "run",
        {
            "scenario_id": scenario.scenario_id,
            "configuration": configuration.value,
            "initial_state": backend.snapshot(),
        },
    )

    def settle(steps: int = 1) -> None:
        """Advance a tickable backend and record settlement transitions."""
        tick = getattr(backend, "tick", None)
        if not callable(tick):
            return
        for execution in tick(steps):
            result_json_inner = _json_object(execution.result.model_dump(mode="json"))
            recorder.record(
                EventKind.TOOL_RESULT, "settlement", {"result": result_json_inner}
            )
            if execution.changes:
                recorder.record(
                    EventKind.STATE_DIFF,
                    "settlement",
                    {
                        "call_id": execution.result.call_id,
                        "changes": [
                            change.model_dump(mode="json") for change in execution.changes
                        ],
                    },
                )

    async def run_customer_turn(turn_id: str) -> None:
        for _ in range(max_agent_steps_per_customer_turn):
            try:
                agent_turn = await agent.respond(tuple(messages), tools)
            except Exception as error:  # noqa: BLE001 - untrusted component
                raise _RunAborted(f"agent raised {type(error).__name__}: {error}") from error

            if agent_turn.reply:
                messages.append(Message(role=Role.AGENT, content=agent_turn.reply, turn_id=turn_id))
                reply_event = recorder.record(
                    EventKind.AGENT_REPLY, turn_id, {"reply": agent_turn.reply}
                )
                if claim_extractor is not None:
                    try:
                        claims.extend(
                            await claim_extractor.extract(
                                agent_turn.reply, reply_event.sequence, turn_id
                            )
                        )
                    except Exception as error:  # noqa: BLE001 - untrusted component
                        raise _RunAborted(
                            f"claim extractor raised {type(error).__name__}: {error}"
                        ) from error

            if not agent_turn.tool_calls:
                return

            for call in agent_turn.tool_calls:
                normalized = resolver.normalize(call)
                resolved = resolver.resolve(call, normalized)
                key = intent_key(call.name, resolved, normalized)
                recorder.record(
                    EventKind.TOOL_CALL,
                    turn_id,
                    {
                        "call": {
                            **_json_object(call.model_dump(mode="json")),
                            "normalized_arguments": normalized,
                            "resolved_intent_id": resolved,
                            "intent_key": key,
                            "confirmation_received": (
                                resolved is not None and resolved in session.confirmed_intents
                            ),
                            "effect": tool_effects.get(call.name, "unknown"),
                        }
                    },
                )
                decision = enforcer.decide(
                    call, resolved, session, intent_key=key, normalized_arguments=normalized
                )
                recorder.record(
                    EventKind.POLICY_DECISION,
                    turn_id,
                    {
                        "call_id": call.call_id,
                        "allowed": decision.allowed,
                        "reason": decision.reason,
                    },
                )

                if decision.allowed:
                    injected = faults.execute(backend, call)
                else:
                    denied = _denied_execution(call.call_id, call.name, decision.reason)
                    injected = InjectedExecution(execution=denied, visible_result=denied.result)
                execution = injected.execution
                if execution.result.committed:
                    session.record_commit(key)

                result_json = _json_object(execution.result.model_dump(mode="json"))
                visible_json = _json_object(injected.visible_result.model_dump(mode="json"))
                result_payload: JsonObject = {"result": result_json}
                if injected.fault is not None:
                    result_payload["fault"] = injected.fault.value
                    result_payload["agent_visible_result"] = visible_json
                recorder.record(EventKind.TOOL_RESULT, turn_id, result_payload)
                if execution.changes:
                    recorder.record(
                        EventKind.STATE_DIFF,
                        turn_id,
                        {
                            "call_id": call.call_id,
                            "changes": [
                                change.model_dump(mode="json") for change in execution.changes
                            ],
                        },
                    )
                messages.append(
                    Message(
                        role=Role.TOOL,
                        content=json.dumps(visible_json, sort_keys=True),
                        turn_id=turn_id,
                    )
                )
                settle(1)
        raise _RunAborted(
            f"agent exceeded {max_agent_steps_per_customer_turn} steps during {turn_id}"
        )

    for customer_turn in scenario.customer_turns:
        if customer_turn.confirms_intent_id is not None:
            session.confirm(customer_turn.confirms_intent_id)
        messages.append(
            Message(
                role=Role.CUSTOMER,
                content=customer_turn.message,
                turn_id=customer_turn.turn_id,
            )
        )
        recorder.record(
            EventKind.CUSTOMER_MESSAGE,
            customer_turn.turn_id,
            {
                "message": customer_turn.message,
                "confirms_intent_id": customer_turn.confirms_intent_id,
            },
        )
        try:
            await run_customer_turn(customer_turn.turn_id)
        except _RunAborted as abort:
            aborted_reason = str(abort)
            recorder.record(
                EventKind.RUN_ABORTED, customer_turn.turn_id, {"reason": aborted_reason}
            )
            break

    # Finalize settlement up to the scenario horizon so final states show
    # settled money unless a scenario deliberately ends mid-flight.
    for _ in range(scenario.settlement_horizon_ticks):
        before = backend.snapshot()
        settle(1)
        if backend.snapshot() == before:
            break

    final_state = backend.snapshot()
    recorder.record(EventKind.FINAL_STATE, "run", {"state": final_state})
    events = tuple(recorder.events)
    claim_tuple = tuple(claims)
    return RunResult(
        scenario_id=scenario.scenario_id,
        configuration=configuration,
        final_state=final_state,
        events=events,
        state_score=score_state(scenario, final_state, events),
        claims=claim_tuple,
        claim_verdicts=verify_claims(claim_tuple, events),
        aborted_reason=aborted_reason,
    )


def _denied_execution(call_id: str, name: str, reason: str) -> BackendExecution:
    return BackendExecution(
        result=ToolResult(
            call_id=call_id,
            name=name,
            status=ToolStatus.DENIED,
            error=reason,
        )
    )


def _json_object(value: object) -> JsonObject:
    if not isinstance(value, dict):
        raise TypeError("expected a JSON object")
    return cast(JsonObject, value)
