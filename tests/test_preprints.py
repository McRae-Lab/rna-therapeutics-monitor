"""Offline tests for official bioRxiv/medRxiv API handling."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from rna_monitor.config import load_config
from rna_monitor.http import HttpClient
from rna_monitor.sources.base import RetrievalWindow
from rna_monitor.sources.preprints import (
    PreprintAdapter,
    coalesce_preprint_revisions,
    parse_preprint_item,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "preprints"


def _load(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_parse_preprint_published_relationship() -> None:
    item = _load("page0.json")["collection"][1]  # type: ignore[index]
    assert isinstance(item, dict)
    record = parse_preprint_item(item, "biorxiv", datetime(2026, 7, 27, tzinfo=UTC))

    assert record.id == "doi:10.1101/2026.07.20.123456"
    assert record.preprint and record.preprint.version == 2
    assert record.preprint.published_doi == "10.1000/journal.2026.9"
    assert str(record.alternate_urls[-1]) == "https://doi.org/10.1000/journal.2026.9"


def test_preprint_revisions_are_one_logical_record() -> None:
    items = _load("page0.json")["collection"]
    assert isinstance(items, list)
    revisions = [
        parse_preprint_item(item, "biorxiv", datetime(2026, 7, 27, tzinfo=UTC))
        for item in items
        if isinstance(item, dict)
    ]

    merged = coalesce_preprint_revisions(revisions)

    assert len(merged) == 1
    assert merged[0].preprint and merged[0].preprint.version == 2
    assert merged[0].first_date == date(2026, 7, 20)
    assert merged[0].version == 2
    assert merged[0].change_history[0].fields == ["preprint.version"]
    assert len(merged[0].provenance) == 2


def test_cursor_pagination_and_local_query_scope() -> None:
    config = load_config(ROOT / "config")
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        payload = _load("page0.json") if request.url.path.endswith("/0") else _load("page2.json")
        return httpx.Response(200, json=payload, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = PreprintAdapter(
        config.sources.preprints,
        config.queries.source_queries["preprints"],
        config.queries.groups,
        config.queries.agriculture_enabled,
        HttpClient(config.sources.http, config.sources.user_agent, client=client),
    )
    result = adapter.fetch(
        RetrievalWindow(date(2026, 7, 20), date(2026, 7, 27)),
        server="biorxiv",
    )

    assert result.raw_count == 3
    assert len(result.records) == 1
    assert result.records[0].preprint and result.records[0].preprint.version == 2
    assert seen_paths == [
        "/details/biorxiv/2026-07-20/2026-07-27/0",
        "/details/biorxiv/2026-07-20/2026-07-27/2",
    ]
