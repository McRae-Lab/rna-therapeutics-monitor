"""Conservative deterministic record matching and provenance-preserving merges."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from difflib import SequenceMatcher
from typing import Any

from pydantic import HttpUrl

from rna_monitor.identifiers import canonical_id, normalize_doi, normalize_title
from rna_monitor.models import Author, Record
from rna_monitor.sources.clinical_trials import apply_trial_update


@dataclass(frozen=True)
class MergeDecision:
    """Auditable explanation of one deterministic merge."""

    kept_id: str
    merged_id: str
    reason: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable decision."""

        return asdict(self)


@dataclass
class DeduplicationResult:
    """Deduplicated records and their merge log."""

    records: list[Record]
    decisions: list[MergeDecision]


SOURCE_QUALITY = {
    "pubmed": 100,
    "clinicaltrials": 95,
    "biorxiv": 80,
    "medrxiv": 80,
    "crossref": 70,
    "regulatory": 65,
    "rss": 40,
}


def _quality(record: Record) -> int:
    return max((SOURCE_QUALITY.get(source, 20) for source in record.source_types), default=20)


def _author_parts(author: Author) -> tuple[str, str, str | None]:
    def clean(value: str) -> str:
        return re.sub(r"[^\w]", "", unicodedata.normalize("NFKC", value).casefold())

    if author.family_name:
        family = clean(author.family_name)
        given = clean(author.given_name or "")
    else:
        parts = [clean(part) for part in author.name.split() if clean(part)]
        family = parts[-1] if parts else ""
        given = parts[0] if len(parts) > 1 else ""
    orcid = author.orcid.rstrip("/").rsplit("/", 1)[-1] if author.orcid else None
    return family, given, orcid


def authors_corroborate(left: Record, right: Record) -> bool:
    """Require an ORCID match or matching family and nontrivial given name."""

    if not left.authors or not right.authors:
        return False
    left_family, left_given, left_orcid = _author_parts(left.authors[0])
    right_family, right_given, right_orcid = _author_parts(right.authors[0])
    if left_orcid and right_orcid:
        return left_orcid == right_orcid
    if not left_family or left_family != right_family:
        return False
    if not left_given or not right_given:
        return False
    if len(left_given) == 1 or len(right_given) == 1:
        return left_given[0] == right_given[0]
    return left_given == right_given


def _record_date(record: Record) -> date | None:
    return record.first_date or record.published_date or record.updated_date


def _dates_corroborate(left: Record, right: Record, years: int = 2) -> bool:
    left_date = _record_date(left)
    right_date = _record_date(right)
    if not left_date or not right_date:
        return True
    return abs(left_date.year - right_date.year) <= years


def _token_similarity(left: str, right: str) -> float:
    left_tokens = set(left.split())
    right_tokens = set(right.split())
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def match_reason(left: Record, right: Record) -> tuple[str, float] | None:
    """Return a deterministic merge reason, or None when evidence is insufficient."""

    if left.doi and right.doi and normalize_doi(left.doi) == normalize_doi(right.doi):
        return "exact DOI", 1.0
    if left.pmid and right.pmid and left.pmid == right.pmid:
        return "exact PMID", 1.0
    if left.nct_id and right.nct_id and left.nct_id.upper() == right.nct_id.upper():
        return "exact NCT identifier", 1.0
    for source, source_id in left.source_ids.items():
        if right.source_ids.get(source) == source_id:
            return f"exact source identifier ({source})", 1.0

    left_published = left.preprint.published_doi if left.preprint else None
    right_published = right.preprint.published_doi if right.preprint else None
    if left_published and right.doi and normalize_doi(left_published) == normalize_doi(right.doi):
        return "documented preprint-to-journal DOI", 1.0
    if right_published and left.doi and normalize_doi(right_published) == normalize_doi(left.doi):
        return "documented preprint-to-journal DOI", 1.0

    left_title = normalize_title(left.title)
    right_title = normalize_title(right.title)
    if not authors_corroborate(left, right) or not _dates_corroborate(left, right):
        return None
    if left_title == right_title and len(left_title.split()) >= 5:
        return "exact normalized title with author/date corroboration", 0.98
    sequence = SequenceMatcher(None, left_title, right_title, autojunk=False).ratio()
    token = _token_similarity(left_title, right_title)
    if (
        min(len(left_title.split()), len(right_title.split())) >= 8
        and sequence >= 0.96
        and token >= 0.72
    ):
        confidence = round(min(0.97, (sequence + token) / 2), 4)
        return "conservative fuzzy title with author/date corroboration", confidence
    return None


def _unique_strings(*collections: list[str]) -> list[str]:
    return list(dict.fromkeys(value for collection in collections for value in collection if value))


def _unique_models(*collections: list[Any]) -> list[Any]:
    output: list[Any] = []
    seen: set[str] = set()
    for value in (item for collection in collections for item in collection):
        if hasattr(value, "model_dump_json"):
            key = value.model_dump_json(exclude_none=True)
        else:
            key = repr(value)
        if key not in seen:
            seen.add(key)
            output.append(value)
    return output


def _merged_relations(left: Record, right: Record) -> dict[str, list[str]]:
    keys = set(left.relations) | set(right.relations)
    return {
        key: _unique_strings(left.relations.get(key, []), right.relations.get(key, []))
        for key in sorted(keys)
    }


def merge_records(left: Record, right: Record, reason: str) -> Record:
    """Merge two known duplicates while preserving identifiers, URLs, and provenance."""

    if left.nct_id and right.nct_id and left.nct_id == right.nct_id:
        older, newer = sorted((left, right), key=lambda record: record.retrieved_at)
        if older.trial and newer.trial:
            return apply_trial_update(older, newer)

    preferred, secondary = (
        (left, right) if (_quality(left), left.id) >= (_quality(right), right.id) else (right, left)
    )
    journal_record = next(
        (
            record
            for record in (left, right)
            if record.record_type == "publication"
            and (
                (other := right if record is left else left).preprint
                and other.preprint.published_doi
                and normalize_doi(other.preprint.published_doi) == normalize_doi(record.doi)
            )
        ),
        None,
    )
    doi = journal_record.doi if journal_record else preferred.doi or secondary.doi
    pmid = preferred.pmid or secondary.pmid
    nct_id = preferred.nct_id or secondary.nct_id
    source_ids = {**secondary.source_ids, **preferred.source_ids}
    native_source, native_id = next(iter(source_ids.items()), ("merged", ""))
    preferred_date = _record_date(preferred)
    merged_id = canonical_id(
        doi=doi,
        pmid=pmid,
        nct_id=nct_id,
        source=native_source,
        source_id=native_id,
        title=preferred.title,
        first_author=preferred.authors[0].name if preferred.authors else "",
        year=str(preferred_date.year) if preferred_date else "",
    )
    all_urls = list(
        dict.fromkeys(
            str(url)
            for record in (preferred, secondary)
            for url in [record.url, *record.alternate_urls]
        )
    )
    first_dates = [value for value in (left.first_date, right.first_date) if value]
    updated_dates = [value for value in (left.updated_date, right.updated_date) if value]
    abstract = preferred.abstract or secondary.abstract
    pubmed = next(
        (record for record in (left, right) if "pubmed" in record.source_types and record.abstract),
        None,
    )
    if pubmed:
        abstract = pubmed.abstract
    field_sources = {**secondary.field_sources, **preferred.field_sources}
    relations = _merged_relations(left, right)
    if journal_record:
        preprint_record = secondary if journal_record is preferred else preferred
        if preprint_record.doi:
            relations["has-preprint"] = _unique_strings(
                relations.get("has-preprint", []), [preprint_record.doi]
            )
    update = {
        "id": merged_id,
        "source_types": _unique_strings(left.source_types, right.source_types),
        "source_ids": source_ids,
        "abstract": abstract,
        "description": preferred.description or secondary.description,
        "authors": preferred.authors or secondary.authors,
        "organizations": _unique_models(left.organizations, right.organizations),
        "funders": _unique_models(left.funders, right.funders),
        "publisher": preferred.publisher or secondary.publisher,
        "doi": doi,
        "pmid": pmid,
        "nct_id": nct_id,
        "alternate_urls": [HttpUrl(url) for url in all_urls if url != str(preferred.url)],
        "first_date": min(first_dates) if first_dates else None,
        "published_date": preferred.published_date or secondary.published_date,
        "electronic_published_date": (
            preferred.electronic_published_date or secondary.electronic_published_date
        ),
        "updated_date": max(updated_dates) if updated_dates else None,
        "modalities": _unique_strings(left.modalities, right.modalities),
        "delivery_systems": _unique_strings(left.delivery_systems, right.delivery_systems),
        "disease_areas": _unique_strings(left.disease_areas, right.disease_areas),
        "therapeutic_targets": _unique_strings(left.therapeutic_targets, right.therapeutic_targets),
        "development_stages": _unique_strings(left.development_stages, right.development_stages),
        "species": _unique_strings(left.species, right.species),
        "methods": _unique_strings(left.methods, right.methods),
        "topics": _unique_strings(left.topics, right.topics),
        "companies": _unique_strings(left.companies, right.companies),
        "institutions": _unique_strings(left.institutions, right.institutions),
        "keywords": _unique_strings(left.keywords, right.keywords),
        "mesh_terms": _unique_strings(left.mesh_terms, right.mesh_terms),
        "publication_types": _unique_strings(left.publication_types, right.publication_types),
        "provenance": _unique_models(left.provenance, right.provenance),
        "field_sources": field_sources,
        "relations": relations,
        "version": max(left.version, right.version),
        "change_history": _unique_models(left.change_history, right.change_history),
        "excluded": left.excluded and right.excluded,
        "exclusion_reasons": _unique_strings(left.exclusion_reasons, right.exclusion_reasons),
    }
    merged = preferred.model_copy(update=update)
    return merged.model_copy(
        update={
            "provenance": [
                *merged.provenance,
                preferred.provenance[-1].model_copy(
                    update={
                        "note": (
                            f"Deterministic merge: {reason}; preserved all source identifiers."
                        )
                    }
                ),
            ]
            if preferred.provenance
            else merged.provenance
        }
    )


def deduplicate(records: list[Record]) -> DeduplicationResult:
    """Deduplicate in stable order and return every merge decision."""

    kept: list[Record] = []
    decisions: list[MergeDecision] = []
    for candidate in sorted(records, key=lambda record: (record.id, record.retrieved_at)):
        match_index: int | None = None
        match: tuple[str, float] | None = None
        for index, existing in enumerate(kept):
            if result := match_reason(existing, candidate):
                match_index = index
                match = result
                break
        if match_index is None or match is None:
            kept.append(candidate)
            continue
        existing = kept[match_index]
        merged = merge_records(existing, candidate, match[0])
        kept[match_index] = merged
        decisions.append(
            MergeDecision(
                kept_id=merged.id,
                merged_id=candidate.id,
                reason=match[0],
                confidence=match[1],
            )
        )
    return DeduplicationResult(
        records=sorted(kept, key=lambda record: record.id),
        decisions=decisions,
    )
