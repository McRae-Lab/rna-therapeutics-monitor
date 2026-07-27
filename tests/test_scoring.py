"""Reproducibility and interpretation tests for relevance scoring."""

from datetime import date

from test_classifier import _record

from rna_monitor.classifier import classify_record
from rna_monitor.config import load_config
from rna_monitor.scoring import score_record

CONFIG = load_config().categories
AS_OF = date(2026, 7, 27)


def test_relevance_score_is_reproducible_and_components_sum() -> None:
    record = classify_record(
        _record(
            "Phase 1 LNP mRNA therapeutic targeting KRAS in solid tumors",
            "The lipid nanoparticle was tested in mice and trial participants.",
        ),
        CONFIG,
    )
    first = score_record(record, AS_OF)
    second = score_record(record, AS_OF)

    assert first.relevance_score == second.relevance_score
    assert first.score_components == second.score_components
    assert first.relevance_score == sum(item.points for item in first.score_components)
    assert 0 <= first.relevance_score <= 100


def test_excluded_incidental_rna_record_is_retained_with_low_score() -> None:
    record = classify_record(
        _record(
            "mRNA expression in odor-exposed residents",
            "RNA sequencing and transcriptomic profiling catalog residents.",
        ),
        CONFIG,
    )
    scored = score_record(record, AS_OF)

    assert scored.excluded
    assert scored.relevance_score <= 15
    assert any(
        component.name == "auditable exclusion adjustment" for component in scored.score_components
    )


def test_press_release_claim_gets_no_evidence_quality_bonus() -> None:
    news = _record(
        "Transformative mRNA therapeutic platform",
        "A company announcement claims a therapeutic effect.",
    ).model_copy(
        update={
            "record_type": "news",
            "evidence_level": "news or announcement",
        }
    )
    record = classify_record(
        news,
        CONFIG,
    )
    scored = score_record(record, AS_OF)

    assert all(component.name != "evidence quality" for component in scored.score_components)
    assert scored.evidence_level == "news or announcement"
