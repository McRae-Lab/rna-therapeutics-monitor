"""Deterministic public artifact and HTML-escaping tests."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from rna_monitor.export import (
    PUBLIC_ARTIFACTS,
    escape_html,
    export_static_data,
    validate_public_artifacts,
)
from rna_monitor.sources.pubmed import parse_pubmed_xml

ROOT = Path(__file__).resolve().parents[1]
PUBMED = ROOT / "tests" / "fixtures" / "pubmed" / "efetch.xml"
STAMP = datetime(2026, 7, 27, 18, tzinfo=UTC)


def _records() -> list:
    return parse_pubmed_xml(PUBMED.read_text(encoding="utf-8"), STAMP)


def test_deterministic_exports_are_byte_identical(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    export_static_data(_records(), first, generated_at=STAMP)
    export_static_data(list(reversed(_records())), second, generated_at=STAMP)

    for name in PUBLIC_ARTIFACTS:
        assert (first / name).read_bytes() == (second / name).read_bytes()
    assert validate_public_artifacts(first) == {"records": 2, "latest": 2}


def test_public_projection_retains_provenance_but_omits_raw_hash(tmp_path: Path) -> None:
    export_static_data(_records(), tmp_path, generated_at=STAMP)
    records = json.loads((tmp_path / "records.min.json").read_text(encoding="utf-8"))

    assert records[0]["provenance"]
    assert "raw_sha256" not in records[0]["provenance"][0]
    assert records[0]["score_components"] == []


def test_html_escaping_covers_source_controlled_markup() -> None:
    assert escape_html('<img src=x onerror="alert(1)">') == (
        "&lt;img src=x onerror=&quot;alert(1)&quot;&gt;"
    )


def test_validation_rejects_missing_or_malformed_artifacts(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="missing public artifacts"):
        validate_public_artifacts(tmp_path)
    export_static_data(_records(), tmp_path, generated_at=STAMP)
    (tmp_path / "statistics.json").write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match=r"statistics\.json"):
        validate_public_artifacts(tmp_path)
