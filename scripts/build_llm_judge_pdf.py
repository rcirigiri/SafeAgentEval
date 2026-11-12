"""Build docs/llm_judge.pdf from docs/llm_judge.md.

Small, dependency-light Markdown subset renderer (headings, paragraphs,
tables, code blocks, lists, bold/code inline markup) on ReportLab.
The Markdown file remains the canonical source; rerun this script after
editing it.

Usage: python scripts/build_llm_judge_pdf.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    PageTemplate,
    Paragraph,
    Preformatted,
    Spacer,
    Table,
    TableStyle,
)

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "llm_judge.md"
OUTPUT = ROOT / "docs" / "llm_judge.pdf"
NAVY = colors.HexColor("#0B3C6C")
TEAL = colors.HexColor("#0FA3A8")


def inline(text: str) -> str:
    """Escape XML, then apply the inline markup we use (**bold**, `code`)."""
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8.5">\1</font>', text)
    text = re.sub(r"\*([^*]+)\*", r"<i>\1</i>", text)
    return text


def parse(md: str) -> list[tuple[str, object]]:
    blocks: list[tuple[str, object]] = []
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("```"):
            code: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].startswith("```"):
                code.append(lines[i])
                i += 1
            blocks.append(("code", "\n".join(code)))
        elif line.startswith("|"):
            rows: list[list[str]] = []
            while i < len(lines) and lines[i].startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(set(c) <= set(":- ") for c in cells):
                    rows.append(cells)
                i += 1
            blocks.append(("table", rows))
            continue
        elif line.startswith("## "):
            blocks.append(("h2", line[3:].strip()))
        elif line.startswith("# "):
            blocks.append(("h1", line[2:].strip()))
        elif re.match(r"^\d+\. ", line):
            blocks.append(("li", line.strip()))
        elif line.startswith("- "):
            blocks.append(("li", "\u2022  " + line[2:].strip()))
        elif line.strip():
            para = [line.strip()]
            i += 1
            while (
                i < len(lines)
                and lines[i].strip()
                and not lines[i].startswith(("#", "|", "```", "- "))
                and not re.match(r"^\d+\. ", lines[i])
            ):
                para.append(lines[i].strip())
                i += 1
            blocks.append(("p", " ".join(para)))
            continue
        i += 1
    return blocks


def footer(canvas: object, doc: object) -> None:
    canvas.saveState()  # type: ignore[attr-defined]
    canvas.setFont("Helvetica", 7.5)  # type: ignore[attr-defined]
    canvas.setFillColor(colors.HexColor("#546B80"))  # type: ignore[attr-defined]
    canvas.drawString(0.85 * inch, 0.55 * inch, "SafeAgentEval — the LLM judge, in plain terms")  # type: ignore[attr-defined]
    canvas.drawRightString(7.65 * inch, 0.55 * inch, f"Page {doc.page}")  # type: ignore[attr-defined]
    canvas.restoreState()  # type: ignore[attr-defined]


def main() -> None:
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TitleX", parent=styles["Title"], textColor=NAVY, fontSize=21)
    h2 = ParagraphStyle(
        "H2X", parent=styles["Heading2"], textColor=NAVY, fontSize=13, spaceBefore=14
    )
    body = ParagraphStyle(
        "BodyX", parent=styles["BodyText"], fontSize=10, leading=14.5, spaceAfter=7
    )
    li = ParagraphStyle("LiX", parent=body, leftIndent=14, spaceAfter=3)
    mono = ParagraphStyle("MonoX", parent=styles["Code"], fontSize=7.8, leading=10.5, leftIndent=8)

    story: list[object] = []
    for kind, payload in parse(SOURCE.read_text(encoding="utf-8")):
        if kind == "h1":
            story.append(Paragraph(inline(str(payload)), title))
            story.append(Spacer(1, 6))
        elif kind == "h2":
            story.append(Paragraph(inline(str(payload)), h2))
        elif kind == "p":
            story.append(Paragraph(inline(str(payload)), body))
        elif kind == "li":
            story.append(Paragraph(inline(str(payload)), li))
        elif kind == "code":
            text = str(payload)
            for glyph, ascii_equiv in (
                ("\u2500", "-"),
                ("\u25ba", ">"),
                ("\u2502", "|"),
                ("\u25bc", "v"),
                ("\u251c", "+"),
                ("\u2514", "+"),
                ("\u2014", "-"),
            ):
                text = text.replace(glyph, ascii_equiv)
            story.append(Preformatted(text, mono))
            story.append(Spacer(1, 6))
        elif kind == "table":
            raw: list[list[str]] = payload  # type: ignore[assignment]
            rows = [[Paragraph(inline(c), body) for c in row] for row in raw]
            rows[0] = [Paragraph(f'<font color="white">{inline(c)}</font>', body) for c in raw[0]]
            weights = [max(len(row[c]) for row in raw) for c in range(len(raw[0]))]
            total_w = sum(weights) or 1
            widths = [6.8 * inch * w / total_w for w in weights]
            table = Table(rows, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#B9C9D6")),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#EEF4F8")],
                        ),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 5),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                        ("TOPPADDING", (0, 0), (-1, -1), 3),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                    ]
                )
            )
            story.append(table)
            story.append(Spacer(1, 8))

    doc = BaseDocTemplate(
        str(OUTPUT),
        pagesize=LETTER,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title="SafeAgentEval — The LLM Judge, in Plain Terms",
        author="SafeAgentEval",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=footer)])
    doc.build(story)
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()
