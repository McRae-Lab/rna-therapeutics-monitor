"""Offline tests for generic RSS/Atom ingestion."""

from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from rna_monitor.config import FeedSettings, load_config
from rna_monitor.http import HttpClient
from rna_monitor.sources.base import RetrievalWindow
from rna_monitor.sources.rss import RssAdapter, feed_text, parse_feed_entry

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "rss"


def _feed() -> FeedSettings:
    return FeedSettings(
        name="Example News",
        url="https://example.org/feed.xml",
        source_type="news",
        attribution="Example Company",
    )


def test_feed_text_strips_active_markup_and_bounds_content() -> None:
    text = feed_text("<p>Hello <b>world</b></p><script>secret()</script>", maximum=20)
    assert text == "Hello world"


def test_parse_feed_entry_uses_only_supplied_metadata() -> None:
    entry = {
        "id": "release-1",
        "title": "An mRNA therapeutic update",
        "link": "https://example.org/release-1",
        "summary": "<p>Short feed description.</p>",
        "published": "2026-07-27",
        "author": "Example Newsroom",
    }
    record = parse_feed_entry(entry, _feed(), datetime(2026, 7, 27, tzinfo=UTC))

    assert record.description == "Short feed description."
    assert record.evidence_level == "news or announcement"
    assert record.provenance[0].note and "article body not retrieved" in record.provenance[0].note


def test_rss_adapter_filters_noise_and_handles_malformed_feed() -> None:
    config = load_config(ROOT / "config")
    feeds = [
        _feed(),
        FeedSettings(
            name="Malformed",
            url="https://example.org/malformed.xml",
            source_type="news",
        ),
    ]
    settings = config.sources.rss.model_copy(update={"feeds": feeds})

    def handler(request: httpx.Request) -> httpx.Response:
        name = "malformed.xml" if request.url.path.endswith("malformed.xml") else "feed.xml"
        return httpx.Response(
            200,
            content=(FIXTURES / name).read_bytes(),
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = RssAdapter(
        settings,
        config.queries.source_queries["rss"],
        config.queries.groups,
        config.queries.agriculture_enabled,
        HttpClient(config.sources.http, config.sources.user_agent, client=client),
    )
    result = adapter.fetch(RetrievalWindow(date(2026, 7, 20), date(2026, 7, 27)))

    assert result.raw_count == 2
    assert len(result.records) == 1
    assert "alert" not in (result.records[0].description or "")
    assert any("malformed" in warning for warning in result.warnings)
