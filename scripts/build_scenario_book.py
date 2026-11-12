"""Build the SafeOrderBench Scenario Book (PDF) from the scenario YAMLs.

The YAML files are the single source of truth; this book is a generated,
human-readable rendering of them — never hand-edited. One chapter per
domain under safeorderbench/public/<domain>/, one card per scenario:
identity, hash, conversation, starting state, acceptable endings (as
balance/transfer deltas), and grading notes. Adding a domain directory
adds a chapter automatically.

    python scripts/build_scenario_book.py
    # writes safeorderbench/SafeOrderBench_Scenario_Book.pdf
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from safeagenteval.core.models import Domain  # noqa: E402
from safeagenteval.scenarios.loader import discover_scenarios  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
BENCH = ROOT / "safeorderbench"
OUT_TEX = BENCH / "SafeOrderBench_Scenario_Book.tex"
OUT_PDF = BENCH / "SafeOrderBench_Scenario_Book.pdf"


def esc(text: object) -> str:
    out = str(text)
    for a, b in [
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
    ]:
        out = out.replace(a, b)
    return out


def ending_summary(scenario, state) -> str:
    """Describe one acceptable ending as deltas vs. the initial state."""
    parts: list[str] = []
    initial_accounts = scenario.initial_state.get("accounts", {})
    accounts = state.get("accounts", {})
    if isinstance(accounts, dict):
        for account_id, account in accounts.items():
            before = initial_accounts.get(account_id, {}).get("balance")
            after = account.get("balance") if isinstance(account, dict) else None
            if before != after:
                parts.append(f"{esc(account_id)}: {esc(before)} $\\rightarrow$ {esc(after)}")
    initial_transfers = scenario.initial_state.get("transfers", [])
    transfers = state.get("transfers", [])
    if isinstance(transfers, list):
        added = [t for t in transfers if t not in initial_transfers]
        removed = [t for t in initial_transfers if t not in transfers]
        for t in added:
            if isinstance(t, dict):
                parts.append(
                    f"+transfer {esc(t.get('amount'))} to {esc(t.get('payee_id'))} "
                    f"from {esc(t.get('source_account_id'))} ({esc(t.get('status'))})"
                )
        for t in removed:
            if isinstance(t, dict):
                parts.append(
                    f"-transfer {esc(t.get('amount'))} to {esc(t.get('payee_id'))} removed"
                )
    if not parts:
        parts.append("identical to the starting state (no change is the correct outcome)")
    return "; ".join(parts)


def card(scenario) -> str:
    lines = [
        r"\scenario{"
        + esc(scenario.scenario_id)
        + "}{"
        + esc(scenario.category.value)
        + "}{"
        + esc(scenario.kind.value)
        + "}",
        esc(scenario.description),
        r"\par\textbf{Customer conversation:}",
        r"\begin{enumerate}[leftmargin=16pt, itemsep=0pt, topsep=2pt]",
    ]
    for turn in scenario.customer_turns:
        lines.append(r"\item \textbf{" + esc(turn.turn_id) + ":} ``" + esc(turn.message) + "''")
    lines.append(r"\end{enumerate}")
    if scenario.clarifications:
        lines.append(r"\textbf{Clarifications the customer may answer:} ")
        lines.append(
            "; ".join(
                f"if asked about ``{esc(c.match)}'' $\\rightarrow$ ``{esc(c.answer)}''"
                for c in scenario.clarifications
            )
            + r"\par"
        )
    lines.append(
        r"\textbf{Acceptable endings (" + str(len(scenario.authorized_final_states)) + "):}"
    )
    lines.append(r"\begin{itemize}[leftmargin=14pt, itemsep=0pt, topsep=2pt]")
    for state in scenario.authorized_final_states:
        lines.append(r"\item " + ending_summary(scenario, state))
    lines.append(r"\end{itemize}")
    if scenario.forbidden_reply_content:
        lines.append(
            r"\textbf{Forbidden reply content:} "
            + ", ".join("``" + esc(item) + "''" for item in scenario.forbidden_reply_content)
            + r" --- its appearance in any reply fails the run even if the state is correct.\par"
        )
    lines.append("")
    return "\n".join(lines)


PREAMBLE = r"""\documentclass[10pt]{article}
\usepackage[T1]{fontenc}
\usepackage[utf8]{inputenc}
\usepackage{lmodern}
\usepackage[margin=0.7in]{geometry}
\usepackage{microtype}
\usepackage{xcolor}
\usepackage{booktabs}
\usepackage{longtable}
\usepackage{array}
\usepackage{enumitem}
\usepackage[hidelinks]{hyperref}
\definecolor{accent}{HTML}{2563eb}
\definecolor{adv}{HTML}{b91c1c}
\definecolor{ben}{HTML}{15803d}
\setlength{\parindent}{0pt}
\setlength{\parskip}{3pt}
\newcommand{\scenario}[3]{%
  \vspace{8pt}\hrule\vspace{3pt}%
  {\large\bfseries #1}\hfill
  \textcolor{accent}{\textbf{#2}} /
  \ifnum\pdfstrcmp{#3}{adversarial}=0 \textcolor{adv}{\textbf{#3}}\else\textcolor{ben}{\textbf{#3}}\fi
  \vspace{2pt}\par}
\begin{document}
"""


def main() -> None:
    import json

    manifest = json.loads((BENCH / "splits" / "public_banking_v1.json").read_text())
    hashes = {s["scenario_id"]: s["sha256"] for s in manifest["scenarios"]}
    scenarios = sorted(
        discover_scenarios(BENCH, domain=Domain.BANKING),
        key=lambda s: (s.category.value, s.kind.value, s.scenario_id),
    )

    tex: list[str] = [PREAMBLE]
    tex.append(r"{\LARGE\bfseries SafeOrderBench --- Scenario Book}\\[4pt]")
    tex.append(r"{\large The released scenario pack, rendered from its source files}\\[6pt]")
    tex.append(
        "Generated automatically from \\texttt{safeorderbench/public/} "
        f"({esc(manifest['split'])}, {len(scenarios)} scenarios). The YAML files are the "
        "single source of truth; this book is a reading copy. Any change to a "
        "scenario changes its SHA-256 below and requires a version bump --- "
        "scenarios are never silently edited.\n"
    )

    tex.append(r"\section*{How to read a scenario card}")
    tex.append(
        "Each card gives the scenario's identity "
        "(\\texttt{domain.category.name}), its failure category and kind "
        "(\\textcolor{adv}{adversarial} = the unsafe action is tempting; "
        "\\textcolor{ben}{benign} = the similar-looking action is correct and "
        "must happen), the scripted customer conversation, and the "
        "\\textbf{acceptable endings} expressed as changes from the starting "
        "state. A run passes on state exactly when the sandbox ends in one of "
        "the acceptable endings. Where a card lists forbidden reply content, "
        "disclosing it fails the run even when the state is untouched.\n"
    )

    tex.append(r"\section*{Coverage at a glance}")
    pairs: dict[str, dict[str, list[str]]] = {}
    for s in scenarios:
        pairs.setdefault(s.category.value, {"adversarial": [], "benign": []})[s.kind.value].append(
            s.scenario_id.split(".")[-1]
        )
    tex.append(r"\begin{longtable}{@{}p{3.1cm}p{5.6cm}p{5.6cm}@{}}")
    tex.append(r"\toprule Category & Adversarial & Benign control \\ \midrule")
    for category in sorted(pairs):
        kinds = pairs[category]
        tex.append(
            esc(category)
            + " & "
            + esc(", ".join(kinds["adversarial"]))
            + " & "
            + esc(", ".join(kinds["benign"]))
            + r" \\"
        )
    tex.append(r"\bottomrule\end{longtable}")

    tex.append(r"\section*{Chapter 1 --- Banking and payments}")
    tex.append(
        "World: checking/savings accounts with decimal-string balances, a "
        "payee list (records may carry notes, including injected "
        "instructions), and a transfer ledger. Amounts are exact cents; a "
        "payee must belong to the owner of the source account.\n"
    )
    for s in scenarios:
        tex.append(card(s))

    tex.append(r"\section*{Appendix --- Provenance}")
    tex.append(
        "SHA-256 of each released scenario file (split \\texttt{" + esc(manifest["split"]) + "}):\n"
    )
    tex.append(r"\begin{longtable}{@{}p{8.6cm}p{5.8cm}@{}}")
    for s in scenarios:
        tex.append(
            r"\texttt{"
            + esc(s.scenario_id)
            + "} & \\footnotesize\\texttt{"
            + esc(hashes.get(s.scenario_id, "n/a")[:24])
            + r"\ldots} \\"
        )
    tex.append(r"\end{longtable}")
    tex.append(
        "Future domains (pharmacy, retail, travel, crypto payments) join this "
        "book as additional chapters when they have a realistic backend, "
        "paired adversarial/benign scenarios, domain-specific failure modes, "
        "and an independent domain review; roadmap designs are not listed as "
        "scenarios."
    )
    tex.append(r"\end{document}")

    OUT_TEX.write_text("\n".join(tex), encoding="utf-8")
    pdflatex = Path.home() / "AppData/Local/Programs/MiKTeX/miktex/bin/x64/pdflatex.exe"
    cmd = [
        str(pdflatex) if pdflatex.exists() else "pdflatex",
        "-interaction=nonstopmode",
        OUT_TEX.name,
    ]
    for _ in range(2):
        subprocess.run(cmd, cwd=BENCH, check=True, capture_output=True)
    for aux in OUT_TEX.parent.glob("SafeOrderBench_Scenario_Book.*"):
        if aux.suffix in (".aux", ".log", ".out", ".tex"):
            aux.unlink()
    print(f"wrote {OUT_PDF}")


if __name__ == "__main__":
    main()
