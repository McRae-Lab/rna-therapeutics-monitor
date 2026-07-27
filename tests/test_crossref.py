"""Tests for conservative Crossref enrichment."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from rna_monitor.config import load_config
from rna_monitor.http import HttpClient
from rna_monitor.sources.base import RetrievalWindow
from rna_monitor.sources.crossref import (
    CrossrefAuthorAdapter,
    CrossrefEnricher,
    enrich_record_from_crossref,
    record_from_crossref,
)
from rna_monitor.sources.pubmed import parse_pubmed_xml

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "tests" / "fixtures" / "crossref" / "work.json"
PUBMED = ROOT / "tests" / "fixtures" / "pubmed" / "efetch.xml"


def _message() -> dict[str, object]:
    payload = json.loads(WORK.read_text(encoding="utf-8"))
    return payload["message"]


def test_crossref_fills_missing_fields_without_overwriting_pubmed() -> None:
    record = parse_pubmed_xml(
        PUBMED.read_text(encoding="utf-8"), datetime(2026, 7, 27, tzinfo=UTC)
    )[0]
    original_title = record.title
    original_journal = record.journal_or_source

    enriched = enrich_record_from_crossref(record, _message(), datetime(2026, 7, 27, tzinfo=UTC))

    assert enriched.title == original_title
    assert enriched.journal_or_source == original_journal
    assert enriched.publisher == "Example Science Press"
    assert enriched.funders[0].name == "Example Research Foundation"
    assert str(enriched.license_url) == "https://creativecommons.org/licenses/by/4.0/"
    assert enriched.relations["is-correction-of"] == ["10.1000/OLDER.001"]
    assert enriched.field_sources["publisher"] == "crossref"
    assert enriched.field_sources["title"] == "pubmed"


def test_crossref_enricher_uses_encoded_doi_and_mailto() -> None:
    config = load_config(ROOT / "config")
    record = parse_pubmed_xml(PUBMED.read_text(encoding="utf-8"))[0]
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200, json=json.loads(WORK.read_text(encoding="utf-8")), request=request
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    enricher = CrossrefEnricher(
        config.sources.crossref,
        HttpClient(config.sources.http, config.sources.user_agent, client=client),
    )
    enriched = enricher.enrich(record)

    assert enriched.publisher == "Example Science Press"
    assert "/works/10.1000%2Frna.2026.001" in str(requests[0].url)
    assert dict(requests[0].url.params)["mailto"]


def test_crossref_watched_author_discovery_is_strict() -> None:
    config = load_config(ROOT / "config")
    person = next(person for person in config.people.people if person.display_name == "Lior Zangi")
    work = {
        "DOI": "10.3390/pharmaceutics18070868",
        "title": ["Optimization of Therapeutic modRNA Delivery to the Lung"],
        "container-title": ["Pharmaceutics"],
        "published-online": {"date-parts": [[2026, 7, 16]]},
        "author": [
            {"given": "Gayatri", "family": "Mainkar"},
            {
                "given": "Lior",
                "family": "Zangi",
                "affiliation": [{"name": "Icahn School of Medicine at Mount Sinai"}],
            },
        ],
        "URL": "https://doi.org/10.3390/pharmaceutics18070868",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"message": {"items": [work], "next-cursor": "*"}},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = CrossrefAuthorAdapter(
        config.sources.crossref,
        [person],
        HttpClient(config.sources.http, config.sources.user_agent, client=client),
    )
    result = adapter.fetch(RetrievalWindow(date(2026, 7, 1), date(2026, 7, 27)))

    assert result.raw_count == 1
    assert len(result.records) == 1
    assert result.records[0].watched_people == ["Lior Zangi"]
    assert result.records[0].doi == "10.3390/pharmaceutics18070868"


def test_crossref_discovery_normalizes_publication() -> None:
    record = record_from_crossref(_message(), datetime(2026, 7, 27, tzinfo=UTC))

    assert record.id == "doi:10.1000/rna.2026.001"
    assert record.published_date == date(2026, 7, 18)
    assert record.source_types == ["crossref"]
