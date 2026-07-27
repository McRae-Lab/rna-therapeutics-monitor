"""Deterministic public JSON generation for the static website."""

from __future__ import annotations

import html
import json
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from rna_monitor.models import Record
from rna_monitor.storage import _atomic_write

PUBLIC_ARTIFACTS = (
    "records.min.json",
    "latest.json",
    "statistics.json",
    "facets.json",
    "last_updated.json",
    "methodology.json",
)


def escape_html(value: str) -> str:
    """Escape source-controlled text when it must enter an HTML string."""

    return html.escape(value, quote=True)


def _public_provenance(record: Record) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in entry.model_dump(mode="json", exclude_none=True).items()
            if key != "raw_sha256"
        }
        for entry in record.provenance
    ]


def public_record(record: Record) -> dict[str, Any]:
    """Return the stable public projection of a canonical record."""

    output = record.model_dump(mode="json", exclude_none=True)
    output["provenance"] = _public_provenance(record)
    return output


def _sort_date(record: Record) -> date:
    return record.updated_date or record.published_date or record.first_date or date.min


def _counter(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items(), key=lambda item: item[0].casefold()))


def _statistics(records: list[Record], generated_at: datetime) -> dict[str, Any]:
    included = [record for record in records if not record.excluded]
    return {
        "schema_version": 1,
        "generated_at": generated_at.isoformat(),
        "total_records": len(records),
        "included_records": len(included),
        "excluded_records": len(records) - len(included),
        "recently_changed_records": sum(bool(record.change_history) for record in records),
        "average_relevance_score": (
            round(sum(record.relevance_score for record in included) / len(included), 2)
            if included
            else 0.0
        ),
        "by_record_type": _counter([record.record_type for record in records]),
        "by_evidence_level": _counter([record.evidence_level for record in records]),
        "by_source": _counter([source for record in records for source in record.source_types]),
    }


def _facets(records: list[Record]) -> dict[str, Any]:
    fields = {
        "source_types": [value for record in records for value in record.source_types],
        "modalities": [value for record in records for value in record.modalities],
        "delivery_systems": [value for record in records for value in record.delivery_systems],
        "disease_areas": [value for record in records for value in record.disease_areas],
        "development_stages": [value for record in records for value in record.development_stages],
        "evidence_levels": [record.evidence_level for record in records],
        "companies": [value for record in records for value in record.companies],
        "institutions": [value for record in records for value in record.institutions],
        "topics": [value for record in records for value in record.topics],
        "trial_statuses": [
            record.trial.overall_status
            for record in records
            if record.trial and record.trial.overall_status
        ],
        "preprint_statuses": [
            record.preprint.publication_status
            for record in records
            if record.preprint and record.preprint.publication_status
        ],
    }
    return {
        "schema_version": 1,
        "facets": {name: _counter(values) for name, values in fields.items()},
    }


def _methodology(generated_at: datetime, llm_enabled: bool) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "methodology_revision": "2026-07-27",
        "generated_at": generated_at.isoformat(),
        "classification_method": "deterministic-rules-v1",
        "llm_enabled": llm_enabled,
        "score_name": "relevance priority score",
        "score_range": [0, 100],
        "score_is_scientific_quality": False,
        "score_components": {
            "direct therapeutic relevance": 25,
            "RNA modality specificity": 12,
            "delivery relevance": 10,
            "translational stage": 15,
            "human relevance": 10,
            "clinical status change": 8,
            "regulatory importance": 8,
            "methodological relevance": 5,
            "recency": 5,
            "source corroboration": 2,
        },
        "disclaimer": (
            "Inclusion does not represent endorsement. Automated classifications "
            "and relevance scores can contain errors."
        ),
    }


def _write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    if compact:
        content = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    else:
        content = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
    _atomic_write(path, content + "\n")


def export_static_data(
    records: list[Record],
    output_dir: Path,
    *,
    generated_at: datetime | None = None,
    latest_limit: int = 100,
) -> dict[str, Any]:
    """Generate every public data artifact deterministically."""

    timestamp = generated_at or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("export timestamp must be timezone aware")
    output_dir.mkdir(parents=True, exist_ok=True)
    stable_records = sorted(
        records,
        key=lambda record: (-_sort_date(record).toordinal(), -record.relevance_score, record.id),
    )
    public = [public_record(record) for record in stable_records]
    latest = [public_record(record) for record in stable_records if not record.excluded][
        :latest_limit
    ]
    artifacts: dict[str, Any] = {
        "records.min.json": public,
        "latest.json": latest,
        "statistics.json": _statistics(stable_records, timestamp),
        "facets.json": _facets(stable_records),
        "last_updated.json": {
            "schema_version": 1,
            "generated_at": timestamp.isoformat(),
            "record_count": len(stable_records),
        },
        "methodology.json": _methodology(
            timestamp,
            any(
                record.enrichment_metadata is not None
                and record.enrichment_metadata.provider != "none"
                for record in stable_records
            ),
        ),
    }
    for name, payload in artifacts.items():
        _write_json(output_dir / name, payload, compact=name.endswith(".min.json"))
    return artifacts


def validate_public_artifacts(output_dir: Path) -> dict[str, int]:
    """Parse and structurally validate generated artifacts."""

    missing = [name for name in PUBLIC_ARTIFACTS if not (output_dir / name).is_file()]
    if missing:
        raise ValueError(f"missing public artifacts: {missing}")
    records_payload = json.loads((output_dir / "records.min.json").read_text(encoding="utf-8"))
    if not isinstance(records_payload, list):
        raise ValueError("records.min.json must contain a list")
    for index, raw in enumerate(records_payload):
        try:
            Record.model_validate(raw)
        except Exception as exc:
            raise ValueError(f"invalid public record at index {index}") from exc
    latest = json.loads((output_dir / "latest.json").read_text(encoding="utf-8"))
    if not isinstance(latest, list):
        raise ValueError("latest.json must contain a list")
    for name in PUBLIC_ARTIFACTS[2:]:
        payload = json.loads((output_dir / name).read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != 1:
            raise ValueError(f"{name} must be a schema-versioned object")
    return {"records": len(records_payload), "latest": len(latest)}
