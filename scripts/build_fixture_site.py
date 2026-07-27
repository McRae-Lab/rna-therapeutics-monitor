"""Build a representative static site using only saved offline fixtures."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, date, datetime
from pathlib import Path

from rna_monitor.classifier import classify_records
from rna_monitor.config import load_config
from rna_monitor.export import export_static_data, validate_public_artifacts
from rna_monitor.scoring import score_records
from rna_monitor.sources.clinical_trials import parse_clinical_trial
from rna_monitor.sources.preprints import parse_preprint_item
from rna_monitor.sources.pubmed import parse_pubmed_xml


def build_fixture_records(root: Path) -> list:
    """Normalize representative fixtures from each primary adapter."""

    timestamp = datetime(2026, 7, 27, 18, tzinfo=UTC)
    fixtures = root / "tests" / "fixtures"
    records = parse_pubmed_xml(
        (fixtures / "pubmed" / "efetch.xml").read_text(encoding="utf-8"),
        timestamp,
    )
    preprint_page = json.loads((fixtures / "preprints" / "page0.json").read_text(encoding="utf-8"))
    records.append(parse_preprint_item(preprint_page["collection"][1], "biorxiv", timestamp))
    trial = json.loads((fixtures / "clinical_trials" / "study.json").read_text(encoding="utf-8"))
    records.append(parse_clinical_trial(trial, timestamp))
    return records


def main() -> int:
    """Build and validate fixture-backed site data."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("site/data"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    config = load_config(root / "config")
    records = score_records(
        classify_records(build_fixture_records(root), config.categories),
        date(2026, 7, 27),
    )
    export_static_data(
        records,
        args.output,
        generated_at=datetime(2026, 7, 27, 18, tzinfo=UTC),
    )
    validate_public_artifacts(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
