"""Typed canonical models for all monitored information sources."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from rna_monitor.vocab import DEVELOPMENT_STAGES, EVIDENCE_LEVELS, MODALITIES, RECORD_TYPES


class StrictModel(BaseModel):
    """Base model that rejects undocumented fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Author(StrictModel):
    """A publication or feed author."""

    name: str = Field(min_length=1)
    given_name: str | None = None
    family_name: str | None = None
    initials: str | None = None
    orcid: str | None = None
    affiliations: list[str] = Field(default_factory=list)
    corresponding: bool = False


class Organization(StrictModel):
    """An institution, company, sponsor, publisher, or collaborator."""

    name: str = Field(min_length=1)
    organization_type: str | None = None
    ror_id: str | None = None
    country: str | None = None


class NumericalResult(StrictModel):
    """A quantitative result with enough context to avoid misleading display."""

    metric: str
    value: float | str
    unit: str | None = None
    group: str | None = None
    context: str | None = None
    confidence_interval: str | None = None
    p_value: str | None = None


class ProvenanceEntry(StrictModel):
    """Source-level provenance for a normalized or enriched record."""

    source: str
    source_id: str
    url: HttpUrl
    retrieved_at: datetime
    fields: list[str] = Field(default_factory=list)
    raw_sha256: str | None = None
    note: str | None = None


class ChangeEvent(StrictModel):
    """A substantive change observed in a record over time."""

    changed_at: datetime
    source: str
    fields: list[str]
    summary: str
    old_values: dict[str, Any] = Field(default_factory=dict)
    new_values: dict[str, Any] = Field(default_factory=dict)


class ClassificationEvidence(StrictModel):
    """Auditable evidence for one assigned classification label."""

    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    matched_phrases: list[str] = Field(default_factory=list)
    fields: list[str] = Field(default_factory=list)
    method: str = "deterministic-rules"


class ScoreComponent(StrictModel):
    """One transparent contribution to the 0-100 relevance score."""

    name: str
    points: float
    maximum: float
    reason: str


class TrialOutcome(StrictModel):
    """A primary or secondary ClinicalTrials.gov outcome."""

    outcome_type: Literal["primary", "secondary", "other"]
    measure: str
    description: str | None = None
    time_frame: str | None = None


class TrialLocation(StrictModel):
    """A summarized clinical trial location."""

    facility: str | None = None
    city: str | None = None
    state: str | None = None
    country: str | None = None


class TrialDetails(StrictModel):
    """Clinical-trial-specific normalized fields."""

    official_title: str | None = None
    brief_title: str | None = None
    sponsor: str | None = None
    collaborators: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    interventions: list[str] = Field(default_factory=list)
    intervention_aliases: list[str] = Field(default_factory=list)
    study_type: str | None = None
    phase: list[str] = Field(default_factory=list)
    overall_status: str | None = None
    enrollment: int | None = None
    start_date: date | None = None
    primary_completion_date: date | None = None
    completion_date: date | None = None
    locations: list[TrialLocation] = Field(default_factory=list)
    countries: list[str] = Field(default_factory=list)
    outcomes: list[TrialOutcome] = Field(default_factory=list)
    results_available: bool = False


class PreprintDetails(StrictModel):
    """Revision and publication information for a preprint."""

    server: Literal["biorxiv", "medrxiv"]
    version: int = Field(ge=1)
    category: str | None = None
    published_doi: str | None = None
    publication_status: str | None = None


class Record(StrictModel):
    """Canonical public record shared by all source adapters."""

    id: str = Field(min_length=1)
    record_type: str
    source_types: list[str] = Field(min_length=1)
    source_ids: dict[str, str] = Field(default_factory=dict)
    title: str = Field(min_length=1)
    abstract: str | None = None
    description: str | None = None
    authors: list[Author] = Field(default_factory=list)
    organizations: list[Organization] = Field(default_factory=list)
    journal_or_source: str | None = None
    publisher: str | None = None
    doi: str | None = None
    pmid: str | None = None
    nct_id: str | None = None
    url: HttpUrl
    alternate_urls: list[HttpUrl] = Field(default_factory=list)
    first_date: date | None = None
    published_date: date | None = None
    electronic_published_date: date | None = None
    updated_date: date | None = None
    retrieved_at: datetime
    modalities: list[str] = Field(default_factory=list)
    delivery_systems: list[str] = Field(default_factory=list)
    disease_areas: list[str] = Field(default_factory=list)
    therapeutic_targets: list[str] = Field(default_factory=list)
    development_stages: list[str] = Field(default_factory=list)
    species: list[str] = Field(default_factory=list)
    methods: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    institutions: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    mesh_terms: list[str] = Field(default_factory=list)
    publication_types: list[str] = Field(default_factory=list)
    date_precision: dict[str, str] = Field(default_factory=dict)
    relevance_score: float = Field(default=0.0, ge=0.0, le=100.0)
    novelty_score: float | None = Field(default=None, ge=0.0, le=100.0)
    evidence_level: str
    classification_method: str = "deterministic-rules"
    classification_evidence: dict[str, list[ClassificationEvidence]] = Field(default_factory=dict)
    score_components: list[ScoreComponent] = Field(default_factory=list)
    summary: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    numerical_results: list[NumericalResult] = Field(default_factory=list)
    provenance: list[ProvenanceEntry] = Field(default_factory=list)
    field_sources: dict[str, str] = Field(default_factory=dict)
    version: int = Field(default=1, ge=1)
    change_history: list[ChangeEvent] = Field(default_factory=list)
    excluded: bool = False
    exclusion_reasons: list[str] = Field(default_factory=list)
    trial: TrialDetails | None = None
    preprint: PreprintDetails | None = None

    @field_validator("record_type")
    @classmethod
    def validate_record_type(cls, value: str) -> str:
        """Require a documented canonical record type."""

        if value not in RECORD_TYPES:
            raise ValueError(f"unsupported record_type: {value}")
        return value

    @field_validator("modalities")
    @classmethod
    def validate_modalities(cls, values: list[str]) -> list[str]:
        """Reject modality labels outside the controlled vocabulary."""

        unsupported = sorted(set(values) - set(MODALITIES))
        if unsupported:
            raise ValueError(f"unsupported modalities: {unsupported}")
        return values

    @field_validator("development_stages")
    @classmethod
    def validate_development_stages(cls, values: list[str]) -> list[str]:
        """Reject development stages outside the controlled vocabulary."""

        unsupported = sorted(set(values) - set(DEVELOPMENT_STAGES))
        if unsupported:
            raise ValueError(f"unsupported development stages: {unsupported}")
        return values

    @field_validator("evidence_level")
    @classmethod
    def validate_evidence_level(cls, value: str) -> str:
        """Require a documented evidence level."""

        if value not in EVIDENCE_LEVELS:
            raise ValueError(f"unsupported evidence_level: {value}")
        return value

    @field_validator("doi")
    @classmethod
    def normalize_doi_field(cls, value: str | None) -> str | None:
        """Normalize DOI prefixes while preserving missing values."""

        if value is None:
            return None
        normalized = value.strip().lower()
        for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix) :]
        return normalized.rstrip(" .") or None
