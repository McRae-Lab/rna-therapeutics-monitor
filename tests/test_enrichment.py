"""Credential, malformed-output, structured validation, and cache tests."""

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from rna_monitor.enrichment import (
    OpenAICompatibleSummarizer,
    apply_enrichment,
    build_summarizer,
    enrich_records,
)
from rna_monitor.models import Record
from rna_monitor.sources.pubmed import parse_pubmed_xml

ROOT = Path(__file__).resolve().parents[1]
PUBMED = ROOT / "tests" / "fixtures" / "pubmed" / "efetch.xml"


def _record() -> Record:
    return parse_pubmed_xml(
        PUBMED.read_text(encoding="utf-8"),
        datetime(2026, 7, 27, tzinfo=UTC),
    )[0]


def _response(content: str, request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}]},
        request=request,
    )


def test_absent_hosted_credentials_fail_only_when_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert build_summarizer(enabled=False).__class__.__name__ == "NoOpSummarizer"
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        build_summarizer(enabled=True, provider="openai", model="example-model")


def test_valid_llm_result_is_cached_and_reused(tmp_path: Path) -> None:
    calls = 0
    content = json.dumps(
        {
            "summary": "A two-sentence factual summary.",
            "key_findings": ["mRNA was delivered in mice."],
            "modalities": ["mRNA"],
            "delivery_systems": ["lipid nanoparticle"],
            "disease_areas": [],
            "development_stages": ["preclinical animal"],
            "therapeutic_targets": [],
            "species": ["mouse"],
            "numerical_results": [],
            "uncertainty_notes": ["Clinical efficacy is unknown."],
        }
    )

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(content, request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    summarizer = OpenAICompatibleSummarizer(
        provider="fixture",
        model="fixture-model",
        base_url="https://example.org/v1",
        cache_dir=tmp_path,
        client=client,
    )
    first = summarizer.enrich(_record())
    second = summarizer.enrich(_record())
    enriched = apply_enrichment(_record(), second)

    assert calls == 1
    assert first == second
    assert enriched.summary == "A two-sentence factual summary."
    assert enriched.enrichment_metadata
    assert enriched.enrichment_metadata.input_hash == first.input_hash
    assert enriched.modalities == ["mRNA"]


def test_malformed_llm_json_does_not_prevent_publication(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return _response("not-json", request)

    summarizer = OpenAICompatibleSummarizer(
        provider="fixture",
        model="fixture-model",
        base_url="https://example.org/v1",
        cache_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        max_attempts=1,
    )
    original = _record()
    records, failures = enrich_records([original], summarizer)

    assert records == [original]
    assert failures == [f"{original.id}: ValidationError"]
    assert not list(tmp_path.glob("*.json"))


def test_cache_key_changes_with_relevant_content(tmp_path: Path) -> None:
    content = json.dumps(
        {
            "summary": None,
            "key_findings": [],
            "modalities": [],
            "delivery_systems": [],
            "disease_areas": [],
            "development_stages": [],
            "therapeutic_targets": [],
            "species": [],
            "numerical_results": [],
            "uncertainty_notes": [],
        }
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _response(content, request)

    summarizer = OpenAICompatibleSummarizer(
        provider="fixture",
        model="fixture-model",
        base_url="https://example.org/v1",
        cache_dir=tmp_path,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    record = _record()
    summarizer.enrich(record)
    summarizer.enrich(record.model_copy(update={"abstract": "Changed public abstract."}))

    assert calls == 2
    assert len(list(tmp_path.glob("*.json"))) == 2
