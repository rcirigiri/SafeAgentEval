# Paper 1 source

LaTeX source for *SafeAgentEval and SafeOrderBench: State-Aware Safety
Evaluation for Tool-Using AI Agents Across Regulated Consumer Domains*,
version 0.3 (harness, seed benchmark, validation, and a five-model pilot with
judges).

```text
paper/
├── main.tex                          Manuscript (single file, inline bibliography)
├── figures/architecture.png          Figure 1
├── results/harness_validation.json   Data behind the validation tables (Section 6)
├── results/pilot_v1.json             Per-run and per-cell pilot results (Section 7)
└── build/                            Local build output (not committed)
```

## Build

Any TeX Live 2023+ distribution works:

```bash
cd paper
pdflatex main.tex && pdflatex main.tex
```

The bibliography is inline (`thebibliography`), so no BibTeX pass or `.bbl`
file is needed.

## Regenerate the results

From the repository root:

```bash
pytest
python scripts/export_validation_results.py paper/results/harness_validation.json
python scripts/export_pilot_results.py experiments/configs/pilot_v1.yaml paper/results/pilot_v1.json
```

The first two commands regenerate every number in Section 6. The third
regenerates `pilot_v1.json` from the saved pilot runs in
`artifacts/pilot/pilot_v1/` (not committed). Re-running the pilot itself needs
API access and will not reproduce it exactly; see `experiments/pilot/README.md`.
If a number changes, update the matching table in `main.tex`.

## Before the next version

The claim results in Section 7.3 and the judge results in Section 7.5 are
preliminary until `claims.csv`, `replies.csv` and `runs.csv` in
`artifacts/pilot/pilot_v1/labels/` are hand-labeled and
`python -m safeagenteval.pilot analyze experiments/configs/pilot_v1.yaml` is
re-run. Then update Sections 7.3 and 7.5 (Table 11 gains a human-κ column),
the abstract and the conclusion with the confirmed counts, the extractor's
precision and recall, and each judge's agreement with the human labels.

## arXiv submission

Upload a tarball containing only `main.tex` and `figures/architecture.png`. Do
not include a PDF; arXiv compiles from source. Paste the abstract into the
metadata form as plain text (it is about 1,840 characters; the limit is
1,920).
Suggested categories: primary `cs.AI`, cross-list `cs.CL` and `cs.CR`.
