"""Provider-neutral contracts shared by the evaluation pipeline."""

from __future__ import annotations

from enum import StrEnum
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

JsonObject: TypeAlias = dict[str, JsonValue]


class FrozenModel(BaseModel):
    """Immutable base model for evidence and configuration records."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Domain(StrEnum):
    """Supported SafeOrderBench domains."""

    BANKING = "banking"
    PHARMACY = "pharmacy"
    RETAIL = "retail"
    TRAVEL = "travel"


class FailureCategory(StrEnum):
    """SafeOrderBench safety categories."""

    STATE_MODIFICATION = "state_modification"
    CONFIRMATION_GATE = "confirmation_gate"
    SAFETY_UNCERTAINTY = "safety_uncertainty"
    PRIVACY = "privacy"
    PROMPT_INJECTION = "prompt_injection"
    DUPLICATE_TRANSACTION = "duplicate_transaction"
    PARTIAL_FAILURE = "partial_failure"


class ScenarioKind(StrEnum):
    """Whether a scenario targets a hazard or an in-policy control."""

    ADVERSARIAL = "adversarial"
    BENIGN = "benign"


class ExecutionMode(StrEnum):
    """How the harness drives the agent under test.

    ``mediated``: the agent returns tool requests and the harness executes
    them on a DomainBackend (gate, faults, and per-call recording apply).
    ``black_box``: the agent receives customer utterances and executes its
    own tools internally; the harness seeds and reads its world through a
    StateProvider and grades the final state. Verdicts from the two modes
    are labeled and must never be conflated.
    """

    MEDIATED = "mediated"
    BLACK_BOX = "black_box"


class Configuration(StrEnum):
    """Paper 1 agent configurations."""

    C0 = "C0"
    C1 = "C1"
    C1_PLUS = "C1+"
    C2 = "C2"


class Role(StrEnum):
    """Conversation message roles."""

    CUSTOMER = "customer"
    AGENT = "agent"
    TOOL = "tool"


class ToolEffect(StrEnum):
    """The state effect of a tool."""

    READ = "read"
    STAGE = "stage"
    COMMIT = "commit"


class ToolStatus(StrEnum):
    """Normalized tool outcomes."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    TIMEOUT = "timeout"


class Message(FrozenModel):
    """One normalized conversation message."""

    role: Role
    content: str
    turn_id: str


class ToolSpec(FrozenModel):
    """Provider-neutral tool definition exposed to an agent."""

    name: str
    description: str
    effect: ToolEffect
    input_schema: JsonObject


class ToolCall(FrozenModel):
    """A tool request emitted by an agent.

    ``intent_id`` is an optional, untrusted hint supplied by the agent. It is
    recorded for analysis but never used for authorization: the harness binds
    each call to a scenario-declared intent by comparing normalized arguments.
    """

    call_id: str
    name: str
    arguments: JsonObject
    intent_id: str | None = None


class ToolResult(FrozenModel):
    """Normalized result returned to an agent."""

    call_id: str
    name: str
    status: ToolStatus
    output: JsonObject = Field(default_factory=dict)
    error: str | None = None
    committed: bool = False


class StateChange(FrozenModel):
    """One deterministic change to backend state."""

    path: str
    before: JsonValue
    after: JsonValue


class BackendExecution(FrozenModel):
    """Backend result and its associated state changes."""

    result: ToolResult
    changes: tuple[StateChange, ...] = ()


class AgentTurn(FrozenModel):
    """Reply text and tool calls produced in one agent step."""

    reply: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


class CustomerTurn(FrozenModel):
    """One scripted customer turn and trusted confirmation metadata."""

    turn_id: str
    message: str
    confirms_intent_id: str | None = None


class Clarification(FrozenModel):
    """One scenario-declared fact the customer can answer questions with.

    Used by the black-box driver when a session agent asks a question mid-
    turn: if the agent's reply contains ``match`` (case-insensitive), the
    customer answers ``answer``. Facts are declared by the scenario author,
    so the agent cannot extract information the scenario did not sanction,
    and a clarification never counts as a trusted confirmation.
    """

    match: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class IntentSpec(FrozenModel):
    """A customer intent declared by the scenario author.

    A tool call is bound to this intent only when its tool name matches and its
    backend-normalized arguments equal ``arguments`` exactly. Customer
    confirmation therefore authorizes specific content (payee, amount, and so
    on), not an agent-chosen label.
    """

    intent_id: str
    tool: str
    arguments: JsonObject


class AuthorizationPolicy(FrozenModel):
    """Scenario-specific authorization rules evaluated against the trace.

    Every commit must match a declared intent; ``confirmation_required_for``
    additionally requires trusted confirmation of that intent. Any call whose
    arguments reference a ``protected_resources`` identifier (for example,
    another customer's account) is unauthorized, reads included.
    """

    allowed_tools: frozenset[str]
    confirmation_required_for: frozenset[str] = frozenset()
    max_successful_commits_per_intent: int = Field(default=1, ge=1)
    protected_resources: frozenset[str] = frozenset()


class FaultKind(StrEnum):
    """Deterministic backend faults the harness can inject."""

    TIMEOUT_BEFORE_COMMIT = "timeout_before_commit"
    TIMEOUT_AFTER_COMMIT = "timeout_after_commit"


class FaultSpec(FrozenModel):
    """Inject ``kind`` on the ``occurrence``-th executed call to ``tool``."""

    tool: str
    occurrence: int = Field(ge=1)
    kind: FaultKind


class FinalStateAssertion(FrozenModel):
    """One expected value at a state path (v2 subset matching).

    Path segments are dot-separated mapping keys, with an optional
    ``key=value`` list selector, e.g. ``transfers[payee_id=payee-alice].status``.
    """

    path: str
    equals: JsonValue


class Scenario(FrozenModel):
    """One executable SafeOrderBench scenario."""

    scenario_id: str
    version: int = Field(ge=1)
    schema_version: int = Field(default=1, ge=1)
    execution_mode: ExecutionMode = ExecutionMode.MEDIATED
    final_state_assertions: tuple[FinalStateAssertion, ...] = ()
    settlement_horizon_ticks: int = Field(default=96, ge=0)
    domain: Domain
    category: FailureCategory
    kind: ScenarioKind
    description: str
    initial_state: JsonObject
    intents: tuple[IntentSpec, ...] = ()
    customer_turns: tuple[CustomerTurn, ...]
    clarifications: tuple[Clarification, ...] = ()
    authorization: AuthorizationPolicy
    authorized_final_states: tuple[JsonObject, ...]
    fault_schedule: tuple[FaultSpec, ...] = ()

    @model_validator(mode="after")
    def _check_intent_references(self) -> Scenario:
        intent_ids = [intent.intent_id for intent in self.intents]
        if len(intent_ids) != len(set(intent_ids)):
            raise ValueError("intent_id values must be unique")
        known = set(intent_ids)
        for turn in self.customer_turns:
            if turn.confirms_intent_id is not None and turn.confirms_intent_id not in known:
                raise ValueError(
                    f"turn {turn.turn_id} confirms undeclared intent {turn.confirms_intent_id}"
                )
        for tool in self.authorization.confirmation_required_for:
            if not any(intent.tool == tool for intent in self.intents):
                raise ValueError(f"{tool} requires confirmation but no intent declares it")
        fault_keys = [(fault.tool, fault.occurrence) for fault in self.fault_schedule]
        if len(fault_keys) != len(set(fault_keys)):
            raise ValueError("fault_schedule has more than one fault for the same call")
        return self
