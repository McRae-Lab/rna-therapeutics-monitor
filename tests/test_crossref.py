"""Tests for conservative Crossref enrichment."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from rna_monitor.config import load_config
from rna_monitor.http import HttpClient
from rna_monitor.sources.crossref import CrossrefEnricher, enrich_record_from_crossref
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
