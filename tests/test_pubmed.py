"""Offline tests for PubMed query construction and XML parsing."""

from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from rna_monitor.config import load_config
from rna_monitor.http import HttpClient
from rna_monitor.sources.base import RetrievalWindow
from rna_monitor.sources.pubmed import PubMedAdapter, build_pubmed_query, parse_pubmed_xml

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "pubmed" / "efetch.xml"


def test_parse_pubmed_complete_and_missing_fields() -> None:
    records = parse_pubmed_xml(
        FIXTURE.read_text(encoding="utf-8"),
        datetime(2026, 7, 27, tzinfo=UTC),
    )

    assert len(records) == 2
    complete = records[0]
    assert complete.id == "doi:10.1000/rna.2026.001"
    assert complete.pmid == "40123456"
    assert complete.doi == "10.1000/rna.2026.001"
    assert complete.authors[0].orcid == "0000-0002-0000-0001"
    assert complete.abstract and "BACKGROUND:" in complete.abstract
    assert complete.published_date == date(2026, 7, 1)
    assert complete.date_precision["published_date"] == "month"
    assert complete.electronic_published_date == date(2026, 7, 18)
    assert complete.mesh_terms == ["RNA Therapeutics"]

    missing = records[1]
    assert missing.id == "pmid:40999999"
    assert missing.abstract is None
    assert missing.doi is None
    assert missing.alternate_urls == []


def test_pubmed_query_uses_publication_and_modification_windows() -> None:
    config = load_config(ROOT / "config")
    query = build_pubmed_query(
        config.queries.source_queries["pubmed"],
        config.queries.groups,
        RetrievalWindow(date(2026, 7, 20), date(2026, 7, 27)),
    )

    assert '"2026/07/20"[PDAT] : "2026/07/27"[PDAT]' in query
    assert '"2026/07/20"[MDAT] : "2026/07/27"[MDAT]' in query
    assert '"RNA sequencing"[Title/Abstract]' in query
    assert query != "RNA"


def test_pubmed_adapter_esearch_then_efetch() -> None:
    config = load_config(ROOT / "config")
    fixture = FIXTURE.read_text(encoding="utf-8")
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            return httpx.Response(
                200,
                json={"esearchresult": {"count": "2", "idlist": ["40123456", "40999999"]}},
                request=request,
            )
        return httpx.Response(200, text=fixture, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    http = HttpClient(config.sources.http, config.sources.user_agent, client=client)
    adapter = PubMedAdapter(
        config.sources.pubmed,
        config.queries.source_queries["pubmed"],
        config.queries.groups,
        http,
    )
    result = adapter.fetch(RetrievalWindow(date(2026, 7, 20), date(2026, 7, 27)))

    assert result.raw_count == 2
    assert len(result.records) == 2
    assert [request.url.path.rsplit("/", 1)[-1] for request in requests] == [
        "esearch.fcgi",
        "efetch.fcgi",
    ]
    search_params = dict(requests[0].url.params)
    assert search_params["tool"] == "rna_therapeutics_monitor"
    assert search_params["email"]
