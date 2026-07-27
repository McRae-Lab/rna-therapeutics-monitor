"""Validated configuration loading for queries, sources, and classification rules."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, HttpUrl, field_validator, model_validator

from rna_monitor.models import StrictModel


class QueryGroup(StrictModel):
    """A reusable group of discovery or exclusion phrases."""

    description: str
    precision: Literal["high", "broad", "exclusion"]
    terms: list[str] = Field(min_length=1)
    enabled: bool = True

    @field_validator("terms")
    @classmethod
    def reject_bare_rna(cls, values: list[str]) -> list[str]:
        """Prevent the intentionally prohibited bare RNA discovery query."""

        if any(value.strip().casefold() == "rna" for value in values):
            raise ValueError("the bare token 'RNA' is not an allowed query term")
        return values


class SourceQuery(StrictModel):
    """Source-specific query syntax and references to reusable term groups."""

    queries: list[str] = Field(default_factory=list)
    include_groups: list[str] = Field(default_factory=list)
    exclusion_groups: list[str] = Field(default_factory=list)


class QueriesConfig(StrictModel):
    """Top-level discovery query configuration."""

    schema_version: int = Field(ge=1)
    agriculture_enabled: bool = False
    groups: dict[str, QueryGroup]
    source_queries: dict[str, SourceQuery]

    @model_validator(mode="after")
    def validate_group_references(self) -> QueriesConfig:
        """Require every source query to reference an existing group."""

        known = set(self.groups)
        for source, query in self.source_queries.items():
            missing = (set(query.include_groups) | set(query.exclusion_groups)) - known
            if missing:
                raise ValueError(f"{source} references unknown query groups: {sorted(missing)}")
        return self


class HttpSettings(StrictModel):
    """Shared bounded HTTP behavior."""

    connect_timeout_seconds: float = Field(default=10.0, gt=0)
    read_timeout_seconds: float = Field(default=30.0, gt=0)
    max_attempts: int = Field(default=4, ge=1, le=10)
    backoff_min_seconds: float = Field(default=1.0, ge=0)
    backoff_max_seconds: float = Field(default=20.0, gt=0)
    cache_ttl_hours: int = Field(default=24, ge=0)


class ApiSourceSettings(StrictModel):
    """Configuration shared by public API adapters."""

    enabled: bool = True
    base_url: HttpUrl
    overlap_days: int = Field(default=7, ge=0, le=90)


class PubMedSettings(ApiSourceSettings):
    """NCBI E-utilities settings."""

    tool: str = Field(min_length=3)
    contact_email_env: str
    default_contact_email: str
    requests_per_second: float = Field(default=3.0, gt=0, le=3.0)
    batch_size: int = Field(default=200, ge=1, le=500)


class PreprintSettings(ApiSourceSettings):
    """bioRxiv API settings."""

    servers: list[Literal["biorxiv", "medrxiv"]] = Field(min_length=1)
    page_size: int = Field(default=100, ge=1)


class ClinicalTrialsSettings(ApiSourceSettings):
    """ClinicalTrials.gov API v2 settings."""

    page_size: int = Field(default=100, ge=1, le=1000)


class CrossrefSettings(ApiSourceSettings):
    """Crossref REST API enrichment settings."""

    contact_email_env: str
    default_contact_email: str
    requests_per_second: float = Field(default=5.0, gt=0)


class FeedSettings(StrictModel):
    """One explicitly configured RSS or Atom feed."""

    name: str
    url: HttpUrl
    source_type: str
    enabled: bool = True
    attribution: str | None = None
    terms_url: HttpUrl | None = None


class RssSettings(StrictModel):
    """Generic feed adapter settings."""

    enabled: bool = True
    overlap_days: int = Field(default=7, ge=0, le=90)
    feeds: list[FeedSettings] = Field(default_factory=list)


class SourcesConfig(StrictModel):
    """All source and network settings."""

    schema_version: int = Field(ge=1)
    user_agent: str = Field(min_length=8)
    retention_days: int = Field(default=30, ge=1, le=3650)
    http: HttpSettings
    pubmed: PubMedSettings
    preprints: PreprintSettings
    clinical_trials: ClinicalTrialsSettings
    crossref: CrossrefSettings
    rss: RssSettings


class ClassificationRule(StrictModel):
    """A weighted deterministic classification rule."""

    label: str
    patterns: list[str] = Field(min_length=1)
    negative_patterns: list[str] = Field(default_factory=list)
    weight: float = Field(default=1.0, gt=0)
    minimum_score: float = Field(default=1.0, gt=0)

    @field_validator("patterns", "negative_patterns")
    @classmethod
    def validate_regular_expressions(cls, values: list[str]) -> list[str]:
        """Compile expressions during configuration loading."""

        for value in values:
            try:
                re.compile(value, re.IGNORECASE)
            except re.error as exc:
                raise ValueError(f"invalid regular expression {value!r}: {exc}") from exc
        return values


class CategoriesConfig(StrictModel):
    """Rule groups and field weights used by deterministic classification."""

    schema_version: int = Field(ge=1)
    field_weights: dict[str, float]
    categories: dict[str, list[ClassificationRule]]
    global_negative_patterns: list[str] = Field(default_factory=list)

    @field_validator("global_negative_patterns")
    @classmethod
    def validate_global_patterns(cls, values: list[str]) -> list[str]:
        """Validate global exclusion expressions."""

        for value in values:
            re.compile(value, re.IGNORECASE)
        return values


class WatchedPerson(StrictModel):
    """One Society for RNA Therapeutics person monitored in PubMed."""

    id: str = Field(pattern=r"^srt-\d{4}$")
    display_name: str
    role: Literal["board", "member", "staff"]
    organization: str | None = None
    orcid: str | None = Field(default=None, pattern=r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$")
    aliases: list[str] = Field(min_length=1)
    pubmed_query: str = Field(min_length=3)
    affiliation_terms: list[str] = Field(default_factory=list)
    require_affiliation: bool = False
    active: bool = True
    note: str | None = None


class PeopleConfig(StrictModel):
    """Versioned SRT author-watch configuration."""

    schema_version: int = Field(ge=1)
    roster_checked_at: str
    people: list[WatchedPerson]

    @model_validator(mode="after")
    def validate_unique_people(self) -> PeopleConfig:
        """Reject duplicate person IDs and ORCIDs."""

        ids = [person.id for person in self.people]
        if len(ids) != len(set(ids)):
            raise ValueError("people IDs must be unique")
        orcids = [person.orcid for person in self.people if person.orcid]
        if len(orcids) != len(set(orcids)):
            raise ValueError("non-empty ORCIDs must be unique")
        return self


class AppConfig(StrictModel):
    """Complete validated application configuration."""

    queries: QueriesConfig
    sources: SourcesConfig
    categories: CategoriesConfig
    people: PeopleConfig


def _read_yaml(path: Path) -> dict[str, Any]:
    """Load one YAML mapping with actionable errors."""

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"configuration file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid YAML in {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"configuration root must be a mapping: {path}")
    return raw


def load_config(config_dir: Path | str = "config") -> AppConfig:
    """Load and validate all repository configuration files."""

    root = Path(config_dir)
    return AppConfig(
        queries=QueriesConfig.model_validate(_read_yaml(root / "queries.yml")),
        sources=SourcesConfig.model_validate(_read_yaml(root / "sources.yml")),
        categories=CategoriesConfig.model_validate(_read_yaml(root / "categories.yml")),
        people=PeopleConfig.model_validate(_read_yaml(root / "people.yml")),
    )
