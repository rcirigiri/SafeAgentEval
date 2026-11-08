"""Black-box (Profile C) scenario orchestration for session agents.

The agent receives scripted customer utterances, executes its own tools
internally, and is graded on the final state read through a StateProvider.
No gate mediation or fault injection is possible in this mode; every result
is labeled ``ExecutionMode.BLACK_BOX`` so verdicts are never conflated with
mediated ones. The state scorer, claim verifier, and trace format are shared
with the mediated runner.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from safeagenteval.agents.session import SessionAgent
from safeagenteval.backends.state_provider import StateProvider
from safeagenteval.claims.verifier import ActionClaim, ClaimExtractor, verify_claims
from safeagenteval.core.models import (
    Configuration,
    ExecutionMode,
    Scenario,
)
from safeagenteval.harness.runner import RunResult, _RunAborted
from safeagenteval.scoring.state import score_state
from safeagenteval.trace.recorder import EventKind, TraceRecorder, utc_now


async def run_session_scenario(
    scenario: Scenario,
    agent: SessionAgent,
    provider: StateProvider,
    claim_extractor: ClaimExtractor | None = None,
    *,
    max_exchanges_per_turn: int = 4,
    clock: Callable[[], datetime] = utc_now,
) -> RunResult:
    """Run one black-box scenario and grade the provider's final snapshot.

    When the agent's reply matches a scenario-declared clarification (and
    reads as a question), the customer answers from the declared facts and
    the exchange continues within the same turn. A clarification is never a
    trusted confirmation. Agent exceptions abort the run and are scored.
    """
    recorder = TraceRecorder(clock)
    claims: list[ActionClaim] = []
    aborted_reason: str | None = None

    provider.reset()
    provider.seed(scenario.initial_state)
    seeded_state = provider.snapshot()
    recorder.record(
        EventKind.RUN_STARTED,
        "run",
        {
            "scenario_id": scenario.scenario_id,
            "configuration": Configuration.C0.value,
            "execution_mode": ExecutionMode.BLACK_BOX.value,
            "initial_state": seeded_state,
        },
    )
    recorder.record(EventKind.EXTERNAL_STATE, "run", {"phase": "seeded", "state": seeded_state})

    used_clarifications: set[str] = set()

    async def exchange(turn_id: str, first_text: str) -> None:
        text = first_text
        for _ in range(max_exchanges_per_turn):
            try:
                reply = await agent.say(text)
            except Exception as error:  # noqa: BLE001 - untrusted component
                raise _RunAborted(f"agent raised {type(error).__name__}: {error}") from error
            if reply.text:
                reply_event = recorder.record(
                    EventKind.AGENT_REPLY, turn_id, {"reply": reply.text}
                )
                if claim_extractor is not None:
                    try:
                        claims.extend(
                            await claim_extractor.extract(
                                reply.text, reply_event.sequence, turn_id
                            )
                        )
                    except Exception as error:  # noqa: BLE001 - untrusted component
                        raise _RunAborted(
                            f"claim extractor raised {type(error).__name__}: {error}"
                        ) from error
            if reply.metadata:
                recorder.record(
                    EventKind.AGENT_METADATA, turn_id, {"metadata": reply.metadata}
                )
            answer = _clarification_answer(scenario, reply.text, used_clarifications)
            if answer is None:
                return
            used_clarifications.add(answer[0])
            recorder.record(
                EventKind.CUSTOMER_MESSAGE,
                turn_id,
                {"message": answer[1], "confirms_intent_id": None, "clarification": True},
            )
            text = answer[1]
        raise _RunAborted(f"agent exceeded {max_exchanges_per_turn} exchanges during {turn_id}")

    for customer_turn in scenario.customer_turns:
        recorder.record(
            EventKind.CUSTOMER_MESSAGE,
            customer_turn.turn_id,
            {
                "message": customer_turn.message,
                "confirms_intent_id": customer_turn.confirms_intent_id,
            },
        )
        try:
            await exchange(customer_turn.turn_id, customer_turn.message)
        except _RunAborted as abort:
            aborted_reason = str(abort)
            recorder.record(
                EventKind.RUN_ABORTED, customer_turn.turn_id, {"reason": aborted_reason}
            )
            break

    final_state = provider.snapshot()
    recorder.record(EventKind.EXTERNAL_STATE, "run", {"phase": "final", "state": final_state})
    recorder.record(EventKind.FINAL_STATE, "run", {"state": final_state})
    events = tuple(recorder.events)
    claim_tuple = tuple(claims)
    return RunResult(
        scenario_id=scenario.scenario_id,
        configuration=Configuration.C0,
        execution_mode=ExecutionMode.BLACK_BOX,
        final_state=final_state,
        events=events,
        state_score=score_state(scenario, final_state, events),
        claims=claim_tuple,
        claim_verdicts=verify_claims(claim_tuple, events),
        aborted_reason=aborted_reason,
    )


def _clarification_answer(
    scenario: Scenario, reply_text: str, used: set[str]
) -> tuple[str, str] | None:
    """Return (match, answer) if the reply asks about a declared fact."""
    if "?" not in reply_text:
        return None
    lowered = reply_text.lower()
    for clarification in scenario.clarifications:
        if clarification.match in used:
            continue
        if clarification.match.lower() in lowered:
            return clarification.match, clarification.answer
    return None
