"""Auditable weighted rule-based classification."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field

from rna_monitor.config import CategoriesConfig, ClassificationRule
from rna_monitor.models import ClassificationEvidence, Record


@dataclass
class _Match:
    score: float = 0.0
    phrases: list[str] = field(default_factory=list)
    fields: list[str] = field(default_factory=list)


CATEGORY_FIELDS = {
    "modalities": "modalities",
    "delivery_systems": "delivery_systems",
    "disease_areas": "disease_areas",
    "therapeutic_targets": "therapeutic_targets",
    "development_stages": "development_stages",
    "species": "species",
    "methods": "methods",
    "topics": "topics",
    "companies": "companies",
    "institutions": "institutions",
}


def _searchable_fields(record: Record) -> dict[str, str]:
    interventions: list[str] = []
    if record.trial:
        interventions = [
            *record.trial.interventions,
            *record.trial.intervention_aliases,
        ]
    return {
        "title": record.title,
        "interventions": " ".join(interventions),
        "keywords": " ".join(record.keywords),
        "mesh_terms": " ".join(record.mesh_terms),
        "abstract": record.abstract or "",
        "description": record.description or "",
        "organizations": " ".join(organization.name for organization in record.organizations),
    }


def _rule_match(
    rule: ClassificationRule,
    searchable: dict[str, str],
    weights: dict[str, float],
) -> _Match | None:
    for negative in rule.negative_patterns:
        if any(re.search(negative, text, re.IGNORECASE) for text in searchable.values()):
            return None
    result = _Match()
    for field_name, text in searchable.items():
        if not text:
            continue
        for pattern in rule.patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                phrase = match.group(0)
                result.score += weights.get(field_name, 1.0) * rule.weight
                if phrase.casefold() not in {value.casefold() for value in result.phrases}:
                    result.phrases.append(phrase)
                if field_name not in result.fields:
                    result.fields.append(field_name)
    return result if result.score >= rule.minimum_score else None


def _metadata_evidence(record: Record) -> dict[str, list[ClassificationEvidence]]:
    evidence: dict[str, list[ClassificationEvidence]] = defaultdict(list)
    for organization in record.organizations:
        if organization.organization_type == "sponsor":
            evidence["companies"].append(
                ClassificationEvidence(
                    label=organization.name,
                    confidence=1.0,
                    matched_phrases=[organization.name],
                    fields=["organizations"],
                    method="source-metadata",
                )
            )
        elif organization.organization_type in {"affiliation", "collaborator"}:
            evidence["institutions"].append(
                ClassificationEvidence(
                    label=organization.name,
                    confidence=1.0,
                    matched_phrases=[organization.name],
                    fields=["organizations"],
                    method="source-metadata",
                )
            )
    return dict(evidence)


def classify_record(record: Record, config: CategoriesConfig) -> Record:
    """Classify one record with configured expressions and weighted fields."""

    searchable = _searchable_fields(record)
    classifications: dict[str, list[str]] = {
        field: ([] if field == "topics" else list(getattr(record, field)))
        for field in CATEGORY_FIELDS.values()
    }
    evidence: dict[str, list[ClassificationEvidence]] = {
        key: [
            item for item in value if not (key == "topics" and item.method == "deterministic-rules")
        ]
        for key, value in record.classification_evidence.items()
    }
    for category, rules in config.categories.items():
        target_field = CATEGORY_FIELDS.get(category)
        if not target_field:
            continue
        for rule in rules:
            match = _rule_match(rule, searchable, config.field_weights)
            if not match:
                continue
            if rule.label not in classifications[target_field]:
                classifications[target_field].append(rule.label)
            confidence = min(1.0, match.score / max(rule.minimum_score * 3, 1.0))
            evidence.setdefault(category, []).append(
                ClassificationEvidence(
                    label=rule.label,
                    confidence=round(confidence, 3),
                    matched_phrases=match.phrases,
                    fields=match.fields,
                    method="deterministic-rules",
                )
            )

    for category, entries in _metadata_evidence(record).items():
        target_field = CATEGORY_FIELDS[category]
        for item in entries:
            if item.label not in classifications[target_field]:
                classifications[target_field].append(item.label)
            if not any(existing.label == item.label for existing in evidence.get(category, [])):
                evidence.setdefault(category, []).append(item)

    negative_matches = [
        match.group(0)
        for pattern in config.global_negative_patterns
        for text in searchable.values()
        for match in re.finditer(pattern, text, re.IGNORECASE)
    ]
    exclusion_reasons = list(record.exclusion_reasons)
    excluded = record.excluded
    if negative_matches and not classifications["modalities"]:
        excluded = True
        exclusion_reasons.extend(
            f"classification negative pattern: {phrase}" for phrase in negative_matches
        )
    updates = {
        **classifications,
        "classification_evidence": {
            category: sorted(items, key=lambda item: item.label.casefold())
            for category, items in sorted(evidence.items())
        },
        "classification_method": "deterministic-rules-v1",
        "excluded": excluded,
        "exclusion_reasons": list(dict.fromkeys(exclusion_reasons)),
    }
    return record.model_copy(update=updates)


def classify_records(records: list[Record], config: CategoriesConfig) -> list[Record]:
    """Classify records in deterministic ID order."""

    return [classify_record(record, config) for record in sorted(records, key=lambda item: item.id)]
