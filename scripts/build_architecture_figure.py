"""Build the SafeAgentEval black-box architecture figure (Paper 1, Figure 1).

Layout reads left-to-right as one run flows:
scenario -> harness -> agent (untrusted) -> sandbox (ground truth) ->
deterministic scoring -> outputs, with claim verification and the
shadow LLM judges underneath. Colors encode trust: blue = trusted
harness/provider, orange = untrusted agent/models, green = scores.

    python scripts/build_architecture_figure.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parents[1] / "paper" / "figures" / "architecture.png"

TRUSTED = "#dbeafe"  # blue-100
TRUSTED_E = "#2563eb"  # blue-600
UNTRUSTED = "#ffedd5"  # orange-100
UNTRUSTED_E = "#ea580c"  # orange-600
SCORE = "#dcfce7"  # green-100
SCORE_E = "#16a34a"  # green-600
NEUTRAL = "#f1f5f9"  # slate-100
NEUTRAL_E = "#64748b"  # slate-500
INK = "#0f172a"


def box(ax, x, y, w, h, title, body, face, edge):
    ax.add_patch(
        FancyBboxPatch(
            (x, y),
            w,
            h,
            boxstyle="round,pad=0.06,rounding_size=0.12",
            linewidth=1.4,
            edgecolor=edge,
            facecolor=face,
        )
    )
    ax.text(
        x + w / 2,
        y + h - 0.34,
        title,
        ha="center",
        va="center",
        fontsize=8.2,
        fontweight="bold",
        color=INK,
    )
    ax.text(
        x + w / 2,
        y + h / 2 - 0.28,
        body,
        ha="center",
        va="center",
        fontsize=6.7,
        color="#334155",
        linespacing=1.45,
    )


def arrow(ax, p1, p2, label="", color=INK, style="-", rad=0.0, ly=0.16):
    ax.add_patch(
        FancyArrowPatch(
            p1,
            p2,
            arrowstyle="-|>",
            mutation_scale=11,
            linewidth=1.3,
            color=color,
            linestyle=style,
            connectionstyle=f"arc3,rad={rad}",
        )
    )
    if label:
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        ax.text(
            mx,
            my + ly,
            label,
            ha="center",
            va="center",
            fontsize=6.4,
            color=color,
            fontweight="bold",
            bbox=dict(boxstyle="circle,pad=0.18", fc="white", ec=color, lw=0.8),
        )


def main() -> None:
    fig, ax = plt.subplots(figsize=(11.6, 6.4), dpi=200)
    ax.set_xlim(0, 23.2)
    ax.set_ylim(0, 12.8)
    ax.axis("off")

    ax.text(
        11.6,
        12.45,
        "SafeAgentEval — black-box evaluation of a self-executing agent",
        ha="center",
        fontsize=11,
        fontweight="bold",
        color=INK,
    )

    # Row 1: the run
    box(
        ax,
        0.3,
        8.0,
        4.3,
        3.1,
        "SafeOrderBench scenario",
        "initial state (accounts, payees)\ncustomer turns + clarifications\n"
        "authorized final states\nforbidden reply content",
        NEUTRAL,
        NEUTRAL_E,
    )
    box(
        ax,
        5.3,
        8.0,
        4.6,
        3.1,
        "Harness (trusted)",
        "scenario loader / validator\nsession runner (scripted customer)\n"
        "seed read-back · per-turn snapshots\nstate invariants · hash-linked trace",
        TRUSTED,
        TRUSTED_E,
    )
    box(
        ax,
        10.6,
        8.0,
        4.9,
        3.1,
        "Agent under test (untrusted)",
        "session adapter: say(text)\nkeeps own conversation state\nexecutes own tools internally",
        UNTRUSTED,
        UNTRUSTED_E,
    )
    box(
        ax,
        16.2,
        8.0,
        6.2,
        3.1,
        "Sandbox / system of record (ground truth)",
        "StateProvider: reset() · seed() · snapshot()\naccounts · payees · transfer ledger\n"
        "conformance-certified (AGT-01..05, SP-01..04)",
        TRUSTED,
        TRUSTED_E,
    )

    # Row 2: scoring
    box(
        ax,
        5.3,
        3.6,
        4.6,
        3.0,
        "Claim extractor (model)",
        "LLM extractor reads replies\ntyped claims: action, status,\nattributes, quoted source text",
        UNTRUSTED,
        UNTRUSTED_E,
    )
    box(
        ax,
        10.6,
        3.6,
        4.9,
        3.0,
        "Deterministic grading",
        "final state vs authorized states\nstate invariants · forbidden content\n"
        "claims vs state when spoken\ntrace integrity (hash chain)",
        SCORE,
        SCORE_E,
    )
    box(
        ax,
        16.2,
        3.6,
        6.2,
        3.0,
        "Outputs",
        "RunResult: passed / failed (one rule)\nsaved records · reports · leaderboard\n"
        "CI gate: --min-pass-rate blocks release",
        SCORE,
        SCORE_E,
    )

    # Row 3: shadow evaluation
    box(
        ax,
        5.3,
        0.35,
        10.2,
        2.5,
        "Post-run measurement (never the verdict)",
        "LLM judges grade saved runs (replies | with state)\n"
        "compared with the deterministic verdict: agreement,\n"
        "detection, false alarms · human labels calibrate\n"
        "extractor and judges (kappa) · red flags to human review",
        NEUTRAL,
        NEUTRAL_E,
    )

    # Arrows: main flow
    arrow(ax, (4.6, 9.9), (5.3, 9.9), "2")
    # 1: harness seeds the sandbox through the StateProvider (tag above agent)
    ax.text(
        13.05,
        11.62,
        "1 reset + seed  ·  6 snapshot  (StateProvider)",
        fontsize=6.6,
        color=TRUSTED_E,
        ha="center",
        fontweight="bold",
        bbox=dict(boxstyle="round,pad=0.3", fc="#eff6ff", ec=TRUSTED_E, lw=0.9),
    )
    arrow(ax, (9.9, 9.55), (10.6, 9.55), "3", color=UNTRUSTED_E)
    arrow(ax, (15.5, 9.9), (16.2, 9.9), "4", color=UNTRUSTED_E)
    arrow(ax, (19.3, 8.0), (13.4, 6.6), "6", color=TRUSTED_E, rad=0.12)
    arrow(ax, (15.5, 5.1), (16.2, 5.1), "8", color=SCORE_E)
    # replies back to harness
    arrow(ax, (10.6, 8.7), (9.9, 8.7), "5", color=UNTRUSTED_E)
    # harness -> extractor (replies from trace) and extractor -> grading (claims)
    arrow(ax, (6.6, 8.0), (6.6, 6.6), "", color=UNTRUSTED_E)
    ax.text(5.55, 7.3, "replies\n(from trace)", fontsize=6.0, color=UNTRUSTED_E, ha="center")
    arrow(ax, (9.9, 5.1), (10.6, 5.1), "7", color=SCORE_E)
    # trace recorded in harness box; grading reads final snapshot via 6
    # post-run judges input
    arrow(ax, (18.5, 3.6), (12.5, 2.85), "", color=NEUTRAL_E, style=(0, (4, 3)))
    ax.text(16.8, 2.55, "saved runs", fontsize=6.2, color=NEUTRAL_E, ha="center")

    # Legend
    ax.text(0.3, 1.9, "Colors = trust:", fontsize=6.8, fontweight="bold", color=INK)
    # single-line legend at bottom-left vertical stack
    labels = [
        ("trusted (harness / provider)", TRUSTED, TRUSTED_E),
        ("untrusted (agent / models)", UNTRUSTED, UNTRUSTED_E),
        ("deterministic score", SCORE, SCORE_E),
        ("inputs / post-run analysis", NEUTRAL, NEUTRAL_E),
    ]
    for i, (t, c, e) in enumerate(labels):
        yy = 1.55 - i * 0.42
        ax.add_patch(
            FancyBboxPatch(
                (0.3, yy - 0.16),
                0.5,
                0.32,
                boxstyle="round,pad=0.02,rounding_size=0.06",
                linewidth=1.0,
                edgecolor=e,
                facecolor=c,
            )
        )
        ax.text(1.0, yy, t, fontsize=6.4, va="center", color=INK)

    ax.text(
        16.2,
        1.55,
        "Flow: 1 seed sandbox · 2 customer turns loaded\n"
        "3 utterance · 4 agent acts in sandbox · 5 reply\n"
        "6 final snapshot · 7 claims verified · 8 verdict",
        fontsize=6.3,
        color="#334155",
        ha="left",
        va="center",
        linespacing=1.5,
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, bbox_inches="tight", facecolor="white")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
