"""Incremental update, overlap, failure-isolation, and idempotence tests."""

from datetime import UTC, date, datetime
from pathlib import Path

from pydantic import HttpUrl

from rna_monitor.config import load_config
from rna_monitor.models import Record
from rna_monitor.pipeline import UpdateOptions, UpdatePipeline, retain_recent_records
from rna_monitor.sources.base import RetrievalWindow, SourceResult
from rna_monitor.storage import load_records, load_state

NOW = datetime(2026, 7, 27, 12, tzinfo=UTC)


def _record() -> Record:
    return Record(
        id="fixture:1",
        record_type="publication",
        source_types=["fixture"],
        source_ids={"fixture": "1"},
        title="An mRNA therapeutic delivered by lipid nanoparticles",
        abstract="The therapeutic was tested in mice.",
        url=HttpUrl("https://example.org/1"),
        published_date=date(2026, 7, 26),
        retrieved_at=NOW,
        evidence_level="peer-reviewed publication",
    )


class FakeAdapter:
    name = "pubmed"

    def __init__(self, result: SourceResult | Exception) -> None:
        self.result = result
        self.windows: list[RetrievalWindow] = []

    def fetch(self, window: RetrievalWindow, limit: int | None = None) -> SourceResult:
        self.windows.append(window)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_incremental_pipeline_is_idempotent_and_uses_overlap(tmp_path: Path) -> None:
    config = load_config()
    adapter = FakeAdapter(SourceResult("pubmed", [_record()], raw_count=1))
    pipeline = UpdatePipeline(config, tmp_path, {"pubmed": adapter}, now=NOW)

    first = pipeline.run(UpdateOptions(days=14))
    second = pipeline.run(UpdateOptions(days=14))

    assert first.new_or_changed == 1
    assert second.new_or_changed == 0
    assert len(load_records(tmp_path / "records.jsonl")) == 1
    assert adapter.windows[0].since == date(2026, 7, 13)
    assert adapter.windows[1].since == date(2026, 7, 20)
    assert load_state(tmp_path / "state.json").sources["pubmed"].raw_count == 1


def test_one_failed_source_preserves_existing_data_and_state(tmp_path: Path) -> None:
    config = load_config()
    initial = FakeAdapter(SourceResult("pubmed", [_record()], raw_count=1))
    UpdatePipeline(config, tmp_path, {"pubmed": initial}, now=NOW).run(UpdateOptions())
    old_state = (tmp_path / "state.json").read_text(encoding="utf-8")

    failing = FakeAdapter(RuntimeError("temporary outage"))
    successful = FakeAdapter(SourceResult("rss", [], raw_count=0))
    pipeline = UpdatePipeline(
        config,
        tmp_path,
        {"pubmed": failing, "rss": successful},
        now=datetime(2026, 7, 28, tzinfo=UTC),
    )
    report = pipeline.run(UpdateOptions())

    assert "pubmed" in report.failed_sources
    assert report.successful_sources == ["rss"]
    assert len(load_records(tmp_path / "records.jsonl")) == 1
    state = load_state(tmp_path / "state.json")
    assert state.sources["pubmed"].last_retrieved_at == NOW
    assert state.sources["rss"].last_successful_until == date(2026, 7, 28)
    assert (tmp_path / "state.json").read_text(encoding="utf-8") != old_state


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    config = load_config()
    adapter = FakeAdapter(SourceResult("pubmed", [_record()], raw_count=1))
    report = UpdatePipeline(config, tmp_path, {"pubmed": adapter}, now=NOW).run(
        UpdateOptions(dry_run=True)
    )

    assert report.total_records == 1
    assert not (tmp_path / "records.jsonl").exists()
    assert not (tmp_path / "state.json").exists()


def test_rolling_retention_uses_publication_date_for_publications() -> None:
    recent = _record()
    old_publication_with_recent_index_update = _record().model_copy(
        update={
            "id": "fixture:old",
            "published_date": date(2026, 6, 1),
            "updated_date": date(2026, 7, 27),
        }
    )

    retained = retain_recent_records(
        [recent, old_publication_with_recent_index_update],
        as_of=NOW.date(),
        days=30,
    )

    assert [record.id for record in retained] == ["fixture:1"]


def test_pipeline_prunes_records_outside_configured_window(tmp_path: Path) -> None:
    old = _record().model_copy(
        update={
            "id": "fixture:old",
            "source_ids": {"fixture": "old"},
            "published_date": date(2026, 6, 1),
        }
    )
    adapter = FakeAdapter(SourceResult("pubmed", [old, _record()], raw_count=2))
    report = UpdatePipeline(load_config(), tmp_path, {"pubmed": adapter}, now=NOW).run(
        UpdateOptions()
    )

    assert report.total_records == 1
    assert report.retention_removed == 1
