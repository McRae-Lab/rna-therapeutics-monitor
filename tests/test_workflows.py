"""Static workflow safety and required-step checks."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _workflow(name: str) -> dict:
    return yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))


def test_tests_workflow_has_no_secrets_and_all_quality_gates() -> None:
    path = ROOT / ".github" / "workflows" / "tests.yml"
    text = path.read_text(encoding="utf-8")
    workflow = _workflow("tests.yml")

    assert workflow["permissions"] == {"contents": "read"}
    assert "secrets." not in text
    assert 'python-version: "3.12"' in text
    for command in (
        "ruff format --check .",
        "ruff check .",
        "mypy src",
        "pytest",
        "python scripts/build_fixture_site.py",
        "python -m rna_monitor validate",
    ):
        assert command in text
