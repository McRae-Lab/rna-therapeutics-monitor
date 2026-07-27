"""Source-date normalization coverage."""

from datetime import date

from rna_monitor.dates import parse_date_parts, parse_flexible_date


def test_date_parsing_preserves_precision_and_rejects_invalid_dates() -> None:
    assert parse_flexible_date("2026").value == date(2026, 1, 1)  # type: ignore[union-attr]
    assert parse_flexible_date("2026").precision == "year"  # type: ignore[union-attr]
    assert parse_flexible_date("2026-Jul").precision == "month"  # type: ignore[union-attr]
    assert parse_flexible_date("2026-07-27").precision == "day"  # type: ignore[union-attr]
    assert parse_date_parts("2026", "02", "30") is None
