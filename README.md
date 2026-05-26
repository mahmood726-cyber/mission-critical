<!-- sentinel:skip-file — hardcoded paths are fixture/registry/audit-narrative data for this repo's research workflow, not portable application configuration. Same pattern as push_all_repos.py and E156 workbook files. -->

# MissionCritical

[![ci](https://github.com/mahmood726-cyber/mission-critical/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/mahmood726-cyber/mission-critical/actions/workflows/ci.yml) [![codeql](https://github.com/mahmood726-cyber/mission-critical/actions/workflows/codeql.yml/badge.svg?branch=master)](https://github.com/mahmood726-cyber/mission-critical/actions/workflows/codeql.yml) [![license: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE) [![python: 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)

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
+ R metafor) and BLOCKS on any divergence above tolerance on the
pooled estimate, standard error, confidence interval, Q, tau², or I².

  diffmeta compare data.csv --measure OR --method REML

Coverage: **{OR, SMD, GEN} × {FE, DL, REML, HKSJ}**. SMD uses the
exact gamma-ratio Hedges' J (scipy.special.gammaln), not the
approximation. I² uses metafor's formula `100·τ²/(τ² + v_typ)` for
random-effects. REML/HKSJ tolerances are relaxed per-field
(see `tolerance_config.py`) because scipy vs metafor's Fisher
scoring differ at the 7th–8th decimal on tau².

This catches errors that pass a single-engine unit test: wrong
pooling formulas (DOR sign, HKSJ floor, Clopper-Pearson alpha,
Hedges' J approximation), numerical instability, transposed
arguments. metafor 4.8+ is the gold standard; Python engines
diverge from it more often than researchers suspect.

### 2. `provenance` — identifier + data extraction chain

Every NCT / PMID / DOI / trial-N / event-count used in a paper MUST
have a provenance record: extraction source (PDF page, PubMed ID,
manual), extractor (human or tool), extraction commit SHA, and the
exact extracted values. Any change to the paper's data without an
updated provenance record is flagged.

  provenance add NCT00095238 --source "PARADIGM-HF-pdf:p12" \
      --value N=8442 --value HR=0.80
  provenance diff NCT00095238 --value N=1807 --value HR=0.80 \
      --classify --float-tol 1e-5

Drift classification emits typed records (`added` /
`null_transition` / `type_changed` / `value_changed`). `--float-tol`
absorbs sub-threshold numeric jitter so rerun noise doesn't show
up as drift. Catches the MAPriors citation-swap class + the "Not
Randomized 1,807" class (negated-counts silent corruption) that
lessons.md documents.

Exports to **W3C PROV-O JSON-LD** for Whole Tale / RO-Crate / ELN
interop (`provenance export prov-o out.jsonld`).

### 3. `baseline` — numerical continuity corpus

Every shipped MA's pooled estimate, CI, and heterogeneity values are
committed to a corpus. Re-running the MA on new data diff-checks
against the stored values; anything outside tolerance is a BLOCK.

  baseline record paper-id --from report.json
  baseline diff paper-id --against new_report.json --tol 1e-6

Catches silent numerical drift across revisions — the "HR moved from
0.80 to 0.81 because I added 3 new studies" that authors routinely
miss in cover letters.

Each baseline row gets a persistent **claim-ID** (`cl_<8hex>`, HEPData
pattern) so a paper revision can reference "my claim `cl_a3f19b2e`
was HR=0.80; it is now HR=0.81" with a stable identifier that
survives CSV edits and row reorders.

Exports to **RO-Crate 1.2** (`baseline export rocrate out/`) and has
a **pytest-regressions** bidirectional adapter so baseline rows can
be used as `num_regression` / `data_regression` fixtures.

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
  (common Windows R installs are auto-detected)

## Install

```bash
pip install -e ".[dev]"
pytest
```

## Integration

- **Sentinel** ships a P0-baseline-drift plugin rule that reads this
  repo's `BaselineStore` and BLOCKs pre-push when a changed baseline
  row doesn't have an accompanying changelog entry.
- **Overmind** has a `NumericalContinuityWitness` wired into the
  tier-3 verify path that reads a `baseline.json` and fails the
  bundle if numerical drift exceeds tolerance.
- **YAML tolerance registry** (`ToleranceConfig`, ESMValTool pattern) —
  per-study / per-measure / per-method epsilons in one file.

## Status

v0.2 — shipped. Coverage: {OR, SMD, GEN} × {FE, DL, REML, HKSJ} in
`diffmeta`; drift classification + NaN-canonicalization in
`provenance`; persistent claim-IDs, PROV-O, RO-Crate, and
pytest-regressions interop in `baseline`. 99 tests passing.

Real-paper deployments:
- `repro-floor-atlas` baseline corpus — 14.3% reproducibility benchmark
  (Pairwise70, 7,545 MAs)
- `ma-workbench` baseline corpus — sglt2i-hfpef-v1.0 +
  precision-sweep-v1.0
- `dossiergap` provenance chain — PARADIGM-HF, VICTORIA,
  GRIPHON (HR values verified against published ground truth)

## License

MIT — see `LICENSE`.

## Companion tools

- **[Sentinel](https://github.com/mahmood726-cyber/Sentinel)** — pre-push
  rule engine (23 rules). Engineering hygiene layer.
- **[Overmind](https://github.com/mahmood726-cyber/overmind)** — nightly
  multi-witness portfolio verifier. Test-suite + smoke + numerical
  witness arbitration layer.

The three together form a tiered integrity stack:
`Sentinel` (pre-push) → `MissionCritical` (numerical correctness) →
`Overmind` (nightly arbitrated verdict).
