"""bioRxiv and medRxiv discovery through the official cursor API."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import UTC, datetime
from itertools import pairwise
from typing import Any, Literal

from pydantic import HttpUrl

from rna_monitor.config import PreprintSettings, QueryGroup, SourceQuery
from rna_monitor.dates import parse_flexible_date
from rna_monitor.http import HttpClient
from rna_monitor.identifiers import canonical_id, normalize_doi
from rna_monitor.models import (
    Author,
    ChangeEvent,
    Organization,
    PreprintDetails,
    ProvenanceEntry,
    Record,
)
from rna_monitor.sources.base import RetrievalWindow, SourceResult


def _split_authors(value: str) -> list[Author]:
    separators = ";" if ";" in value else ","
    return [Author(name=name.strip()) for name in value.split(separators) if name.strip()]


def _published_doi(value: Any) -> str | None:
    if not isinstance(value, str) or value.strip().casefold() in {"", "na", "n/a", "none"}:
        return None
    return normalize_doi(value)


def parse_preprint_item(
    item: dict[str, Any],
    server: Literal["biorxiv", "medrxiv"],
    retrieved_at: datetime | None = None,
) -> Record:
    """Normalize one official bioRxiv API collection item."""

    timestamp = retrieved_at or datetime.now(UTC)
    doi = normalize_doi(str(item.get("doi", "")))
    title = str(item.get("title", "")).strip()
    if not doi or not title:
        raise ValueError(f"{server} item requires DOI and title")
    posting = parse_flexible_date(str(item.get("date", "")))
    version = int(item.get("version", 1))
    authors = _split_authors(str(item.get("authors", "")))
    affiliation = str(item.get("author_corresponding_institution", "")).strip()
    published_doi = _published_doi(item.get("published"))
    source_url = f"https://www.{server}.org/content/{doi}v{version}"
    alternate_urls = [HttpUrl(f"https://doi.org/{doi}")]
    if published_doi:
        alternate_urls.append(HttpUrl(f"https://doi.org/{published_doi}"))
    raw = json.dumps(item, sort_keys=True, separators=(",", ":")).encode()
    return Record(
        id=canonical_id(
            doi=doi,
            source=server,
            source_id=doi,
            title=title,
            first_author=authors[0].name if authors else "",
            year=str(posting.value.year) if posting else "",
        ),
        record_type="preprint",
        source_types=[server],
        source_ids={server: doi},
        title=title,
        abstract=str(item.get("abstract", "")).strip() or None,
        authors=authors,
        organizations=(
            [Organization(name=affiliation, organization_type="affiliation")] if affiliation else []
        ),
        journal_or_source=server,
        doi=doi,
        url=HttpUrl(source_url),
        alternate_urls=alternate_urls,
        first_date=posting.value if posting else None,
        published_date=posting.value if posting else None,
        updated_date=posting.value if posting else None,
        retrieved_at=timestamp,
        institutions=[affiliation] if affiliation else [],
        keywords=[str(item.get("category", "")).strip()]
        if str(item.get("category", "")).strip()
        else [],
        date_precision={"first_date": posting.precision, "published_date": posting.precision}
        if posting
        else {},
        evidence_level="preprint",
        preprint=PreprintDetails(
            server=server,
            version=version,
            category=str(item.get("category", "")).strip() or None,
            published_doi=published_doi,
            publication_status="published" if published_doi else "preprint",
        ),
        provenance=[
            ProvenanceEntry(
                source=server,
                source_id=doi,
                url=HttpUrl(source_url),
                retrieved_at=timestamp,
                fields=[
                    "title",
                    "abstract",
                    "authors",
                    "published_date",
                    "preprint",
                ],
                raw_sha256=hashlib.sha256(raw).hexdigest(),
            )
        ],
        field_sources={
            field: server for field in ("title", "abstract", "authors", "published_date", "doi")
        },
    )


def _term_present(term: str, text: str) -> bool:
    return term.casefold() in text


def apply_query_scope(
    record: Record,
    source_query: SourceQuery,
    groups: dict[str, QueryGroup],
    *,
    agriculture_enabled: bool,
) -> tuple[bool, Record]:
    """Identify in-scope preprints and retain auditable exclusion reasons."""

    searchable = " ".join(
        value for value in (record.title, record.abstract or "", " ".join(record.keywords)) if value
    ).casefold()
    include_terms = [
        term
        for name in source_query.include_groups
        if groups[name].enabled
        for term in groups[name].terms
    ]
    if not any(_term_present(term, searchable) for term in include_terms):
        return False, record
    reasons: list[str] = []
    for name in source_query.exclusion_groups:
        for term in groups[name].terms:
            if _term_present(term, searchable):
                if agriculture_enabled and term.casefold() in {"crop", "plant", "agriculture"}:
                    continue
                reasons.append(f"matched exclusion term: {term}")
    if reasons:
        record = record.model_copy(
            update={"excluded": True, "exclusion_reasons": sorted(set(reasons))}
        )
    return True, record


def coalesce_preprint_revisions(records: list[Record]) -> list[Record]:
    """Keep the newest revision while preserving first posting and revision history."""

    grouped: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        grouped[record.doi or record.id].append(record)
    output: list[Record] = []
    for revisions in grouped.values():
        revisions.sort(key=lambda value: value.preprint.version if value.preprint else 0)
        latest = revisions[-1]
        if len(revisions) > 1:
            first_date = min(
                (value.first_date for value in revisions if value.first_date),
                default=latest.first_date,
            )
            history = list(latest.change_history)
            for previous, current in pairwise(revisions):
                previous_version = previous.preprint.version if previous.preprint else None
                current_version = current.preprint.version if current.preprint else None
                history.append(
                    ChangeEvent(
                        changed_at=current.retrieved_at,
                        source=current.preprint.server if current.preprint else "preprint",
                        fields=["preprint.version"],
                        summary=f"Preprint revision {previous_version} to {current_version}",
                        old_values={"version": previous_version},
                        new_values={"version": current_version},
                    )
                )
            provenance = [entry for revision in revisions for entry in revision.provenance]
            urls = list(
                dict.fromkeys(
                    str(url)
                    for revision in revisions
                    for url in [revision.url, *revision.alternate_urls]
                )
            )
            latest = latest.model_copy(
                update={
                    "first_date": first_date,
                    "alternate_urls": [HttpUrl(url) for url in urls if url != str(latest.url)],
                    "provenance": provenance,
                    "version": len(revisions),
                    "change_history": history,
                }
            )
        output.append(latest)
    return sorted(output, key=lambda value: value.id)


class PreprintAdapter:
    """Cursor-paginated bioRxiv and medRxiv adapter."""

    name = "preprints"

    def __init__(
        self,
        settings: PreprintSettings,
        source_query: SourceQuery,
        groups: dict[str, QueryGroup],
        agriculture_enabled: bool,
        http: HttpClient,
    ) -> None:
        self.settings = settings
        self.source_query = source_query
        self.groups = groups
        self.agriculture_enabled = agriculture_enabled
        self.http = http

    def fetch(
        self,
        window: RetrievalWindow,
        limit: int | None = None,
        server: Literal["biorxiv", "medrxiv"] | None = None,
    ) -> SourceResult:
        """Retrieve interval pages, locally scope them, and coalesce revisions."""

        servers = [server] if server else list(self.settings.servers)
        records: list[Record] = []
        raw_count = 0
        for current_server in servers:
            if current_server not in self.settings.servers:
                raise ValueError(f"unsupported preprint server: {current_server}")
            cursor = 0
            while limit is None or raw_count < limit:
                interval = f"{window.since.isoformat()}/{window.until.isoformat()}"
                url = (
                    f"{str(self.settings.base_url).rstrip('/')}/details/"
                    f"{current_server}/{interval}/{cursor}"
                )
                payload = self.http.get(url).json()
                collection = payload.get("collection", [])
                if not isinstance(collection, list):
                    raise ValueError(f"{current_server} API collection is not a list")
                if limit is not None:
                    collection = collection[: max(0, limit - raw_count)]
                for item in collection:
                    if not isinstance(item, dict):
                        continue
                    record = parse_preprint_item(item, current_server)
                    in_scope, record = apply_query_scope(
                        record,
                        self.source_query,
                        self.groups,
                        agriculture_enabled=self.agriculture_enabled,
                    )
                    if in_scope:
                        records.append(record)
                raw_count += len(collection)
                total = _total_from_messages(payload.get("messages"))
                cursor += len(collection)
                if not collection or (total is not None and cursor >= total):
                    break
        return SourceResult(
            source=self.name,
            records=coalesce_preprint_revisions(records),
            raw_count=raw_count,
        )


def _total_from_messages(messages: Any) -> int | None:
    if not isinstance(messages, list):
        return None
    for message in messages:
        if isinstance(message, dict) and str(message.get("total", "")).isdigit():
            return int(message["total"])
    return None
