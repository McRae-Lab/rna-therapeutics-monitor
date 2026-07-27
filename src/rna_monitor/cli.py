"""Command-line entry point for ingestion and local dataset maintenance."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from rna_monitor.classifier import classify_records
from rna_monitor.config import load_config
from rna_monitor.enrichment import build_summarizer, enrich_records
from rna_monitor.export import export_static_data, validate_public_artifacts
from rna_monitor.logging_utils import configure_logging
from rna_monitor.pipeline import UpdateOptions, build_default_pipeline
from rna_monitor.scoring import score_records
from rna_monitor.storage import load_records, save_records


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("expected YYYY-MM-DD") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rna-monitor")
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--data-dir", type=Path, default=Path("data"))
    parser.add_argument("--site-dir", type=Path, default=Path("site"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    update = subparsers.add_parser("update", help="retrieve and process incremental records")
    update.add_argument("--source", action="append", dest="sources")
    update.add_argument("--days", type=int, default=14)
    update.add_argument("--since", type=_date)
    update.add_argument("--until", type=_date)
    update.add_argument("--limit", type=int)
    update.add_argument("--dry-run", action="store_true")
    update.add_argument("--verbose", action="store_true")
    update.add_argument("--no-llm", action="store_true")

    classify = subparsers.add_parser("classify", help="reclassify and rescore stored records")
    classify.add_argument("--dry-run", action="store_true")
    classify.add_argument("--verbose", action="store_true")

    export = subparsers.add_parser("export", help="generate deterministic public JSON")
    export.add_argument("--verbose", action="store_true")

    build = subparsers.add_parser("build", help="export and validate the static site")
    build.add_argument("--verbose", action="store_true")

    enrich = subparsers.add_parser("enrich", help="run explicitly enabled optional enrichment")
    enrich.add_argument("--provider", choices=("none", "openai", "local"), default="none")
    enrich.add_argument("--model", default="")
    enrich.add_argument("--base-url", default="")
    enrich.add_argument("--cache-dir", type=Path, default=Path(".cache/enrichment"))
    enrich.add_argument("--dry-run", action="store_true")
    enrich.add_argument("--verbose", action="store_true")

    validate = subparsers.add_parser("validate", help="validate configuration and canonical data")
    validate.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI and return a process status."""

    args = _parser().parse_args(argv)
    configure_logging(bool(args.verbose))
    try:
        config = load_config(args.config_dir)
        records_path = args.data_dir / "records.jsonl"
        if args.command == "update":
            options = UpdateOptions(
                since=args.since,
                until=args.until,
                days=args.days,
                sources=args.sources,
                limit=args.limit,
                dry_run=args.dry_run,
                no_llm=True,
            )
            with build_default_pipeline(args.config_dir, args.data_dir) as pipeline:
                report = pipeline.run(options)
            print(json.dumps(report.__dict__, default=str, sort_keys=True))
        elif args.command == "classify":
            records = load_records(records_path)
            output = score_records(classify_records(records, config.categories))
            if not args.dry_run:
                save_records(records_path, output)
            print(json.dumps({"records": len(output), "dry_run": args.dry_run}))
        elif args.command in {"export", "build"}:
            records = load_records(records_path)
            artifacts = export_static_data(records, args.site_dir / "data")
            build_result: dict[str, object] = {
                "artifacts": sorted(artifacts),
                "records": len(records),
            }
            if args.command == "build":
                build_result["validation"] = validate_public_artifacts(args.site_dir / "data")
            print(json.dumps(build_result, sort_keys=True))
        elif args.command == "enrich":
            records = load_records(records_path)
            summarizer = build_summarizer(
                enabled=args.provider != "none",
                provider=args.provider,
                model=args.model,
                base_url=args.base_url,
                cache_dir=args.cache_dir,
            )
            enriched, failures = enrich_records(records, summarizer)
            if not args.dry_run:
                save_records(records_path, enriched)
            print(
                json.dumps(
                    {
                        "records": len(enriched),
                        "failures": failures,
                        "provider": args.provider,
                        "dry_run": args.dry_run,
                    },
                    sort_keys=True,
                )
            )
        else:
            records = load_records(records_path)
            result: dict[str, object] = {
                "configuration": "valid",
                "records": len(records),
            }
            if (args.site_dir / "data").exists():
                result["public"] = validate_public_artifacts(args.site_dir / "data")
            print(json.dumps(result, sort_keys=True))
        return 0
    except Exception as exc:
        print(f"rna-monitor: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
