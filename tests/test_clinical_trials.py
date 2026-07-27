"""Offline tests for ClinicalTrials.gov API v2 normalization."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from rna_monitor.config import load_config
from rna_monitor.http import HttpClient
from rna_monitor.sources.base import RetrievalWindow
from rna_monitor.sources.clinical_trials import (
    ClinicalTrialsAdapter,
    apply_trial_update,
    build_trial_query,
    parse_clinical_trial,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "clinical_trials" / "study.json"


def _study() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parse_clinical_trial_v2() -> None:
    record = parse_clinical_trial(_study(), datetime(2026, 7, 27, tzinfo=UTC))

    assert record.id == "nct:NCT07123456"
    assert record.nct_id == "NCT07123456"
    assert record.development_stages == ["Phase 1"]
    assert record.trial and record.trial.enrollment == 48
    assert record.trial.start_date == date(2026, 8, 1)
    assert record.date_precision["start_date"] == "month"
    assert record.trial.countries == ["Canada", "United States"]
    assert record.trial.intervention_aliases == ["RNA-101", "EX101"]
    assert len(record.trial.outcomes) == 2


def test_trial_update_records_substantive_changes() -> None:
    existing = parse_clinical_trial(_study(), datetime(2026, 7, 26, tzinfo=UTC))
    changed_study = _study()
    protocol = changed_study["protocolSection"]
    assert isinstance(protocol, dict)
    status = protocol["statusModule"]
    design = protocol["designModule"]
    assert isinstance(status, dict)
    assert isinstance(design, dict)
    status["overallStatus"] = "ACTIVE_NOT_RECRUITING"
    design["enrollmentInfo"] = {"count": 52, "type": "ACTUAL"}
    incoming = parse_clinical_trial(changed_study, datetime(2026, 7, 27, tzinfo=UTC))

    updated = apply_trial_update(existing, incoming)

    assert updated.version == 2
    assert updated.change_history[0].fields == [
        "trial.overall_status",
        "trial.enrollment",
    ]
    assert len(updated.provenance) == 2


def test_clinical_trials_query_and_token_pagination() -> None:
    config = load_config(ROOT / "config")
    window = RetrievalWindow(date(2026, 7, 20), date(2026, 7, 27))
    query = build_trial_query(config.queries.source_queries["clinical_trials"], window)
    assert "AREA[StudyType]INTERVENTIONAL" in query
    assert "AREA[LastUpdatePostDate]RANGE[2026-07-20, 2026-07-27]" in query
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            payload = {"studies": [_study()], "nextPageToken": "next-token", "totalCount": 2}
        else:
            second = _study()
            protocol = second["protocolSection"]
            assert isinstance(protocol, dict)
            identification = protocol["identificationModule"]
            assert isinstance(identification, dict)
            identification["nctId"] = "NCT07999999"
            payload = {"studies": [second], "totalCount": 2}
        return httpx.Response(200, json=payload, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    adapter = ClinicalTrialsAdapter(
        config.sources.clinical_trials,
        config.queries.source_queries["clinical_trials"],
        HttpClient(config.sources.http, config.sources.user_agent, client=client),
    )
    result = adapter.fetch(window)

    assert len(result.records) == 2
    assert result.raw_count == 2
    assert dict(requests[1].url.params)["pageToken"] == "next-token"
