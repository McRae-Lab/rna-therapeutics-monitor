"""Conservative identity resolution for the Society author watchlist."""

from __future__ import annotations

import re
import unicodedata

from rna_monitor.config import WatchedPerson
from rna_monitor.models import Author, Record


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_text = "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )
    return " ".join(re.sub(r"[^a-z0-9]+", " ", ascii_text.casefold()).split())


def _orcid(value: str | None) -> str:
    if not value:
        return ""
    return value.casefold().removeprefix("https://orcid.org/").strip()


def _name_matches(author: Author, aliases: list[str]) -> bool:
    author_family = _normalize(author.family_name or author.name).split()[-1:]
    author_given = _normalize(author.given_name or author.name).split()
    if not author_family or not author_given:
        return False
    author_first = author_given[0]
    for alias in aliases:
        parts = _normalize(alias).split()
        if len(parts) < 2 or parts[-1] != author_family[0]:
            continue
        alias_first = parts[0]
        # Full given-name agreement is deliberate. Initial-only matching was the
        # source of Michelle/Meredith Hastings and Timothy/Tianlun Yu false hits.
        if len(alias_first) > 1 and len(author_first) > 1 and alias_first == author_first:
            return True
    return False


def _affiliation_matches(author: Author, person: WatchedPerson, record: Record) -> bool:
    if not person.affiliation_terms:
        return not person.require_affiliation
    affiliations = _normalize(
        " ".join(
            [
                *author.affiliations,
                *(organization.name for organization in record.organizations),
                *record.institutions,
            ]
        )
    )
    return any(_normalize(term) in affiliations for term in person.affiliation_terms)


def match_watched_people(record: Record, people: list[WatchedPerson]) -> list[str]:
    """Return display names supported by ORCID or strict bibliographic identity."""

    matches: list[str] = []
    for person in people:
        if not person.active:
            continue
        exact_orcid = bool(
            person.orcid
            and any(_orcid(author.orcid) == _orcid(person.orcid) for author in record.authors)
        )
        bibliographic = any(
            _name_matches(author, person.aliases) and _affiliation_matches(author, person, record)
            for author in record.authors
        )
        if exact_orcid or bibliographic:
            matches.append(person.display_name)
    return matches
