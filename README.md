# MissionCritical

Moon-mission-grade guards for scientific meta-analysis workflows.

Three tools that target the three classes of error that retract papers:
wrong statistics, wrong identifiers, wrong numerical continuity between
paper revisions. Scope is deliberately narrow — this is *not* a
general-purpose MA engine, and it doesn't replace peer review. It does
the three specific checks a solo researcher routinely skips because the
tooling doesn't exist.

Consciously distinct from Sentinel (engineering hygiene) and Overmind
(test/smoke pass-fail). Those verify that code runs; MissionCritical
verifies that the *numbers are right*.

## The three tools

### 1. `diffmeta` — differential-engine statistical verifier

Runs the same meta-analysis in two independent engines (Python numpy
+ R metafor) and BLOCKS on any divergence > 1e-6 on the pooled
estimate, standard error, confidence interval, or Q statistic.

  diffmeta compare data.csv --measure OR --method FE

This catches errors that pass a single-engine unit test: wrong
pooling formulas (DOR sign, HKSJ floor, Clopper-Pearson alpha),
numerical instability, transposed arguments. metafor 4.8+ is the
gold standard; Python engines diverge from it more often than
researchers suspect.

### 2. `provenance` — identifier + data extraction chain

Every NCT / PMID / DOI / trial-N / event-count used in a paper MUST
have a provenance record: extraction source (PDF page, PubMed ID,
manual), extractor (human or tool), extraction commit SHA, and the
exact extracted values. Any change to the paper's data without an
updated provenance record is flagged.

  provenance add NCT00095238 --source "PARADIGM-HF-pdf:p12" --n 8442 --hr 0.80
  provenance verify paper/data.csv  # compare CSV to recorded provenance

Catches the MAPriors citation-swap class + the "Not Randomized 1,807"
class (negated-counts silent corruption) that `lessons.md` documents.

### 3. `baseline` — numerical continuity corpus

Every shipped MA's pooled estimate, CI, and heterogeneity values are
committed to a corpus. Re-running the MA on new data diff-checks
against the stored values; anything outside tolerance is a BLOCK.

  baseline record paper-id --from report.json
  baseline diff paper-id --against new_report.json --tol 1e-6

Catches silent numerical drift across revisions — the "HR moved from
0.80 to 0.81 because I added 3 new studies" that authors routinely
miss in cover letters.

## What this does NOT guard

- **Clinical interpretation** — numbers can be correct and the paper
  still wrong. Human review only.
- **Study quality / risk of bias** — out of scope; use ROBMA or similar.
- **Systematic review scope** — PICO integrity is a different problem.
- **Ethics / PRISMA adherence** — checklists elsewhere.
- **Cherry-picking studies** — this tool can't detect motivated
  inclusion/exclusion.

## Requirements

- Python 3.11+, numpy
- R 4.5+ with metafor package installed (`install.packages("metafor")`)
- Environment variable `RSCRIPT_PATH` if Rscript isn't on PATH
  (defaults to `C:/Program Files/R/R-4.5.2/bin/Rscript.exe` on Windows)

## Install

```bash
pip install -e ".[dev]"
pytest
```

## Integration

None yet. These are standalone CLIs. A Sentinel plugin wrapper and an
Overmind witness integration are a separate, later task — the point
is to have the tools first, then wire them in once they've proven
themselves.

## Status

v0.1 — MVP. Binary-outcome fixed-effect OR only for `diffmeta`. JSON
storage for provenance + baseline. Honest about scope limits.
