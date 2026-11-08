"""Static HTML rendering of a run trace (no JavaScript, no external assets)."""

from __future__ import annotations

import html
from collections.abc import Sequence

from safeagenteval.trace.recorder import TraceEvent


def render_trace_html(events: Sequence[TraceEvent], *, title: str = "SafeAgentEval trace") -> str:
    """Render trace events as a single self-contained HTML document."""
    rows: list[str] = []
    for event in events:
        payload = html.escape(_short(event.payload))
        rows.append(
            "<tr>"
            f"<td>{event.sequence}</td>"
            f"<td>{html.escape(event.kind.value)}</td>"
            f"<td>{html.escape(event.turn_id)}</td>"
            f"<td><code>{payload}</code></td>"
            f"<td><code>{html.escape(event.event_hash[:12])}…</code></td>"
            "</tr>"
        )
    body = "\n".join(rows)
    return (
        "<!DOCTYPE html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        f"<title>{html.escape(title)}</title>"
        "<style>body{font-family:system-ui,sans-serif;margin:2rem}"
        "table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccc;"
        "padding:4px 8px;text-align:left;vertical-align:top}code{font-size:12px;"
        "word-break:break-all}</style></head><body>"
        f"<h1>{html.escape(title)}</h1>"
        "<table><thead><tr><th>#</th><th>Kind</th><th>Turn</th><th>Payload</th>"
        f"<th>Hash</th></tr></thead><tbody>{body}</tbody></table>"
        "</body></html>\n"
    )


def _short(payload: object) -> str:
    text = str(payload)
    return text if len(text) <= 500 else text[:500] + "…"
