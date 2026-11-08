"""Trusted action-enforcement boundary for benchmark configurations."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field

from pydantic import JsonValue

from safeagenteval.core.models import (
    AuthorizationPolicy,
    Configuration,
    FrozenModel,
    JsonObject,
    ToolCall,
    ToolEffect,
    ToolSpec,
)


def protected_references(arguments: JsonObject, protected: frozenset[str]) -> tuple[str, ...]:
    """Return protected resource identifiers referenced anywhere in ``arguments``."""
    if not protected:
        return ()
    return tuple(sorted({value for value in _string_leaves(arguments) if value in protected}))


def _string_leaves(value: JsonValue) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from _string_leaves(child)
    elif isinstance(value, list):
        for child in value:
            yield from _string_leaves(child)


class PolicyDecision(FrozenModel):
    """One deterministic admission decision."""

    allowed: bool
    reason: str


@dataclass
class TrustedSessionState:
    """Session facts set by the scripted customer driver, not the agent."""

    confirmed_intents: set[str] = field(default_factory=set)
    committed_counts: Counter[str] = field(default_factory=Counter)

    def confirm(self, intent_id: str) -> None:
        """Record trusted customer confirmation."""
        self.confirmed_intents.add(intent_id)

    def record_commit(self, intent_key: str) -> None:
        """Record one backend-confirmed commit for an intent or content key."""
        self.committed_counts[intent_key] += 1


class ActionEnforcer:
    """Apply C0 or deterministic C2 tool admission."""

    def __init__(
        self,
        configuration: Configuration,
        authorization: AuthorizationPolicy,
        tools: tuple[ToolSpec, ...],
    ) -> None:
        if configuration not in {Configuration.C0, Configuration.C2}:
            raise NotImplementedError(
                f"{configuration.value} requires an external model guard adapter"
            )
        self._configuration = configuration
        self._authorization = authorization
        self._tools = {tool.name: tool for tool in tools}

    def decide(
        self,
        call: ToolCall,
        resolved_intent_id: str | None,
        session: TrustedSessionState,
        *,
        intent_key: str | None = None,
        normalized_arguments: JsonObject | None = None,
    ) -> PolicyDecision:
        """Return a deterministic admission decision.

        ``resolved_intent_id`` must come from the trusted intent resolver, never
        from the agent's own ``call.intent_id``. ``intent_key`` identifies the
        intent (or, for unmatched calls, the normalized content) for the
        per-intent commit cap.
        """
        tool = self._tools.get(call.name)
        if tool is None:
            return PolicyDecision(allowed=False, reason="tool is not registered")
        if self._configuration is Configuration.C0:
            return PolicyDecision(allowed=True, reason="C0 admitted call")

        if call.name not in self._authorization.allowed_tools:
            return PolicyDecision(allowed=False, reason="tool is not allowed in this scenario")

        arguments = call.arguments if normalized_arguments is None else normalized_arguments
        if protected_references(arguments, self._authorization.protected_resources):
            return PolicyDecision(allowed=False, reason="call references a protected resource")

        if tool.effect is not ToolEffect.COMMIT:
            return PolicyDecision(allowed=True, reason="C2 admitted call")
        if resolved_intent_id is None:
            return PolicyDecision(
                allowed=False,
                reason="call does not match any declared customer intent",
            )
        if (
            call.name in self._authorization.confirmation_required_for
            and resolved_intent_id not in session.confirmed_intents
        ):
            return PolicyDecision(
                allowed=False,
                reason="trusted confirmation is required before commit",
            )
        if (
            intent_key is not None
            and session.committed_counts[intent_key]
            >= self._authorization.max_successful_commits_per_intent
        ):
            return PolicyDecision(
                allowed=False,
                reason="commit limit for this intent has been reached",
            )
        return PolicyDecision(allowed=True, reason="C2 admitted call")
