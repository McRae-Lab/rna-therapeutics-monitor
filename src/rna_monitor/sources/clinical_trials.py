"""ClinicalTrials.gov API v2 discovery, normalization, and update history."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import HttpUrl

from rna_monitor.config import ClinicalTrialsSettings, SourceQuery
from rna_monitor.dates import ParsedDate, parse_flexible_date
from rna_monitor.http import HttpClient
from rna_monitor.identifiers import canonical_id
from rna_monitor.models import (
    ChangeEvent,
    Organization,
    ProvenanceEntry,
    Record,
    TrialDetails,
    TrialLocation,
    TrialOutcome,
)
from rna_monitor.sources.base import RetrievalWindow, SourceResult


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _date_struct(module: dict[str, Any], key: str) -> ParsedDate | None:
    return parse_flexible_date(_string(_mapping(module.get(key)).get("date")))


def _phase_label(value: str) -> str:
    return {
        "EARLY_PHASE1": "Phase 1",
        "PHASE1": "Phase 1",
        "PHASE1|PHASE2": "Phase 1/2",
        "PHASE2": "Phase 2",
        "PHASE2|PHASE3": "Phase 2/3",
        "PHASE3": "Phase 3",
    }.get(value.upper(), "unknown")


def _outcomes(module: dict[str, Any]) -> list[TrialOutcome]:
    output: list[TrialOutcome] = []
    outcome_specs: tuple[tuple[str, Literal["primary", "secondary", "other"]], ...] = (
        ("primaryOutcomes", "primary"),
        ("secondaryOutcomes", "secondary"),
        ("otherOutcomes", "other"),
    )
    for key, outcome_type in outcome_specs:
        for raw in _list(module.get(key)):
            item = _mapping(raw)
            measure = _string(item.get("measure"))
            if measure:
                output.append(
                    TrialOutcome(
                        outcome_type=outcome_type,
                        measure=measure,
                        description=_string(item.get("description")),
                        time_frame=_string(item.get("timeFrame")),
                    )
                )
    return output


def parse_clinical_trial(study: dict[str, Any], retrieved_at: datetime | None = None) -> Record:
    """Normalize one ClinicalTrials.gov v2 study object."""

    timestamp = retrieved_at or datetime.now(UTC)
    protocol = _mapping(study.get("protocolSection"))
    identification = _mapping(protocol.get("identificationModule"))
    description = _mapping(protocol.get("descriptionModule"))
    sponsors = _mapping(protocol.get("sponsorCollaboratorsModule"))
    conditions_module = _mapping(protocol.get("conditionsModule"))
    arms = _mapping(protocol.get("armsInterventionsModule"))
    design = _mapping(protocol.get("designModule"))
    status = _mapping(protocol.get("statusModule"))
    locations_module = _mapping(protocol.get("contactsLocationsModule"))
    outcomes_module = _mapping(protocol.get("outcomesModule"))

    nct_id = _string(identification.get("nctId"))
    brief_title = _string(identification.get("briefTitle"))
    official_title = _string(identification.get("officialTitle"))
    title = official_title or brief_title
    if not nct_id or not title:
        raise ValueError("ClinicalTrials.gov study requires nctId and a title")

    lead_sponsor = _string(_mapping(sponsors.get("leadSponsor")).get("name"))
    collaborators = [
        name
        for raw in _list(sponsors.get("collaborators"))
        if (name := _string(_mapping(raw).get("name")))
    ]
    conditions = [
        value for raw in _list(conditions_module.get("conditions")) if (value := _string(raw))
    ]
    interventions: list[str] = []
    aliases: list[str] = []
    for raw in _list(arms.get("interventions")):
        item = _mapping(raw)
        name = _string(item.get("name"))
        if name:
            interventions.append(name)
        aliases.extend(
            value for alias in _list(item.get("otherNames")) if (value := _string(alias))
        )
    phases_raw = [value for raw in _list(design.get("phases")) if (value := _string(raw))]
    phases = list(dict.fromkeys(_phase_label(value) for value in phases_raw))
    enrollment_raw = _mapping(design.get("enrollmentInfo")).get("count")
    enrollment = int(enrollment_raw) if isinstance(enrollment_raw, (int, str)) else None

    start = _date_struct(status, "startDateStruct")
    primary_completion = _date_struct(status, "primaryCompletionDateStruct")
    completion = _date_struct(status, "completionDateStruct")
    first_posted = _date_struct(status, "studyFirstPostDateStruct")
    updated = _date_struct(status, "lastUpdatePostDateStruct")
    locations = [
        TrialLocation(
            facility=_string(_mapping(raw).get("facility")),
            city=_string(_mapping(raw).get("city")),
            state=_string(_mapping(raw).get("state")),
            country=_string(_mapping(raw).get("country")),
        )
        for raw in _list(locations_module.get("locations"))
        if isinstance(raw, dict)
    ]
    countries = sorted({location.country for location in locations if location.country})
    outcomes = _outcomes(outcomes_module)
    has_results = bool(study.get("hasResults", False))
    source_url = f"https://clinicaltrials.gov/study/{nct_id}"
    organizations = [
        Organization(
            name=name,
            organization_type="sponsor" if name == lead_sponsor else "collaborator",
        )
        for name in [lead_sponsor, *collaborators]
        if name
    ]
    raw_bytes = json.dumps(study, sort_keys=True, separators=(",", ":")).encode()
    date_precision = {
        key: value.precision
        for key, value in (
            ("first_date", first_posted),
            ("updated_date", updated),
            ("start_date", start),
            ("primary_completion_date", primary_completion),
            ("completion_date", completion),
        )
        if value
    }
    return Record(
        id=canonical_id(
            nct_id=nct_id,
            source="clinicaltrials",
            source_id=nct_id,
            title=title,
            year=str(first_posted.value.year) if first_posted else "",
        ),
        record_type="clinical_trial",
        source_types=["clinicaltrials"],
        source_ids={"clinicaltrials": nct_id},
        title=title,
        abstract=_string(description.get("briefSummary")),
        description=_string(description.get("detailedDescription")),
        organizations=organizations,
        journal_or_source="ClinicalTrials.gov",
        nct_id=nct_id,
        url=HttpUrl(source_url),
        first_date=first_posted.value if first_posted else None,
        published_date=first_posted.value if first_posted else None,
        updated_date=updated.value if updated else None,
        retrieved_at=timestamp,
        development_stages=phases,
        companies=[lead_sponsor] if lead_sponsor else [],
        institutions=collaborators,
        keywords=conditions,
        date_precision=date_precision,
        evidence_level="trial results" if has_results else "trial registration",
        trial=TrialDetails(
            official_title=official_title,
            brief_title=brief_title,
            sponsor=lead_sponsor,
            collaborators=collaborators,
            conditions=conditions,
            interventions=interventions,
            intervention_aliases=aliases,
            study_type=_string(design.get("studyType")),
            phase=phases_raw,
            overall_status=_string(status.get("overallStatus")),
            enrollment=enrollment,
            start_date=start.value if start else None,
            primary_completion_date=primary_completion.value if primary_completion else None,
            completion_date=completion.value if completion else None,
            locations=locations,
            countries=countries,
            outcomes=outcomes,
            results_available=has_results,
        ),
        provenance=[
            ProvenanceEntry(
                source="clinicaltrials",
                source_id=nct_id,
                url=HttpUrl(source_url),
                retrieved_at=timestamp,
                fields=["title", "abstract", "description", "organizations", "trial"],
                raw_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            )
        ],
        field_sources={
            field: "clinicaltrials"
            for field in ("title", "abstract", "description", "organizations", "trial")
        },
    )


TRACKED_TRIAL_FIELDS = (
    "overall_status",
    "enrollment",
    "phase",
    "start_date",
    "primary_completion_date",
    "completion_date",
    "interventions",
    "outcomes",
)


def apply_trial_update(existing: Record, incoming: Record) -> Record:
    """Replace a trial snapshot while recording substantive tracked changes."""

    if existing.nct_id != incoming.nct_id or not existing.trial or not incoming.trial:
        raise ValueError("trial updates require matching NCT IDs and trial details")
    old = existing.trial.model_dump(mode="json")
    new = incoming.trial.model_dump(mode="json")
    changed = [field for field in TRACKED_TRIAL_FIELDS if old[field] != new[field]]
    history = list(existing.change_history)
    version = existing.version
    if changed:
        history.append(
            ChangeEvent(
                changed_at=incoming.retrieved_at,
                source="clinicaltrials",
                fields=[f"trial.{field}" for field in changed],
                summary=f"ClinicalTrials.gov updated: {', '.join(changed)}",
                old_values={field: old[field] for field in changed},
                new_values={field: new[field] for field in changed},
            )
        )
        version += 1
    return incoming.model_copy(
        update={
            "version": version,
            "change_history": history,
            "provenance": [*existing.provenance, *incoming.provenance],
        }
    )


def build_trial_query(source_query: SourceQuery, window: RetrievalWindow) -> str:
    """Build v2 advanced syntax for interventional studies and updates."""

    terms = " OR ".join(f"({query})" for query in source_query.queries)
    dates = f"AREA[LastUpdatePostDate]RANGE[{window.since.isoformat()}, {window.until.isoformat()}]"
    return f"({terms}) AND AREA[StudyType]INTERVENTIONAL AND {dates}"


class ClinicalTrialsAdapter:
    """Incremental ClinicalTrials.gov API v2 adapter."""

    name = "clinicaltrials"

    def __init__(
        self,
        settings: ClinicalTrialsSettings,
        source_query: SourceQuery,
        http: HttpClient,
    ) -> None:
        self.settings = settings
        self.source_query = source_query
        self.http = http

    def fetch(self, window: RetrievalWindow, limit: int | None = None) -> SourceResult:
        """Retrieve every API page for the configured therapeutic query."""

        records: list[Record] = []
        page_token: str | None = None
        query = build_trial_query(self.source_query, window)
        total_count = 0
        while limit is None or len(records) < limit:
            params: dict[str, Any] = {
                "format": "json",
                "query.term": query,
                "pageSize": min(self.settings.page_size, limit or self.settings.page_size),
                "countTotal": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            payload = self.http.get(
                f"{str(self.settings.base_url).rstrip('/')}/studies", params=params
            ).json()
            studies = _list(payload.get("studies"))
            total_count = int(payload.get("totalCount", len(records) + len(studies)))
            for study in studies:
                if isinstance(study, dict):
                    records.append(parse_clinical_trial(study))
                    if limit is not None and len(records) >= limit:
                        break
            page_token = _string(payload.get("nextPageToken"))
            if not page_token or not studies:
                break
        return SourceResult(source=self.name, records=records, raw_count=total_count)
