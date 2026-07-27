"""Offline tests for PubMed query construction and XML parsing."""

from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from rna_monitor.config import load_config
from rna_monitor.http import HttpClient
from rna_monitor.models import Author, Record
from rna_monitor.people import match_watched_people
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
    assert 'NOT ("RNA sequencing"[Title/Abstract]' not in query
    assert query != "RNA"


def test_pubmed_query_includes_srt_bibliographic_fallbacks() -> None:
    config = load_config(ROOT / "config")
    query = build_pubmed_query(
        config.queries.source_queries["pubmed"],
        config.queries.groups,
        RetrievalWindow(date(2026, 7, 20), date(2026, 7, 27)),
        config.people.people,
    )

    assert "Cullis PR[Author]" in query
    assert "Hastings ML[Author]" in query
    assert "Yu TW[Author]" in query
    assert '"base editing"[Title/Abstract]' in query


def _identity_record(author: Author) -> Record:
    return Record(
        id="pmid:1",
        record_type="publication",
        source_types=["pubmed"],
        source_ids={"pubmed": "1"},
        title="Identity fixture",
        authors=[author],
        url="https://pubmed.ncbi.nlm.nih.gov/1/",
        retrieved_at=datetime(2026, 7, 27, tzinfo=UTC),
        evidence_level="peer-reviewed publication",
    )


def test_srt_identity_matching_rejects_similar_given_names() -> None:
    people = load_config(ROOT / "config").people.people
    meredith = _identity_record(
        Author(
            name="Meredith L Hastings",
            given_name="Meredith L",
            family_name="Hastings",
            initials="ML",
            affiliations=["Brown University, Providence, Rhode Island"],
        )
    )
    tianlun = _identity_record(
        Author(
            name="Tianlun Yu",
            given_name="Tianlun",
            family_name="Yu",
            initials="T",
            affiliations=["Synchrotron physics institute"],
        )
    )
    michelle = _identity_record(
        Author(
            name="Michelle L Hastings",
            given_name="Michelle L",
            family_name="Hastings",
            affiliations=["University of Michigan"],
        )
    )

    assert match_watched_people(meredith, people) == []
    assert match_watched_people(tianlun, people) == []
    assert match_watched_people(michelle, people) == ["Michelle L. Hastings"]


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


def test_pubmed_splits_windows_above_esearch_result_ceiling() -> None:
    config = load_config(ROOT / "config")
    search_windows: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        term = dict(request.url.params)["term"]
        search_windows.append(term)
        if '"2026/01/01"[PDAT] : "2026/12/31"[PDAT]' in term:
            result = {"count": "10001", "idlist": ["discarded-root-page"]}
        elif '"2026/01/01"[PDAT] : "2026/07/02"[PDAT]' in term:
            result = {"count": "2", "idlist": ["1", "2"]}
        else:
            result = {"count": "2", "idlist": ["2", "3"]}
        return httpx.Response(
            200,
            json={"esearchresult": result},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    http = HttpClient(config.sources.http, config.sources.user_agent, client=client)
    adapter = PubMedAdapter(
        config.sources.pubmed,
        config.queries.source_queries["pubmed"],
        config.queries.groups,
        http,
    )

    ids = adapter.search_ids(RetrievalWindow(date(2026, 1, 1), date(2026, 12, 31)))

    assert ids == ["1", "2", "3"]
    assert len(search_windows) == 3
