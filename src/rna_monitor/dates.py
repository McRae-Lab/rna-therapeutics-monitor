"""Conservative source-date parsing with explicit precision."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class ParsedDate:
    """A normalized date and the precision supplied by the source."""

    value: date
    precision: str


MONTHS = {
    name.casefold(): number for number, name in enumerate(calendar.month_abbr) if number and name
} | {name.casefold(): number for number, name in enumerate(calendar.month_name) if number and name}


def parse_date_parts(
    year: str | None,
    month: str | None = None,
    day: str | None = None,
) -> ParsedDate | None:
    """Parse separately supplied date components without inventing precision."""

    if not year or not year.isdigit():
        return None
    month_number = 1
    precision = "year"
    if month:
        month_number = int(month) if month.isdigit() else MONTHS.get(month.casefold(), 0)
        if not 1 <= month_number <= 12:
            return None
        precision = "month"
    day_number = 1
    if day and day.isdigit():
        day_number = int(day)
        precision = "day"
    try:
        return ParsedDate(date(int(year), month_number, day_number), precision)
    except ValueError:
        return None


def parse_flexible_date(value: str | None) -> ParsedDate | None:
    """Parse common API date formats while retaining their source precision."""

    if not value:
        return None
    clean = value.strip()
    match = re.fullmatch(r"(\d{4})(?:[-/](\d{1,2}|[A-Za-z]+))?(?:[-/ ](\d{1,2}))?", clean)
    if match:
        return parse_date_parts(*match.groups())
    year_match = re.search(r"\b(\d{4})\b", clean)
    if year_match:
        return parse_date_parts(year_match.group(1))
    return None
