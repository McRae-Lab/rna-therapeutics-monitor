"""Conservative Crossref DOI metadata enrichment and reconciliation."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

from pydantic import HttpUrl

from rna_monitor.config import CrossrefSettings, WatchedPerson
from rna_monitor.dates import ParsedDate, parse_date_parts
from rna_monitor.http import HttpClient
from rna_monitor.identifiers import canonical_id, normalize_doi
from rna_monitor.models import Author, Organization, ProvenanceEntry, Record
from rna_monitor.people import match_watched_people
from rna_monitor.sources.base import RetrievalWindow, SourceResult


def _first_text(value: Any) -> str | None:
    if isinstance(value, list) and value and isinstance(value[0], str):
        return value[0].strip() or None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _crossref_date(value: Any) -> ParsedDate | None:
    if not isinstance(value, dict):
        return None
    parts = value.get("date-parts")
    if not isinstance(parts, list) or not parts or not isinstance(parts[0], list):
        return None
    numbers = parts[0]
    year = str(numbers[0]) if numbers else None
    month = str(numbers[1]) if len(numbers) > 1 else None
    day = str(numbers[2]) if len(numbers) > 2 else None
    return parse_date_parts(year, month, day)


def _authors(value: Any) -> list[Author]:
    if not isinstance(value, list):
        return []
    output: list[Author] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        given = _first_text(raw.get("given"))
        family = _first_text(raw.get("family"))
        name = " ".join(part for part in (given, family) if part)
        if not name:
            name = _first_text(raw.get("name")) or ""
        if not name:
            continue
        affiliations = [
            text
            for item in raw.get("affiliation", [])
            if isinstance(item, dict) and (text := _first_text(item.get("name")))
        ]
        orcid = _first_text(raw.get("ORCID"))
        if orcid:
            orcid = orcid.rstrip("/").rsplit("/", 1)[-1]
        output.append(
            Author(
                name=name,
                given_name=given,
                family_name=family,
                orcid=orcid,
                affiliations=affiliations,
            )
        )
    return output


def _funders(value: Any) -> list[Organization]:
    if not isinstance(value, list):
        return []
    output: list[Organization] = []
    for raw in value:
        if isinstance(raw, dict) and (name := _first_text(raw.get("name"))):
            doi = _first_text(raw.get("DOI"))
            output.append(
                Organization(
                    name=name,
                    organization_type="funder",
                    ror_id=f"https://doi.org/{doi}" if doi else None,
                )
            )
    return output


def _relations(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    output: dict[str, list[str]] = {}
    for relationship, raw_items in value.items():
        if not isinstance(raw_items, list):
            continue
        identifiers = [
            identifier
            for item in raw_items
            if isinstance(item, dict) and (identifier := _first_text(item.get("id")))
        ]
        if identifiers:
            output[str(relationship)] = identifiers
    return output


def enrich_record_from_crossref(
    record: Record,
    message: dict[str, Any],
    retrieved_at: datetime | None = None,
) -> Record:
    """Fill missing record fields without overwriting stronger source metadata."""

    if not record.doi:
        return record
    timestamp = retrieved_at or datetime.now(UTC)
    canonical_doi = normalize_doi(_first_text(message.get("DOI"))) or record.doi
    container = _first_text(message.get("container-title"))
    publisher = _first_text(message.get("publisher"))
    crossref_authors = _authors(message.get("author"))
    published = _crossref_date(message.get("published-print")) or _crossref_date(
        message.get("published-online")
    )
    funders = _funders(message.get("funder"))
    license_url = None
    license_entries = message.get("license")
    if isinstance(license_entries, list) and license_entries:
        license_url = _first_text(
            license_entries[0].get("URL") if isinstance(license_entries[0], dict) else None
        )
    relations = _relations(message.get("relation"))
    enriched_fields: list[str] = []
    updates: dict[str, Any] = {}

    candidates: tuple[tuple[str, Any, bool], ...] = (
        ("journal_or_source", container, not record.journal_or_source),
        ("publisher", publisher, not record.publisher),
        ("authors", crossref_authors, not record.authors),
        ("published_date", published.value if published else None, not record.published_date),
        ("funders", funders, not record.funders),
        ("license_url", HttpUrl(license_url) if license_url else None, not record.license_url),
        ("relations", relations, not record.relations),
    )
    for field, value, missing in candidates:
        if missing and value:
            updates[field] = value
            enriched_fields.append(field)
    if published and "published_date" in enriched_fields:
        precision = dict(record.date_precision)
        precision["published_date"] = published.precision
        updates["date_precision"] = precision
    source_types = list(dict.fromkeys([*record.source_types, "crossref"]))
    source_ids = {**record.source_ids, "crossref": canonical_doi}
    field_sources = dict(record.field_sources)
    field_sources.update({field: "crossref" for field in enriched_fields})
    alternate_urls = list(record.alternate_urls)
    resource_url = _first_text(message.get("URL"))
    if resource_url and resource_url not in {str(url) for url in alternate_urls}:
        alternate_urls.append(HttpUrl(resource_url))
    raw = json.dumps(message, sort_keys=True, separators=(",", ":")).encode()
    provenance = [
        *record.provenance,
        ProvenanceEntry(
            source="crossref",
            source_id=canonical_doi,
            url=HttpUrl(f"https://api.crossref.org/works/{quote(canonical_doi, safe='')}"),
            retrieved_at=timestamp,
            fields=enriched_fields,
            raw_sha256=hashlib.sha256(raw).hexdigest(),
            note="Missing-field DOI enrichment; existing source metadata retained.",
        ),
    ]
    return record.model_copy(
        update={
            **updates,
            "source_types": source_types,
            "source_ids": source_ids,
            "field_sources": field_sources,
            "alternate_urls": alternate_urls,
            "provenance": provenance,
        }
    )


class CrossrefEnricher:
    """Retrieve DOI metadata from the Crossref REST API."""

    def __init__(self, settings: CrossrefSettings, http: HttpClient) -> None:
        self.settings = settings
        self.http = http

    def enrich(self, record: Record) -> Record:
        """Enrich one DOI-bearing record, or leave a DOI-less record untouched."""

        if not record.doi:
            return record
        doi_path = quote(record.doi, safe="")
        params = {
            "mailto": os.getenv(
                self.settings.contact_email_env,
                self.settings.default_contact_email,
            )
        }
        self.http.pace("crossref", self.settings.requests_per_second)
        payload = self.http.get(
            f"{str(self.settings.base_url).rstrip('/')}/works/{doi_path}",
            params=params,
        ).json()
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ValueError(f"Crossref response for {record.doi} has no message object")
        return enrich_record_from_crossref(record, message)


def record_from_crossref(
    message: dict[str, Any],
    retrieved_at: datetime | None = None,
) -> Record:
    """Normalize one Crossref work discovered through a watched-author query."""

    timestamp = retrieved_at or datetime.now(UTC)
    doi = normalize_doi(_first_text(message.get("DOI")))
    title = _first_text(message.get("title"))
    if not doi or not title:
        raise ValueError("Crossref discovery item requires DOI and title")
    authors = _authors(message.get("author"))
    published = (
        _crossref_date(message.get("published-print"))
        or _crossref_date(message.get("published-online"))
        or _crossref_date(message.get("published"))
        or _crossref_date(message.get("issued"))
    )
    container = _first_text(message.get("container-title"))
    publisher = _first_text(message.get("publisher"))
    resource_url = _first_text(message.get("URL")) or f"https://doi.org/{doi}"
    organizations = list(
        {
            affiliation: Organization(name=affiliation, organization_type="affiliation")
            for author in authors
            for affiliation in author.affiliations
        }.values()
    )
    raw = json.dumps(message, sort_keys=True, separators=(",", ":")).encode()
    return Record(
        id=canonical_id(
            doi=doi,
            source="crossref",
            source_id=doi,
            title=title,
            first_author=authors[0].name if authors else "",
            year=str(published.value.year) if published else "",
        ),
        record_type="publication",
        source_types=["crossref"],
        source_ids={"crossref": doi},
        title=title,
        authors=authors,
        organizations=organizations,
        journal_or_source=container,
        publisher=publisher,
        doi=doi,
        url=HttpUrl(resource_url),
        alternate_urls=[HttpUrl(f"https://doi.org/{doi}")]
        if resource_url != f"https://doi.org/{doi}"
        else [],
        first_date=published.value if published else None,
        published_date=published.value if published else None,
        retrieved_at=timestamp,
        institutions=[organization.name for organization in organizations],
        evidence_level="peer-reviewed publication",
        date_precision={"first_date": published.precision, "published_date": published.precision}
        if published
        else {},
        provenance=[
            ProvenanceEntry(
                source="crossref",
                source_id=doi,
                url=HttpUrl(f"https://api.crossref.org/works/{quote(doi, safe='')}"),
                retrieved_at=timestamp,
                fields=[
                    "title",
                    "authors",
                    "journal_or_source",
                    "publisher",
                    "published_date",
                    "doi",
                ],
                raw_sha256=hashlib.sha256(raw).hexdigest(),
                note="Discovered by a strict Society watched-author Crossref query.",
            )
        ],
        field_sources={
            field: "crossref"
            for field in (
                "title",
                "authors",
                "journal_or_source",
                "publisher",
                "published_date",
                "doi",
            )
        },
    )


class CrossrefAuthorAdapter:
    """Discover recently published works for strictly matched watched authors."""

    name = "crossref_authors"

    def __init__(
        self,
        settings: CrossrefSettings,
        people: list[WatchedPerson],
        http: HttpClient,
    ) -> None:
        self.settings = settings
        self.people = people
        self.http = http

    def fetch(
        self,
        window: RetrievalWindow,
        limit: int | None = None,
    ) -> SourceResult:
        """Query each watched author and retain only strict identity matches."""

        records: dict[str, Record] = {}
        raw_count = 0
        for person in self.people:
            if not person.active:
                continue
            cursor = "*"
            while True:
                params = {
                    "query.author": person.display_name,
                    "filter": (
                        f"from-pub-date:{window.since.isoformat()},"
                        f"until-pub-date:{window.until.isoformat()}"
                    ),
                    "rows": "100",
                    "cursor": cursor,
                    "mailto": os.getenv(
                        self.settings.contact_email_env,
                        self.settings.default_contact_email,
                    ),
                }
                self.http.pace("crossref", self.settings.requests_per_second)
                payload = self.http.get(
                    f"{str(self.settings.base_url).rstrip('/')}/works",
                    params=params,
                ).json()
                message = payload.get("message", {})
                items = message.get("items", []) if isinstance(message, dict) else []
                if not isinstance(items, list):
                    break
                raw_count += len(items)
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    try:
                        record = record_from_crossref(item)
                    except ValueError:
                        continue
                    matches = match_watched_people(record, [person])
                    if not matches:
                        continue
                    record.watched_people = matches
                    records[record.id] = record
                    if limit is not None and len(records) >= limit:
                        return SourceResult(self.name, list(records.values()), raw_count)
                next_cursor = message.get("next-cursor") if isinstance(message, dict) else None
                if not items or not isinstance(next_cursor, str) or next_cursor == cursor:
                    break
                cursor = next_cursor
        return SourceResult(self.name, list(records.values()), raw_count)
