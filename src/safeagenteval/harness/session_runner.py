"""Black-box scenario orchestration for session agents.

The agent receives scripted customer utterances, executes its own tools
internally, and is graded on the final state read through a StateProvider.
The harness provides no tools, executes no calls, and applies no gate.

Failure policy: agent, claim-extractor, and StateProvider exceptions do
not raise out of a run. They are recorded as ``run_aborted`` and the
partial run is scored, so a crashing component still yields evidence.
State is deep-copied at every trust boundary (seed in, snapshots out) so
a provider or caller mutating a dict cannot contaminate the scenario,
the trace, or a later repeat.
"""

from __future__ import annotations

import copy
import inspect
import uuid
from collections.abc import Callable
from datetime import datetime
from typing import TypeVar

from safeagenteval.agents.session import SessionAgent
from safeagenteval.backends.state_provider import AsyncStateProvider, StateProvider
from safeagenteval.claims.verifier import (
    ActionClaim,
    ClaimExtractor,
    ClaimVerdict,
    ClaimVerdictValue,
    verify_claims,
)
from safeagenteval.core.models import FrozenModel, JsonObject, Scenario
from safeagenteval.scoring.invariants import check_state_invariants
from safeagenteval.scoring.state import StateScore, score_state
from safeagenteval.trace.recorder import EventKind, TraceEvent, TraceRecorder, utc_now, verify_trace

EXECUTION_MODE = "black_box"
"""Value written as ``execution_mode`` in run records."""

_T = TypeVar("_T")


async def _maybe_await(value: _T | object) -> _T:
    """Await ``value`` if a provider method returned an awaitable."""
    if inspect.isawaitable(value):
        return await value  # type: ignore[no-any-return]
    return value  # type: ignore[return-value]


class RunResult(FrozenModel):
    """Complete evidence and deterministic scores for one run."""

    scenario_id: str
    final_state: JsonObject
    events: tuple[TraceEvent, ...]
    state_score: StateScore
    claims: tuple[ActionClaim, ...]
    claim_verdicts: tuple[ClaimVerdict, ...]
    reply_violations: tuple[str, ...] = ()
    invariant_violations: tuple[str, ...] = ()
    aborted_reason: str | None = None

    @property
    def completed(self) -> bool:
        """Whether every scripted customer turn ran to completion."""
        return self.aborted_reason is None

    @property
    def state_passed(self) -> bool:
        """The purely state-based verdict (no claim-extractor involvement).

        Completed, ended in an authorized final state, state invariants
        hold, no forbidden reply content, and an intact hash-linked
        trace. This is the headline metric; ``passed`` additionally
        requires that no extracted claim was contradicted.
        """
        return bool(
            self.completed
            and self.state_score.final_state_correct
            and not self.invariant_violations
            and not self.reply_violations
            and verify_trace(self.events)
        )

    @property
    def passed(self) -> bool:
        """The single pass rule for a black-box run.

        ``state_passed`` and no contradicted claim. The CLI and reporting
        consume this property; they do not redefine it.
        """
        return bool(
            self.state_passed
            and not any(
                verdict.verdict is ClaimVerdictValue.CONTRADICTED for verdict in self.claim_verdicts
            )
        )


class _RunAborted(Exception):
    """Internal signal that the run must stop and be scored as aborted."""


async def run_session_scenario(
    scenario: Scenario,
    agent: SessionAgent,
    provider: StateProvider | AsyncStateProvider,
    claim_extractor: ClaimExtractor | None = None,
    *,
    run_id: str | None = None,
    max_exchanges_per_turn: int = 4,
    provider_probe: bool = False,
    clock: Callable[[], datetime] = utc_now,
) -> RunResult:
    """Run one black-box scenario and grade the provider's final snapshot.

    When the agent's reply matches a scenario-declared clarification (and
    reads as a question), the customer answers from the declared facts and
    the exchange continues within the same turn. A clarification is never a
    confirmation.

    Trust controls on the provider (see ``docs/trust_model.md``): the
    state read back immediately after seeding must equal the scenario's
    initial state or the run aborts before the agent acts; a snapshot is
    recorded after every turn so claims are graded against the state in
    force when they were spoken; and with ``provider_probe`` the provider
    must first round-trip a fresh random probe state it cannot predict.
    """
    recorder = TraceRecorder(clock)
    claims: list[ActionClaim] = []
    replies: list[str] = []
    aborted_reason: str | None = None
    final_state: JsonObject = {}

    recorder.record(
        EventKind.RUN_STARTED,
        "run",
        {
            "scenario_id": scenario.scenario_id,
            "execution_mode": EXECUTION_MODE,
            "run_id": run_id,
            "initial_state": copy.deepcopy(scenario.initial_state),
        },
    )

    try:
        set_context = getattr(provider, "set_run_context", None)
        if callable(set_context):
            await _maybe_await(set_context(run_id))
        if provider_probe:
            probe_state: JsonObject = {
                "__safeagenteval_probe__": {"token": uuid.uuid4().hex, "items": [1, 2, 3]}
            }
            await _maybe_await(provider.seed(copy.deepcopy(probe_state)))
            probed: JsonObject = copy.deepcopy(await _maybe_await(provider.snapshot()))
            if probed != probe_state:
                raise _RunAborted("state provider failed the randomized probe round-trip")
            await _maybe_await(provider.reset())
        await _maybe_await(provider.reset())
        await _maybe_await(provider.seed(copy.deepcopy(scenario.initial_state)))
        final_state = copy.deepcopy(await _maybe_await(provider.snapshot()))
        if final_state != scenario.initial_state:
            aborted_reason = (
                "state provider seed read-back mismatch: snapshot after seed "
                "does not equal the scenario initial state"
            )
            recorder.record(EventKind.RUN_ABORTED, "run", {"reason": aborted_reason})
    except _RunAborted as abort:
        aborted_reason = str(abort)
        recorder.record(EventKind.RUN_ABORTED, "run", {"reason": aborted_reason})
    except Exception as error:  # noqa: BLE001 - untrusted component
        aborted_reason = f"state provider raised {type(error).__name__}: {error}"
        recorder.record(EventKind.RUN_ABORTED, "run", {"reason": aborted_reason})

    used_clarifications: set[str] = set()

    async def exchange(turn_id: str, first_text: str) -> None:
        text = first_text
        for _ in range(max_exchanges_per_turn):
            try:
                reply = await agent.say(text)
            except Exception as error:  # noqa: BLE001 - untrusted component
                raise _RunAborted(f"agent raised {type(error).__name__}: {error}") from error
            if reply.text:
                replies.append(reply.text)
                reply_event = recorder.record(EventKind.AGENT_REPLY, turn_id, {"reply": reply.text})
                if claim_extractor is not None:
                    try:
                        claims.extend(
                            await claim_extractor.extract(reply.text, reply_event.sequence, turn_id)
                        )
                    except Exception as error:  # noqa: BLE001 - untrusted component
                        raise _RunAborted(
                            f"claim extractor raised {type(error).__name__}: {error}"
                        ) from error
            if reply.metadata:
                recorder.record(EventKind.AGENT_METADATA, turn_id, {"metadata": reply.metadata})
            answer = _clarification_answer(scenario, reply.text, used_clarifications)
            if answer is None:
                return
            used_clarifications.add(answer[0])
            recorder.record(
                EventKind.CUSTOMER_MESSAGE,
                turn_id,
                {"message": answer[1], "clarification": True},
            )
            text = answer[1]
        raise _RunAborted(f"agent exceeded {max_exchanges_per_turn} exchanges during {turn_id}")

    if aborted_reason is None:
        for customer_turn in scenario.customer_turns:
            recorder.record(
                EventKind.CUSTOMER_MESSAGE,
                customer_turn.turn_id,
                {"message": customer_turn.message},
            )
            try:
                await exchange(customer_turn.turn_id, customer_turn.message)
            except _RunAborted as abort:
                aborted_reason = str(abort)
                recorder.record(
                    EventKind.RUN_ABORTED, customer_turn.turn_id, {"reason": aborted_reason}
                )
                break
            try:
                turn_state: JsonObject = copy.deepcopy(
                    await _maybe_await(provider.snapshot())
                )
                recorder.record(
                    EventKind.TURN_STATE,
                    customer_turn.turn_id,
                    {"state": copy.deepcopy(turn_state)},
                )
            except Exception as error:  # noqa: BLE001 - untrusted component
                aborted_reason = f"state provider raised {type(error).__name__}: {error}"
                recorder.record(
                    EventKind.RUN_ABORTED, customer_turn.turn_id, {"reason": aborted_reason}
                )
                break

        try:
            final_state = copy.deepcopy(await _maybe_await(provider.snapshot()))
        except Exception as error:  # noqa: BLE001 - untrusted component
            provider_error = f"state provider raised {type(error).__name__}: {error}"
            aborted_reason = aborted_reason or provider_error
            recorder.record(EventKind.RUN_ABORTED, "run", {"reason": provider_error})

    reply_violations = tuple(
        forbidden
        for forbidden in scenario.forbidden_reply_content
        if any(forbidden.lower() in reply.lower() for reply in replies)
    )
    if reply_violations:
        recorder.record(
            EventKind.REPLY_VIOLATION,
            "run",
            {"forbidden_content": list(reply_violations)},
        )
    invariant_violations = check_state_invariants(scenario.initial_state, final_state)
    if invariant_violations:
        recorder.record(
            EventKind.INVARIANT_VIOLATION,
            "run",
            {"violations": list(invariant_violations)},
        )
    recorder.record(EventKind.FINAL_STATE, "run", {"state": copy.deepcopy(final_state)})
    events = tuple(recorder.events)
    claim_tuple = tuple(claims)
    return RunResult(
        scenario_id=scenario.scenario_id,
        final_state=final_state,
        events=events,
        state_score=score_state(scenario, final_state),
        claims=claim_tuple,
        claim_verdicts=verify_claims(claim_tuple, events),
        reply_violations=reply_violations,
        invariant_violations=invariant_violations,
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
