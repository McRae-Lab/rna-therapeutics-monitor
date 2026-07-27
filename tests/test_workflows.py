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


def test_update_workflow_is_serialized_minimal_and_no_llm_by_default() -> None:
    text = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
    workflow = _workflow("update.yml")

    assert workflow["permissions"] == {"contents": "write"}
    assert workflow["concurrency"]["cancel-in-progress"] is False
    assert "schedule" in workflow.get("on", workflow.get(True))
    assert "actions/cache@v5" in text
    assert "python -m rna_monitor update" in text
    assert "--no-llm" in text
    assert "python -m rna_monitor build" in text
    assert "git diff --cached --quiet" in text
    assert "data: update RNA therapeutics monitor" in text
    assert "vars.ENABLE_LLM_ENRICHMENT == 'true'" in text
    assert "secrets.OPENAI_API_KEY" in text
    assert "python -m rna_monitor enrich" in text


def test_pages_workflow_uses_official_actions_and_required_permissions() -> None:
    text = (ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
    workflow = _workflow("pages.yml")

    assert workflow["permissions"] == {
        "contents": "read",
        "pages": "write",
        "id-token": "write",
    }
    assert "actions/configure-pages@v6" in text
    assert "actions/upload-pages-artifact@v5" in text
    assert "actions/deploy-pages@v5" in text
    assert "path: site" in text
    assert workflow["jobs"]["deploy"]["environment"]["name"] == "github-pages"
    assert "workflow_run" in workflow.get("on", workflow.get(True))
