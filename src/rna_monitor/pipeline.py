"""Incremental source orchestration with failure isolation and idempotent storage."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Protocol

from rna_monitor.classifier import classify_records
from rna_monitor.config import AppConfig, load_config
from rna_monitor.dedup import MergeDecision, deduplicate
from rna_monitor.http import HttpClient
from rna_monitor.models import Record
from rna_monitor.people import match_watched_people
from rna_monitor.scoring import score_records
from rna_monitor.sources.base import RetrievalWindow, SourceResult
from rna_monitor.sources.clinical_trials import ClinicalTrialsAdapter
from rna_monitor.sources.crossref import CrossrefEnricher
from rna_monitor.sources.preprints import PreprintAdapter
from rna_monitor.sources.pubmed import PubMedAdapter
from rna_monitor.sources.rss import RssAdapter
from rna_monitor.storage import (
    PipelineState,
    SourceState,
    content_fingerprint,
    load_records,
    load_state,
    save_records,
    save_state,
)

LOGGER = logging.getLogger(__name__)


class Adapter(Protocol):
    """Minimum interface used by incremental orchestration."""

    name: str

    def fetch(self, window: RetrievalWindow, limit: int | None = None) -> SourceResult:
        """Return normalized source records."""


class Enricher(Protocol):
    """Optional metadata enrichment interface."""

    def enrich(self, record: Record) -> Record:
        """Return a conservatively enriched record."""


@dataclass
class UpdateOptions:
    """User-controlled retrieval boundaries and behavior."""

    since: date | None = None
    until: date | None = None
    days: int = 14
    sources: list[str] | None = None
    limit: int | None = None
    dry_run: bool = False
    no_llm: bool = True


@dataclass
class UpdateReport:
    """Summary suitable for CLI output and workflow diagnostics."""

    total_records: int
    new_or_changed: int
    merge_decisions: list[MergeDecision] = field(default_factory=list)
    successful_sources: list[str] = field(default_factory=list)
    failed_sources: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    dry_run: bool = False


class UpdatePipeline:
    """Run independent adapters against the canonical on-disk dataset."""

    def __init__(
        self,
        config: AppConfig,
        data_dir: Path,
        adapters: dict[str, Adapter],
        *,
        enricher: Enricher | None = None,
        now: datetime | None = None,
    ) -> None:
        self.config = config
        self.data_dir = data_dir
        self.adapters = adapters
        self.enricher = enricher
        self.now = now or datetime.now(UTC)
        if self.now.tzinfo is None:
            raise ValueError("pipeline time must be timezone aware")

    @property
    def records_path(self) -> Path:
        return self.data_dir / "records.jsonl"

    @property
    def state_path(self) -> Path:
        return self.data_dir / "state.json"

    def _overlap_days(self, source: str) -> int:
        return {
            "pubmed": self.config.sources.pubmed.overlap_days,
            "preprints": self.config.sources.preprints.overlap_days,
            "clinicaltrials": self.config.sources.clinical_trials.overlap_days,
            "rss": self.config.sources.rss.overlap_days,
        }.get(source, 7)

    def _window(
        self,
        source: str,
        state: PipelineState,
        options: UpdateOptions,
    ) -> RetrievalWindow:
        until = options.until or self.now.date()
        if options.since:
            since = options.since
        elif source in state.sources:
            since = state.sources[source].last_successful_until - timedelta(
                days=self._overlap_days(source)
            )
        else:
            since = until - timedelta(days=options.days)
        if since > until:
            raise ValueError(f"retrieval start {since} is after end {until}")
        return RetrievalWindow(since, until)

    def run(self, options: UpdateOptions) -> UpdateReport:
        """Update all requested sources, preserving old data on source failure."""

        existing = load_records(self.records_path)
        state = load_state(self.state_path)
        source_names = options.sources or list(self.adapters)
        unknown = set(source_names) - set(self.adapters)
        if unknown:
            raise ValueError(f"unknown sources: {sorted(unknown)}")
        incoming: list[Record] = []
        successful: list[str] = []
        failed: dict[str, str] = {}
        warnings: list[str] = []
        next_state = state.model_copy(deep=True)
        for source in source_names:
            window = self._window(source, state, options)
            LOGGER.info(
                "source_update_started",
                extra={"source": source, "since": str(window.since), "until": str(window.until)},
            )
            try:
                source_result = self.adapters[source].fetch(window, options.limit)
            except Exception as exc:
                failed[source] = f"{type(exc).__name__}: {exc}"
                LOGGER.error(
                    "source_update_failed",
                    extra={"source": source, "error_type": type(exc).__name__},
                )
                continue
            successful.append(source)
            warnings.extend(source_result.warnings)
            incoming.extend(source_result.records)
            next_state.sources[source] = SourceState(
                last_successful_until=window.until,
                last_retrieved_at=self.now,
                raw_count=source_result.raw_count,
            )
            LOGGER.info(
                "source_update_completed",
                extra={
                    "source": source,
                    "raw_count": source_result.raw_count,
                    "normalized_count": len(source_result.records),
                },
            )

        if source_names and not successful:
            raise RuntimeError(f"all requested sources failed: {sorted(failed)}")
        for record in incoming:
            matches = match_watched_people(record, self.config.people.people)
            record.watched_people = list(dict.fromkeys([*record.watched_people, *matches]))

        enriched: list[Record] = []
        enrichment_available = self.enricher is not None
        for record in incoming:
            if enrichment_available and record.doi:
                try:
                    record = self.enricher.enrich(record) if self.enricher else record
                except Exception as exc:
                    warnings.append(
                        f"Crossref enrichment disabled after failure: {type(exc).__name__}"
                    )
                    enrichment_available = False
            enriched.append(record)

        existing_fingerprints = {record.id: content_fingerprint(record) for record in existing}
        changed = [
            record
            for record in enriched
            if existing_fingerprints.get(record.id) != content_fingerprint(record)
        ]
        dedup_result = deduplicate([*existing, *changed])
        classified = classify_records(dedup_result.records, self.config.categories)
        scored = score_records(classified, self.now.date())
        if not options.dry_run:
            save_records(self.records_path, scored)
            save_state(self.state_path, next_state)
        return UpdateReport(
            total_records=len(scored),
            new_or_changed=len(changed),
            merge_decisions=dedup_result.decisions,
            successful_sources=successful,
            failed_sources=failed,
            warnings=warnings,
            dry_run=options.dry_run,
        )


@dataclass
class DefaultPipeline:
    """A pipeline plus its owned HTTP client."""

    pipeline: UpdatePipeline
    http: HttpClient

    def close(self) -> None:
        self.http.close()

    def __enter__(self) -> UpdatePipeline:
        return self.pipeline

    def __exit__(self, *_: object) -> None:
        self.close()


def build_default_pipeline(
    config_dir: Path = Path("config"),
    data_dir: Path = Path("data"),
    *,
    now: datetime | None = None,
) -> DefaultPipeline:
    """Construct production adapters from repository configuration."""

    config = load_config(config_dir)
    http = HttpClient(
        config.sources.http,
        config.sources.user_agent,
        cache_dir=Path(".cache/http"),
    )
    adapters: dict[str, Adapter] = {}
    if config.sources.pubmed.enabled:
        adapters["pubmed"] = PubMedAdapter(
            config.sources.pubmed,
            config.queries.source_queries["pubmed"],
            config.queries.groups,
            http,
            config.people.people,
        )
    if config.sources.preprints.enabled:
        adapters["preprints"] = PreprintAdapter(
            config.sources.preprints,
            config.queries.source_queries["preprints"],
            config.queries.groups,
            config.queries.agriculture_enabled,
            http,
        )
    if config.sources.clinical_trials.enabled:
        adapters["clinicaltrials"] = ClinicalTrialsAdapter(
            config.sources.clinical_trials,
            config.queries.source_queries["clinical_trials"],
            http,
        )
    if config.sources.rss.enabled:
        adapters["rss"] = RssAdapter(
            config.sources.rss,
            config.queries.source_queries["rss"],
            config.queries.groups,
            config.queries.agriculture_enabled,
            http,
        )
    enricher = (
        CrossrefEnricher(config.sources.crossref, http) if config.sources.crossref.enabled else None
    )
    return DefaultPipeline(
        pipeline=UpdatePipeline(
            config,
            data_dir,
            adapters,
            enricher=enricher,
            now=now,
        ),
        http=http,
    )
