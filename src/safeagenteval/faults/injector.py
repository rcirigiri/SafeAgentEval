"""Deterministic, replayable fault injection between the harness and a backend."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence

from safeagenteval.backends.base import DomainBackend
from safeagenteval.core.models import (
    BackendExecution,
    FaultKind,
    FaultSpec,
    FrozenModel,
    ToolCall,
    ToolResult,
    ToolStatus,
)


class InjectedExecution(FrozenModel):
    """What actually happened, and what the agent was shown.

    ``execution`` is ground truth for scoring. ``visible_result`` is the result
    returned to the agent; it differs only when a fault masks the outcome.
    """

    execution: BackendExecution
    visible_result: ToolResult
    fault: FaultKind | None = None


class FaultInjector:
    """Apply a scenario's fault schedule to admitted tool calls."""

    def __init__(self, schedule: Sequence[FaultSpec]) -> None:
        self._faults = {(fault.tool, fault.occurrence): fault.kind for fault in schedule}
        self._executed: Counter[str] = Counter()

    def execute(self, backend: DomainBackend, call: ToolCall) -> InjectedExecution:
        """Execute ``call``, injecting the scheduled fault for this occurrence."""
        self._executed[call.name] += 1
        fault = self._faults.get((call.name, self._executed[call.name]))
        timeout = ToolResult(
            call_id=call.call_id,
            name=call.name,
            status=ToolStatus.TIMEOUT,
            error="backend timed out",
        )
        if fault is FaultKind.TIMEOUT_BEFORE_COMMIT:
            return InjectedExecution(
                execution=BackendExecution(result=timeout),
                visible_result=timeout,
                fault=fault,
            )
        execution = backend.execute(call)
        if fault is FaultKind.TIMEOUT_AFTER_COMMIT:
            return InjectedExecution(execution=execution, visible_result=timeout, fault=fault)
        return InjectedExecution(execution=execution, visible_result=execution.result)
