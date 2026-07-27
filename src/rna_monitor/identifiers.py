"""Stable identifier normalization shared by source adapters."""

from __future__ import annotations

import hashlib
import re
import unicodedata


def normalize_doi(value: str | None) -> str | None:
    """Return a lowercase DOI without resolver or label prefixes."""

    if not value:
        return None
    normalized = value.strip().casefold()
    normalized = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", normalized)
    normalized = normalized.rstrip(" .")
    return normalized or None


def normalize_title(value: str) -> str:
    """Normalize title text for deterministic hashing and later comparison."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"\b(?:version|v)\s*\d+\b", " ", normalized)
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    return " ".join(normalized.split())


def canonical_id(
    *,
    doi: str | None = None,
    pmid: str | None = None,
    nct_id: str | None = None,
    source: str,
    source_id: str,
    title: str,
    first_author: str = "",
    year: str = "",
) -> str:
    """Build a stable canonical ID using the documented priority order."""

    normalized_doi = normalize_doi(doi)
    if normalized_doi:
        return f"doi:{normalized_doi}"
    if pmid:
        return f"pmid:{pmid.strip()}"
    if nct_id:
        return f"nct:{nct_id.strip().upper()}"
    if source_id:
        return f"{source.casefold()}:{source_id.strip()}"
    material = "|".join(
        (
            normalize_title(title),
            unicodedata.normalize("NFKC", first_author).casefold().strip(),
            source.casefold().strip(),
            year.strip(),
        )
    )
    return f"sha256:{hashlib.sha256(material.encode()).hexdigest()}"
