"""pytest-regressions interop for BaselineStore.

`pytest-regressions` (https://pypi.org/project/pytest-regressions/)
writes num_regression fixtures next to test files. This adapter lets a
MissionCritical baseline be exported to that format so a paper's
existing pytest suite can consume it via `num_regression.check(...)`,
OR imported back from pytest-regressions-managed fixtures into the
baseline corpus.

This is BIDIRECTIONAL INTEROP, not a replacement. The JSON-backed
BaselineStore remains the source of truth; pytest-regressions is a
complementary consumption point for projects that have a pytest suite.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mission_critical.baseline.store import BaselineRecord, BaselineStore


def export_to_pytest_regressions(
    store: BaselineStore,
    out_dir: Path,
) -> list[Path]:
    """Write one num_regression fixture per paper.

    Format matches pytest-regressions' expected YAML layout so a test
    can do:

        def test_paper_stable(num_regression):
            new_values = run_analysis()
            num_regression.check(new_values)

    Returns list of written fixture paths.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for record in store.all():
        fixture_name = f"test_{record.paper_id.replace('-', '_')}_stable.yml"
        fixture_path = out_dir / fixture_name
        # pytest-regressions YAML shape:
        #   field_name: value
        #   other_field: other_value
        # We only emit the numeric fields; commit_sha / recorded_at
        # are metadata, not part of the regression check.
        fields = record.numeric_fields()
        lines = [
            f"# MissionCritical export — paper_id={record.paper_id}",
            f"# recorded_at: {record.recorded_at}",
        ]
        if record.commit_sha:
            lines.append(f"# commit_sha: {record.commit_sha}")
        lines.append("")
        for key, value in sorted(fields.items()):
            lines.append(f"{key}: {value}")
        fixture_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        written.append(fixture_path)
    return written


def import_from_pytest_regressions_yaml(
    store: BaselineStore,
    fixture_dir: Path,
    *,
    overwrite: bool = False,
) -> list[BaselineRecord]:
    """Scan `fixture_dir` for `test_<paper>_stable.yml` files and import
    each as a BaselineRecord.

    Fixture format (one-level mapping of field -> float) is what
    pytest-regressions' num_regression.check writes. Returns the list of
    records added/updated.
    """
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as e:
        raise RuntimeError(
            "PyYAML required to read pytest-regressions fixtures"
        ) from e

    fixture_dir = Path(fixture_dir)
    added: list[BaselineRecord] = []
    for path in sorted(fixture_dir.glob("test_*_stable.yml")):
        stem = path.stem  # e.g. "test_paradigm_hf_stable"
        # Recover paper_id by stripping test_ prefix + _stable suffix
        paper_id = stem
        if paper_id.startswith("test_"):
            paper_id = paper_id[5:]
        if paper_id.endswith("_stable"):
            paper_id = paper_id[:-7]
        paper_id = paper_id.replace("_", "-")

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            continue
        numeric = {k: float(v) for k, v in data.items()
                   if isinstance(v, (int, float)) and not isinstance(v, bool)}
        rec = store.record(
            paper_id, overwrite=overwrite, **numeric,
        )
        added.append(rec)
    store.save()
    return added
