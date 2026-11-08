"""Language-model claim extractor.

The extractor sees only the reply text and pre-run reference data (payee and
account identifiers with display names). It never sees the trace, so it cannot
make claims agree with what happened.
"""

from __future__ import annotations

import json
import re

from safeagenteval.agents.chat import ChatClient, ChatEntry, ChatResponse
from safeagenteval.claims.verifier import ActionClaim, ClaimStatus
from safeagenteval.core.models import FrozenModel, JsonObject

SUPPORTED_ACTIONS = frozenset({"initiate_transfer"})
_ATTRIBUTE_KEYS = frozenset({"payee_id", "amount", "currency", "source_account_id"})
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class ExtractionRecord(FrozenModel):
    """Raw extractor output for one reply, kept for auditing and relabeling."""

    reply_sequence: int
    turn_id: str
    raw_output: str
    parse_error: str | None = None
    dropped_claims: int = 0
    response: ChatResponse


def parse_claims(
    raw: str,
    *,
    reply: str,
    reply_sequence: int,
    turn_id: str,
    claim_prefix: str,
) -> tuple[tuple[ActionClaim, ...], str | None, int]:
    """Parse extractor JSON into claims; return (claims, parse error, dropped count).

    Claims with an unsupported action or status, or a malformed shape, are
    dropped and counted rather than guessed at.
    """
    text = _FENCE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return (), "no JSON object in extractor output", 0
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        return (), f"invalid JSON: {error.msg}", 0
    items = payload.get("claims") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        return (), "missing 'claims' list", 0

    claims: list[ActionClaim] = []
    dropped = 0
    for item in items:
        claim = _to_claim(item, reply, reply_sequence, turn_id, f"{claim_prefix}-{len(claims) + 1}")
        if claim is None:
            dropped += 1
        else:
            claims.append(claim)
    return tuple(claims), None, dropped


def _to_claim(
    item: object, reply: str, reply_sequence: int, turn_id: str, claim_id: str
) -> ActionClaim | None:
    if not isinstance(item, dict):
        return None
    action = item.get("action")
    status = item.get("status")
    if action not in SUPPORTED_ACTIONS or status not in {s.value for s in ClaimStatus}:
        return None
    raw_attributes = item.get("attributes", {})
    if not isinstance(raw_attributes, dict):
        return None
    attributes: JsonObject = {
        key: str(value)
        for key, value in raw_attributes.items()
        if key in _ATTRIBUTE_KEYS and isinstance(value, str | int | float) and str(value)
    }
    source = item.get("source_text")
    return ActionClaim(
        claim_id=claim_id,
        reply_sequence=reply_sequence,
        turn_id=turn_id,
        action=str(action),
        status=ClaimStatus(status),
        source_text=source if isinstance(source, str) and source else reply,
        attributes=attributes,
    )


class LLMClaimExtractor:
    """ClaimExtractor that asks a chat model for typed claims.

    ``reference`` is a short text listing the identifiers the reply may refer
    to by name. ``records`` accumulates raw outputs for auditing.
    """

    def __init__(self, client: ChatClient, prompt: str, reference: str) -> None:
        self._client = client
        self._prompt = prompt
        self._reference = reference
        self.records: list[ExtractionRecord] = []

    async def extract(
        self, reply: str, reply_sequence: int, turn_id: str
    ) -> tuple[ActionClaim, ...]:
        """Extract typed claims from one reply."""
        user = (
            f"Reference data:\n{self._reference}\n\n"
            f"Agent reply (turn {turn_id}):\n<<<\n{reply}\n>>>"
        )
        response = await self._client.complete(
            self._prompt, (ChatEntry(role="user", content=user),), ()
        )
        claims, error, dropped = parse_claims(
            response.text,
            reply=reply,
            reply_sequence=reply_sequence,
            turn_id=turn_id,
            claim_prefix=f"claim-{reply_sequence}",
        )
        self.records.append(
            ExtractionRecord(
                reply_sequence=reply_sequence,
                turn_id=turn_id,
                raw_output=response.text,
                parse_error=error,
                dropped_claims=dropped,
                response=response,
            )
        )
        return claims
