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
        "technology",
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
        "reset-filters",
    ):
        assert f'id="{identifier}"' in html
    for days in ("7", "30", "all"):
        assert f'data-date-days="{days}"' in html
    assert 'data-date-days="365"' not in html
    for preset in (
        "mrna",
        "sirna",
        "aso",
        "crispr",
        "base-editing",
        "industry",
        "academic",
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
    assert 'data-preset="latest"' not in html


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
        "Result ordering and date windows",
        "Optional LLM enrichment",
        "Known limitations",
    ):
        assert heading in html
    assert "Inclusion does not represent endorsement" in html


def test_interface_has_no_relevance_ranking() -> None:
    html = (SITE / "index.html").read_text(encoding="utf-8")
    for removed in ('id="min-score"', 'value="score-desc"', 'id="score-output"'):
        assert removed not in html
    script = (SITE / "assets" / "app.js").read_text(encoding="utf-8")
    assert "score-badge" not in script
    assert "Scoring breakdown" not in script
    assert "record.relevance_score" not in script


def test_hidden_attribute_overrides_component_display() -> None:
    css = (SITE / "assets" / "styles.css").read_text(encoding="utf-8")
    # Component display rules must not keep hidden loading/menus/buttons visible.
    assert "[hidden] { display: none !important; }" in css
