"""Static-site structure and source-text safety checks."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def test_site_uses_project_relative_assets_and_data() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    assert 'href="./assets/styles.css"' in html
    assert 'src="./assets/app.js"' in html
    assert 'href="/assets/' not in html
    script = (SITE / "assets" / "app.js").read_text(encoding="utf-8")
    assert 'fetch("./data/latest.json")' in script
    assert 'fetch("./data/records.min.json")' in script


def test_site_contains_required_controls_and_presets() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for identifier in (
        "search",
        "date-from",
        "source",
        "modality",
        "delivery",
        "disease",
        "stage",
        "evidence",
        "company",
        "institution",
        "watched-person",
        "review-status",
        "trial-status",
        "min-score",
        "reset-filters",
    ):
        assert f'id="{identifier}"' in html
    for preset in (
        "latest",
        "clinical",
        "preclinical",
        "delivery",
        "regulatory",
        "aptamers",
        "nanotechnology",
        "trial-changes",
        "srt-authors",
    ):
        assert f'data-preset="{preset}"' in html


def test_source_text_is_rendered_without_html_injection() -> None:
    script = (SITE / "assets" / "app.js").read_text(encoding="utf-8")
    assert ".innerHTML" not in script
    assert ".outerHTML" not in script
    assert "textContent" in script
    assert "safeUrl" in script


def test_methodology_covers_required_limitations() -> None:
    html = (SITE / "methodology.html").read_text(encoding="utf-8")
    for heading in (
        "Data sources",
        "Update schedule",
        "Query scope and exclusions",
        "Deduplication",
        "Classification",
        "Relevance scoring",
        "Optional LLM enrichment",
        "Known limitations",
    ):
        assert heading in html
    assert "Inclusion does not represent endorsement" in html
