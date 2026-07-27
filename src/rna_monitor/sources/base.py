"""Common source-adapter types."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from rna_monitor.models import Record


@dataclass(frozen=True)
class RetrievalWindow:
    """Inclusive source retrieval bounds."""

    since: date
    until: date


@dataclass
class SourceResult:
    """Records and diagnostics returned by one source adapter."""

    source: str
    records: list[Record] = field(default_factory=list)
    raw_count: int = 0
    warnings: list[str] = field(default_factory=list)
