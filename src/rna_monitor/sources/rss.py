"""Generic RSS/Atom metadata ingestion without article-body scraping."""

from __future__ import annotations

import hashlib
import html
import json
import re
from datetime import UTC, date, datetime
from html.parser import HTMLParser
from time import struct_time
from typing import Any

import feedparser  # type: ignore[import-untyped]
from pydantic import HttpUrl

from rna_monitor.config import FeedSettings, QueryGroup, RssSettings, SourceQuery
from rna_monitor.dates import parse_flexible_date
from rna_monitor.http import HttpClient
from rna_monitor.identifiers import canonical_id, normalize_doi
from rna_monitor.models import Author, Organization, ProvenanceEntry, Record
from rna_monitor.sources.base import RetrievalWindow, SourceResult
from rna_monitor.sources.preprints import apply_query_scope

MAX_DESCRIPTION_LENGTH = 1200
DOI_PATTERN = re.compile(r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+\b", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def feed_text(value: Any, maximum: int = MAX_DESCRIPTION_LENGTH) -> str | None:
    """Convert feed-supplied markup to bounded plain text."""

    if not isinstance(value, str) or not value.strip():
        return None
    without_active_content = re.sub(
        r"<(?:script|style)\b[^>]*>.*?</(?:script|style)>",
        " ",
        value,
        flags=re.IGNORECASE | re.DOTALL,
    )
    parser = _TextExtractor()
    parser.feed(without_active_content)
    text = " ".join(html.unescape(" ".join(parser.parts)).split())
    if len(text) > maximum:
        return text[: maximum - 1].rstrip() + "…"
    return text or None


def _entry_date(entry: dict[str, Any], prefix: str) -> tuple[date | None, str | None]:
    parsed = entry.get(f"{prefix}_parsed")
    if isinstance(parsed, struct_time):
        return date(parsed.tm_year, parsed.tm_mon, parsed.tm_mday), "day"
    flexible = parse_flexible_date(
        entry.get(prefix) if isinstance(entry.get(prefix), str) else None
    )
    return (flexible.value, flexible.precision) if flexible else (None, None)


def _entry_authors(entry: dict[str, Any]) -> list[Author]:
    authors: list[Author] = []
    raw_authors = entry.get("authors")
    if isinstance(raw_authors, list):
        for raw in raw_authors:
            if isinstance(raw, dict) and (name := feed_text(raw.get("name"), maximum=300)):
                authors.append(Author(name=name))
    if not authors and (name := feed_text(entry.get("author"), maximum=300)):
        authors.append(Author(name=name))
    return authors


def _entry_doi(entry: dict[str, Any]) -> str | None:
    for value in (
        entry.get("doi"),
        entry.get("dc_identifier"),
        entry.get("id"),
        entry.get("link"),
    ):
        if isinstance(value, str) and (match := DOI_PATTERN.search(value)):
            return normalize_doi(match.group(0))
    return None


def parse_feed_entry(
    entry: dict[str, Any],
    feed: FeedSettings,
    retrieved_at: datetime | None = None,
) -> Record:
    """Normalize one feed item while retaining only supplied metadata."""

    timestamp = retrieved_at or datetime.now(UTC)
    title = feed_text(entry.get("title"), maximum=500)
    link = entry.get("link")
    if not title or not isinstance(link, str) or not link.startswith(("http://", "https://")):
        raise ValueError(f"{feed.name} entry requires a title and HTTP(S) link")
    native_id = str(entry.get("id") or link)
    description = feed_text(entry.get("summary") or entry.get("description"))
    published, published_precision = _entry_date(entry, "published")
    updated, updated_precision = _entry_date(entry, "updated")
    doi = _entry_doi(entry)
    authors = _entry_authors(entry)
    record_type = "regulatory" if feed.source_type == "regulatory" else "news"
    evidence = "regulatory document" if record_type == "regulatory" else "news or announcement"
    raw = json.dumps(entry, sort_keys=True, default=str, separators=(",", ":")).encode()
    date_precision = {}
    if published_precision:
        date_precision["published_date"] = published_precision
        date_precision["first_date"] = published_precision
    if updated_precision:
        date_precision["updated_date"] = updated_precision
    return Record(
        id=canonical_id(
            doi=doi,
            source="rss",
            source_id=native_id,
            title=title,
            first_author=authors[0].name if authors else "",
            year=str(published.year) if published else "",
        ),
        record_type=record_type,
        source_types=["rss", feed.source_type],
        source_ids={f"rss:{feed.name}": native_id},
        title=title,
        description=description,
        authors=authors,
        organizations=[Organization(name=feed.attribution, organization_type="publisher")]
        if feed.attribution
        else [],
        journal_or_source=feed.name,
        publisher=feed.attribution,
        doi=doi,
        url=HttpUrl(link),
        alternate_urls=[HttpUrl(f"https://doi.org/{doi}")] if doi else [],
        first_date=published or updated,
        published_date=published,
        updated_date=updated,
        retrieved_at=timestamp,
        date_precision=date_precision,
        evidence_level=evidence,
        provenance=[
            ProvenanceEntry(
                source="rss",
                source_id=native_id,
                url=HttpUrl(link),
                retrieved_at=timestamp,
                fields=[
                    "title",
                    "description",
                    "authors",
                    "published_date",
                    "updated_date",
                ],
                raw_sha256=hashlib.sha256(raw).hexdigest(),
                note=f"Feed metadata from {feed.name}; article body not retrieved.",
            )
        ],
        field_sources={
            field: f"rss:{feed.name}"
            for field in ("title", "description", "authors", "published_date", "updated_date")
        },
    )


class RssAdapter:
    """Retrieve configured RSS/Atom feeds independently."""

    name = "rss"

    def __init__(
        self,
        settings: RssSettings,
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

    def fetch(self, window: RetrievalWindow, limit: int | None = None) -> SourceResult:
        """Fetch enabled feeds; a failed or malformed feed does not stop the others."""

        records: list[Record] = []
        warnings: list[str] = []
        raw_count = 0
        for feed in self.settings.feeds:
            if not feed.enabled:
                continue
            try:
                response = self.http.get(str(feed.url))
                parsed = feedparser.parse(response.content)
            except Exception as exc:
                warnings.append(f"{feed.name}: retrieval failed: {type(exc).__name__}")
                continue
            entries = parsed.get("entries", [])
            if parsed.get("bozo"):
                warnings.append(f"{feed.name}: malformed feed parsed with warnings")
            if not isinstance(entries, list):
                warnings.append(f"{feed.name}: entries were not a list")
                continue
            raw_count += len(entries)
            for raw_entry in entries:
                if not isinstance(raw_entry, dict):
                    continue
                try:
                    record = parse_feed_entry(dict(raw_entry), feed)
                except ValueError as exc:
                    warnings.append(str(exc))
                    continue
                in_scope, record = apply_query_scope(
                    record,
                    self.source_query,
                    self.groups,
                    agriculture_enabled=self.agriculture_enabled,
                )
                record_date = record.updated_date or record.published_date or record.first_date
                if in_scope and (
                    record_date is None or window.since <= record_date <= window.until
                ):
                    records.append(record)
                    if limit is not None and len(records) >= limit:
                        return SourceResult(self.name, records, raw_count, warnings)
        return SourceResult(self.name, records, raw_count, warnings)
