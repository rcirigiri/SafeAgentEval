"""Provider-neutral contracts shared by the black-box evaluation pipeline."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

JsonObject: TypeAlias = dict[str, JsonValue]

_SCENARIO_ID = re.compile(r"^[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*\.[a-z][a-z0-9_]*$")


class FrozenModel(BaseModel):
    """Immutable base model for evidence and configuration records.

    Frozen prevents attribute reassignment. Nested JSON objects remain
    plain dicts, so components that hand state across a trust boundary
    (seed, snapshot, trace recording) deep-copy at that boundary.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


class Domain(StrEnum):
    """SafeOrderBench scenario domains. Banking/payments is the focus."""

    BANKING = "banking"
    BOOKING = "booking"


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


class CustomerTurn(FrozenModel):
    """One scripted customer turn."""

    turn_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


class Clarification(FrozenModel):
    """One scenario-declared fact the customer can answer questions with.

    Used by the black-box driver when a session agent asks a question mid-
    turn: if the agent's reply contains ``match`` (case-insensitive), the
    customer answers ``answer``. Facts are declared by the scenario author,
    so the agent cannot extract information the scenario did not sanction,
    and a clarification never counts as a confirmation.
    """

    match: str = Field(min_length=1)
    answer: str = Field(min_length=1)


class Scenario(FrozenModel):
    """One executable SafeOrderBench scenario (black-box only).

    The harness sends ``customer_turns`` to a session agent, which acts
    inside its own system, and grades the final snapshot against
    ``authorized_final_states``.
    """

    scenario_id: str
    version: int = Field(ge=1)
    domain: Domain
    category: FailureCategory
    kind: ScenarioKind
    description: str = Field(min_length=1)
    initial_state: JsonObject
    customer_turns: tuple[CustomerTurn, ...] = Field(min_length=1)
    clarifications: tuple[Clarification, ...] = ()
    authorized_final_states: tuple[JsonObject, ...] = Field(min_length=1)
    forbidden_reply_content: tuple[str, ...] = ()
    """Literal strings (case-insensitive) that must never appear in a reply.

    This is how reply-channel hazards (e.g. disclosing another customer's
    balance) are graded deterministically: the disclosure happens in text,
    not in final state, so state equality alone cannot see it.
    """

    @model_validator(mode="after")
    def _check(self) -> Scenario:
        if not _SCENARIO_ID.match(self.scenario_id):
            raise ValueError(
                "scenario_id must be '<domain>.<category>.<name>' in lowercase, "
                f"got {self.scenario_id!r}"
            )
        domain_part, category_part, _ = self.scenario_id.split(".")
        if domain_part != self.domain.value:
            raise ValueError(
                f"scenario_id domain {domain_part!r} does not match domain {self.domain.value!r}"
            )
        if category_part != self.category.value:
            raise ValueError(
                f"scenario_id category {category_part!r} does not match "
                f"category {self.category.value!r}"
            )
        turn_ids = [turn.turn_id for turn in self.customer_turns]
        if len(turn_ids) != len(set(turn_ids)):
            raise ValueError("customer_turns turn_id values must be unique")
        matches = [clarification.match.lower() for clarification in self.clarifications]
        if len(matches) != len(set(matches)):
            raise ValueError("clarifications match values must be unique (case-insensitive)")
        forbidden = [item.lower() for item in self.forbidden_reply_content]
        if any(not item.strip() for item in forbidden):
            raise ValueError("forbidden_reply_content values must be non-empty")
        if len(forbidden) != len(set(forbidden)):
            raise ValueError("forbidden_reply_content values must be unique (case-insensitive)")
        return self
