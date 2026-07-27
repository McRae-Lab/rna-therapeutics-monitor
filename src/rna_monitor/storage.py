"""Atomic local storage for canonical records and incremental source state."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

from pydantic import Field

from rna_monitor.models import Record, StrictModel


class SourceState(StrictModel):
    """Last successful retrieval boundary for one source."""

    last_successful_until: date
    last_retrieved_at: datetime
    raw_count: int = Field(ge=0)


class PipelineState(StrictModel):
    """Versioned persisted state for all adapters."""

    schema_version: int = 1
    sources: dict[str, SourceState] = Field(default_factory=dict)


FINGERPRINT_EXCLUDES = {
    "retrieved_at",
    "provenance",
    "modalities",
    "delivery_systems",
    "disease_areas",
    "therapeutic_targets",
    "development_stages",
    "species",
    "methods",
    "topics",
    "companies",
    "institutions",
    "classification_method",
    "classification_evidence",
    "score_components",
    "relevance_score",
    "excluded",
    "exclusion_reasons",
}


def content_fingerprint(record: Record) -> str:
    """Hash substantive normalized content, excluding run-specific metadata."""

    payload = record.model_dump(
        mode="json",
        exclude=FINGERPRINT_EXCLUDES,
        exclude_none=False,
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_records(path: Path) -> list[Record]:
    """Load strict JSON Lines records; an absent file means an empty dataset."""

    if not path.exists():
        return []
    records: list[Record] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(Record.model_validate_json(line))
        except Exception as exc:
            raise ValueError(f"invalid canonical record at {path}:{line_number}") from exc
    return records


def load_state(path: Path) -> PipelineState:
    """Load pipeline state; an absent file starts at schema version one."""

    if not path.exists():
        return PipelineState()
    return PipelineState.model_validate_json(path.read_text(encoding="utf-8"))


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def save_records(path: Path, records: list[Record]) -> None:
    """Atomically write canonical JSON Lines in stable ID order."""

    lines = [
        record.model_dump_json(exclude_none=False)
        for record in sorted(records, key=lambda item: item.id)
    ]
    _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))


def save_state(path: Path, state: PipelineState) -> None:
    """Atomically write deterministic, human-readable source state."""

    payload: dict[str, Any] = state.model_dump(mode="json")
    _atomic_write(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")
