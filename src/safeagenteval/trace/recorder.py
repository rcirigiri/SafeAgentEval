"""Append-only, hash-linked execution traces.

The hash chain makes a trace tamper-evident: any edit, insertion, deletion, or
reordering of events is detected by :func:`verify_trace`. It does not by itself
prove authorship; publish or sign the final ``event_hash`` alongside the run
manifest to anchor a trace.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Sequence
from copy import deepcopy
from datetime import UTC, datetime
from enum import StrEnum

from safeagenteval.core.models import FrozenModel, JsonObject


class EventKind(StrEnum):
    """Event types recorded during one benchmark run."""

    RUN_STARTED = "run_started"
    CUSTOMER_MESSAGE = "customer_message"
    AGENT_REPLY = "agent_reply"
    AGENT_METADATA = "agent_metadata"
    EXTERNAL_STATE = "external_state"
    TOOL_CALL = "tool_call"
    POLICY_DECISION = "policy_decision"
    TOOL_RESULT = "tool_result"
    STATE_DIFF = "state_diff"
    FINAL_STATE = "final_state"
    RUN_ABORTED = "run_aborted"


class TraceEvent(FrozenModel):
    """One immutable event in a hash-linked trace."""

    sequence: int
    kind: EventKind
    turn_id: str
    occurred_at: datetime
    payload: JsonObject
    previous_hash: str
    event_hash: str


def utc_now() -> datetime:
    """Return the current UTC time; the default trace clock."""
    return datetime.now(UTC)


def _compute_hash(
    sequence: int,
    kind: EventKind,
    turn_id: str,
    occurred_at: datetime,
    payload: JsonObject,
    previous_hash: str,
) -> str:
    hash_input = {
        "sequence": sequence,
        "kind": kind.value,
        "turn_id": turn_id,
        "occurred_at": occurred_at.isoformat(),
        "payload": payload,
        "previous_hash": previous_hash,
    }
    canonical = json.dumps(hash_input, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def verify_trace(events: Sequence[TraceEvent]) -> bool:
    """Return ``True`` if sequence numbers, links, and every hash recompute."""
    previous_hash = "GENESIS"
    for index, event in enumerate(events, start=1):
        if event.sequence != index or event.previous_hash != previous_hash:
            return False
        expected = _compute_hash(
            event.sequence,
            event.kind,
            event.turn_id,
            event.occurred_at,
            event.payload,
            event.previous_hash,
        )
        if expected != event.event_hash:
            return False
        previous_hash = event.event_hash
    return True


class TraceRecorder:
    """Record ordered evidence without exposing mutation to the agent."""

    def __init__(self, clock: Callable[[], datetime] = utc_now) -> None:
        self._clock = clock
        self._events: list[TraceEvent] = []

    @property
    def events(self) -> Sequence[TraceEvent]:
        """Return an immutable view of recorded events."""
        return tuple(self._events)

    def record(self, kind: EventKind, turn_id: str, payload: JsonObject) -> TraceEvent:
        """Append and return one hash-linked event."""
        sequence = len(self._events) + 1
        previous_hash = self._events[-1].event_hash if self._events else "GENESIS"
        occurred_at = self._clock()
        # Copy so later mutation of caller-owned objects cannot desync the hash.
        payload = deepcopy(payload)
        event_hash = _compute_hash(sequence, kind, turn_id, occurred_at, payload, previous_hash)
        event = TraceEvent(
            sequence=sequence,
            kind=kind,
            turn_id=turn_id,
            occurred_at=occurred_at,
            payload=payload,
            previous_hash=previous_hash,
            event_hash=event_hash,
        )
        self._events.append(event)
        return event
