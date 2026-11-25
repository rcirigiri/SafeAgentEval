"""Build the guide PDFs in docs/ from their Markdown sources.

Reuses the Markdown-subset renderer in build_llm_judge_pdf.py so all
guides share one visual style. The Markdown files remain the canonical
sources; rerun this script after editing any of them.

Usage: python scripts/build_guide_pdfs.py
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from build_llm_judge_pdf import parse
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
DOCS = ROOT / "docs"
NAVY = colors.HexColor("#0B3C6C")

GUIDES = [
    ("developer_guide.md", "AgenticSafetyEval_Developer_Guide.pdf", "Developer Guide"),
    ("customers.md", "AgenticSafetyEval_Client_Guide.pdf", "Client Guide"),
    ("vendor_review_playbook.md", "AgenticSafetyEval_Vendor_Guide.pdf", "Vendor Guide"),
    ("agent_contract.md", "AgenticSafetyEval_Agent_Contract.pdf", "Agent Contract"),
]


def inline(text_value: str) -> str:
    """Escape XML, then apply **bold** and `code` markup (no italic pass:
    guide text contains stray asterisks, e.g. globs, that break nesting)."""
    text_value = html.escape(text_value)
    text_value = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text_value)
    text_value = re.sub(r"`([^`]+)`", r'<font face="Courier" size="8.5">\1</font>', text_value)
    return text_value


def text(raw: str) -> str:
    """Render Markdown links as their link text, then apply inline markup."""
    return inline(re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", raw))


def build(source: Path, output: Path, label: str) -> None:
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

    def footer(canvas: object, doc: object) -> None:
        canvas.saveState()  # type: ignore[attr-defined]
        canvas.setFont("Helvetica", 7.5)  # type: ignore[attr-defined]
        canvas.setFillColor(colors.HexColor("#546B80"))  # type: ignore[attr-defined]
        canvas.drawString(0.85 * inch, 0.55 * inch, f"AgenticSafetyEval — {label}")  # type: ignore[attr-defined]
        canvas.drawRightString(7.65 * inch, 0.55 * inch, f"Page {doc.page}")  # type: ignore[attr-defined]
        canvas.restoreState()  # type: ignore[attr-defined]

    story: list[object] = []
    for kind, payload in parse(source.read_text(encoding="utf-8")):
        if kind == "h1":
            story.append(Paragraph(text(str(payload)), title))
            story.append(Spacer(1, 6))
        elif kind == "h2":
            story.append(Paragraph(text(str(payload)), h2))
        elif kind == "p":
            story.append(Paragraph(text(str(payload)), body))
        elif kind == "li":
            story.append(Paragraph(text(str(payload)), li))
        elif kind == "code":
            code_text = str(payload)
            for glyph, ascii_equiv in (
                ("\u2500", "-"),
                ("\u25ba", ">"),
                ("\u2502", "|"),
                ("\u25bc", "v"),
                ("\u251c", "+"),
                ("\u2514", "+"),
                ("\u2014", "-"),
            ):
                code_text = code_text.replace(glyph, ascii_equiv)
            story.append(Preformatted(code_text, mono))
            story.append(Spacer(1, 6))
        elif kind == "table":
            raw: list[list[str]] = payload  # type: ignore[assignment]
            rows = [[Paragraph(text(c), body) for c in row] for row in raw]
            rows[0] = [Paragraph(f'<font color="white">{text(c)}</font>', body) for c in raw[0]]
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
        str(output),
        pagesize=LETTER,
        leftMargin=0.85 * inch,
        rightMargin=0.85 * inch,
        topMargin=0.8 * inch,
        bottomMargin=0.8 * inch,
        title=f"AgenticSafetyEval — {label}",
        author="AgenticSafetyEval",
    )
    frame = Frame(doc.leftMargin, doc.bottomMargin, doc.width, doc.height, id="main")
    doc.addPageTemplates([PageTemplate(id="page", frames=[frame], onPage=footer)])
    doc.build(story)
    print(f"wrote {output}")


def main() -> None:
    for source_name, output_name, label in GUIDES:
        build(DOCS / source_name, DOCS / output_name, label)


if __name__ == "__main__":
    main()
