"""Tests for the canonical Pydantic schema."""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from rna_monitor.models import Author, ProvenanceEntry, Record


def make_record(**overrides: object) -> Record:
    data: dict[str, object] = {
        "id": "doi:10.1000/example",
        "record_type": "publication",
        "source_types": ["pubmed"],
        "source_ids": {"pubmed": "123"},
        "title": "An mRNA therapeutic study",
        "authors": [Author(name="A. Researcher")],
        "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
        "published_date": date(2026, 7, 1),
        "retrieved_at": datetime(2026, 7, 2, tzinfo=UTC),
        "modalities": ["mRNA"],
        "development_stages": ["preclinical animal"],
        "evidence_level": "peer-reviewed publication",
        "provenance": [
            ProvenanceEntry(
                source="pubmed",
                source_id="123",
                url="https://pubmed.ncbi.nlm.nih.gov/123/",
                retrieved_at=datetime(2026, 7, 2, tzinfo=UTC),
            )
        ],
    }
    data.update(overrides)
    return Record.model_validate(data)


def test_doi_is_normalized() -> None:
    record = make_record(doi="HTTPS://DOI.ORG/10.1000/ABC.1")
    assert record.doi == "10.1000/abc.1"


def test_unknown_modality_is_rejected() -> None:
    with pytest.raises(ValidationError):
        make_record(modalities=["uncontrolled-label"])


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        make_record(secret_debug_payload="must not leak")


def test_record_serializes_dates_and_urls() -> None:
    payload = make_record().model_dump(mode="json")
    assert payload["published_date"] == "2026-07-01"
    assert payload["url"] == "https://pubmed.ncbi.nlm.nih.gov/123/"
