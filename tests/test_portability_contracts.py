from __future__ import annotations

from pathlib import Path


def test_resolve_rscript_path_prefers_explicit_existing(monkeypatch, tmp_path) -> None:
    from mission_critical.diffmeta.engine import resolve_rscript_path

    fake = tmp_path / "Rscript.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.delenv("RSCRIPT_PATH", raising=False)

    assert resolve_rscript_path(str(fake), require_exists=True) == str(fake)


def test_resolve_rscript_path_uses_env_override(monkeypatch, tmp_path) -> None:
    from mission_critical.diffmeta.engine import resolve_rscript_path

    fake = tmp_path / "Rscript.exe"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("RSCRIPT_PATH", str(fake))

    assert resolve_rscript_path() == str(fake)


def test_readme_has_no_hardcoded_local_artifact_paths() -> None:
    readme = (Path(__file__).resolve().parents[1] / "README.md").read_text(encoding="utf-8")

    assert r"C:\Projects\repro-floor-atlas\baseline.json" not in readme
    assert r"C:\Users\user\ma-workbench\baseline.json" not in readme
    assert r"C:\Projects\dossiergap\provenance.json" not in readme
