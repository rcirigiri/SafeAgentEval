"""Bind agent tool calls to scenario-declared intents by content."""

from __future__ import annotations

import json
from collections.abc import Sequence

from safeagenteval.backends.base import DomainBackend
from safeagenteval.core.models import IntentSpec, JsonObject, ToolCall


class IntentResolver:
    """Resolve a call to the declared intent whose normalized content it matches.

    Agent-supplied ``ToolCall.intent_id`` values are ignored. Both the declared
    intent arguments and each call's arguments are passed through the backend's
    normalizer, so ``"100"`` and ``"100.00"`` resolve identically while a
    different payee or amount never resolves to a confirmed intent.
    """

    def __init__(self, intents: Sequence[IntentSpec], backend: DomainBackend) -> None:
        self._backend = backend
        self._by_key: dict[tuple[str, str], str] = {}
        for intent in intents:
            probe = ToolCall(
                call_id=f"intent:{intent.intent_id}",
                name=intent.tool,
                arguments=intent.arguments,
            )
            key = (intent.tool, canonical_json(backend.normalize_arguments(probe)))
            if key in self._by_key:
                raise ValueError(
                    f"intents {self._by_key[key]} and {intent.intent_id} have identical content"
                )
            self._by_key[key] = intent.intent_id

    def normalize(self, call: ToolCall) -> JsonObject:
        """Return the backend-normalized arguments for ``call``."""
        return self._backend.normalize_arguments(call)

    def resolve(self, call: ToolCall, normalized: JsonObject | None = None) -> str | None:
        """Return the matching declared intent id, or ``None``."""
        arguments = self.normalize(call) if normalized is None else normalized
        return self._by_key.get((call.name, canonical_json(arguments)))


def canonical_json(value: object) -> str:
    """Serialize a JSON value deterministically for keying and hashing."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"))
