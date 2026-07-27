"""Rule classification and negative-pattern regression tests."""

from datetime import UTC, datetime

from pydantic import HttpUrl

from rna_monitor.classifier import classify_record
from rna_monitor.config import load_config
from rna_monitor.models import Organization, Record, TrialDetails

CONFIG = load_config().categories
NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _record(title: str, abstract: str, *, trial: TrialDetails | None = None) -> Record:
    return Record(
        id="test:classification",
        record_type="clinical_trial" if trial else "publication",
        source_types=["fixture"],
        source_ids={"fixture": "classification"},
        title=title,
        abstract=abstract,
        organizations=[
            Organization(
                name="Example RNA Therapeutics",
                organization_type="sponsor",
            )
        ],
        url=HttpUrl("https://example.org/classification"),
        retrieved_at=NOW,
        evidence_level="trial registration" if trial else "peer-reviewed publication",
        trial=trial,
    )


def test_weighted_rule_classification_keeps_evidence() -> None:
    record = _record(
        "Phase 1 LNP mRNA therapeutic targeting KRAS in solid tumors",
        "The lipid nanoparticle formulation was tested in mice before enrolling patients.",
        trial=TrialDetails(
            study_type="INTERVENTIONAL",
            interventions=["KRAS mRNA therapeutic"],
            phase=["PHASE1"],
            overall_status="RECRUITING",
        ),
    )

    classified = classify_record(record, CONFIG)

    assert classified.modalities == ["mRNA"]
    assert classified.delivery_systems == ["lipid nanoparticle"]
    assert classified.disease_areas == ["oncology"]
    assert classified.therapeutic_targets == ["KRAS"]
    assert classified.development_stages == ["Phase 1"]
    assert set(classified.species) == {"human", "mouse"}
    modality = classified.classification_evidence["modalities"][0]
    assert "title" in modality.fields
    assert "interventions" in modality.fields
    assert modality.confidence == 1.0
    assert classified.companies == ["Example RNA Therapeutics"]


def test_negative_pattern_blocks_incidental_mrna_expression() -> None:
    record = _record(
        "mRNA expression in odor-exposed residents",
        "RNA sequencing and transcriptomic profiling were used to catalog residents.",
    )

    classified = classify_record(record, CONFIG)

    assert classified.modalities == []
    assert classified.excluded
    assert any("negative pattern" in reason for reason in classified.exclusion_reasons)


def test_title_match_has_more_weight_than_abstract_match() -> None:
    title_record = classify_record(
        _record("An mRNA therapeutic platform", "No additional details."),
        CONFIG,
    )
    abstract_record = classify_record(
        _record("A delivery platform", "This is an mRNA therapeutic platform."),
        CONFIG,
    )

    title_confidence = title_record.classification_evidence["modalities"][0].confidence
    abstract_confidence = abstract_record.classification_evidence["modalities"][0].confidence
    assert title_confidence > abstract_confidence


def test_gene_and_base_editing_topics_support_site_filters() -> None:
    classified = classify_record(
        _record(
            "Lipid nanoparticle delivery of a CRISPR adenine base editor",
            "The gene editing treatment used guide RNA and mRNA in mice.",
        ),
        CONFIG,
    )

    assert "CRISPR" in classified.topics
    assert "gene editing" in classified.topics
    assert "base editing" in classified.topics
    assert "CRISPR RNA" in classified.modalities
