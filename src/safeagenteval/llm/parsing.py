"""Shared parsing for evaluation-side model output.

Judge and claim-extractor outputs are untrusted text. Both need the same
operation — pull one JSON object out of a possibly fenced reply — so it
lives here exactly once. Malformed output yields an error string, never
a guess.
"""

from __future__ import annotations

import json
import re

from safeagenteval.core.models import JsonObject

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def extract_json_object(raw: str) -> tuple[JsonObject | None, str | None]:
    """Return (object, None) on success or (None, error) on failure."""
    text = _FENCE.sub("", raw.strip())
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end < start:
        return None, "no JSON object in model output"
    try:
        payload = json.loads(text[start : end + 1])
    except json.JSONDecodeError as error:
        return None, f"invalid JSON: {error.msg}"
    if not isinstance(payload, dict):
        return None, "model output is not a JSON object"
    return payload, None
