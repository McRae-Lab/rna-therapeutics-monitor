"""Transparent, reproducible RNA-therapeutics relevance scoring."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime

from rna_monitor.models import Record, ScoreComponent

DIRECT_ANCHOR = re.compile(
    r"\b(?:therapeutic|therapy|treatment|drug|vaccine|clinical trial|approved)\b",
    re.IGNORECASE,
)

STAGE_POINTS = {
    "basic research": 1.0,
    "platform development": 3.0,
    "preclinical in vitro": 4.0,
    "preclinical animal": 6.0,
    "IND-enabling": 8.0,
    "Phase 1": 10.0,
    "Phase 1/2": 11.0,
    "Phase 2": 12.0,
    "Phase 2/3": 13.0,
    "Phase 3": 14.0,
    "approved": 15.0,
    "post-marketing": 13.0,
    "discontinued": 7.0,
    "unknown": 0.0,
}


def _component(name: str, points: float, maximum: float, reason: str) -> ScoreComponent:
    return ScoreComponent(name=name, points=round(points, 2), maximum=maximum, reason=reason)


def _record_date(record: Record) -> date | None:
    return record.updated_date or record.published_date or record.first_date


def score_record(record: Record, as_of: date | None = None) -> Record:
    """Assign a relevance score; this score is explicitly not scientific quality."""

    reference_date = as_of or datetime.now(UTC).date()
    searchable = " ".join(
        (
            record.title,
            record.abstract or "",
            record.description or "",
            " ".join(record.trial.interventions) if record.trial else "",
        )
    )
    has_anchor = bool(DIRECT_ANCHOR.search(searchable))
    if record.modalities and has_anchor:
        direct_points = 25.0
        direct_reason = "Named RNA modality appears with explicit therapeutic context."
    elif record.modalities:
        direct_points = 15.0
        direct_reason = "Named RNA modality is present without a strong therapeutic anchor."
    elif record.delivery_systems and has_anchor:
        direct_points = 10.0
        direct_reason = "Therapeutic context and a relevant delivery system are present."
    else:
        direct_points = 0.0
        direct_reason = "No deterministic evidence of direct RNA-therapeutic relevance."

    specific_modalities = [value for value in record.modalities if value != "other"]
    modality_points = (
        min(12.0, 8.0 + 2.0 * (len(specific_modalities) - 1)) if specific_modalities else 0
    )
    delivery_points = (
        min(10.0, 6.0 + 2.0 * (len(record.delivery_systems) - 1)) if record.delivery_systems else 0
    )
    stage_points = max(
        (STAGE_POINTS.get(stage, 0.0) for stage in record.development_stages), default=0
    )
    human_points = (
        10.0 if ("human" in record.species or record.record_type == "clinical_trial") else 0.0
    )
    trial_changes = [
        field
        for event in record.change_history
        for field in event.fields
        if field.startswith("trial.")
    ]
    change_points = 8.0 if trial_changes else 0.0
    regulatory_points = (
        8.0
        if record.evidence_level == "regulatory document" or "regulation" in record.topics
        else 0.0
    )
    method_points = min(5.0, 3.0 + len(record.methods)) if record.methods else 0.0
    item_date = _record_date(record)
    age_days = (reference_date - item_date).days if item_date else None
    if age_days is None or age_days < 0:
        recency_points = 0.0
        recency_reason = "No usable date at or before the scoring date."
    elif age_days <= 7:
        recency_points = 5.0
        recency_reason = f"Record is {age_days} days old."
    elif age_days <= 30:
        recency_points = 4.0
        recency_reason = f"Record is {age_days} days old."
    elif age_days <= 90:
        recency_points = 2.0
        recency_reason = f"Record is {age_days} days old."
    elif age_days <= 365:
        recency_points = 1.0
        recency_reason = f"Record is {age_days} days old."
    else:
        recency_points = 0.0
        recency_reason = f"Record is {age_days} days old."
    corroborating_sources = {source for source in record.source_types if source not in {"crossref"}}
    corroboration_points = 2.0 if len(corroborating_sources) >= 2 else 0.0

    components = [
        _component("direct therapeutic relevance", direct_points, 25, direct_reason),
        _component(
            "RNA modality specificity",
            modality_points,
            12,
            f"{len(specific_modalities)} specific modality label(s).",
        ),
        _component(
            "delivery relevance",
            delivery_points,
            10,
            f"{len(record.delivery_systems)} delivery label(s).",
        ),
        _component(
            "translational stage",
            stage_points,
            15,
            "Highest configured development-stage contribution.",
        ),
        _component(
            "human relevance",
            human_points,
            10,
            "Human participants or an interventional trial are present."
            if human_points
            else "No deterministic human evidence.",
        ),
        _component(
            "clinical status change",
            change_points,
            8,
            f"{len(trial_changes)} tracked trial field change(s).",
        ),
        _component(
            "regulatory importance",
            regulatory_points,
            8,
            "Regulatory evidence or topic."
            if regulatory_points
            else "No regulatory evidence or topic.",
        ),
        _component(
            "methodological relevance",
            method_points,
            5,
            f"{len(record.methods)} relevant method label(s).",
        ),
        _component("recency", recency_points, 5, recency_reason),
        _component(
            "source corroboration",
            corroboration_points,
            2,
            f"{len(corroborating_sources)} independent discovery source(s).",
        ),
    ]
    total = sum(component.points for component in components)
    if record.excluded:
        adjustment = min(0.0, 15.0 - total)
        components.append(
            _component(
                "auditable exclusion adjustment",
                adjustment,
                0,
                "Excluded records are retained but capped at relevance 15.",
            )
        )
        total = min(total, 15.0)
    return record.model_copy(
        update={
            "relevance_score": round(max(0.0, min(100.0, total)), 2),
            "score_components": components,
        }
    )


def score_records(records: list[Record], as_of: date | None = None) -> list[Record]:
    """Score records in stable ID order using one shared reference date."""

    reference_date = as_of or datetime.now(UTC).date()
    return [
        score_record(record, reference_date) for record in sorted(records, key=lambda item: item.id)
    ]
