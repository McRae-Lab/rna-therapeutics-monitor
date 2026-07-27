# RNA Therapeutics Monitor

Production-oriented monitoring of recent RNA-therapeutics publications,
preprints, clinical trials, regulatory developments, and selected RSS sources.
The pipeline normalizes, deduplicates, classifies, scores, and exports records
for a static GitHub Pages website.

> Work in progress: checkpoints 1-10 establish ingestion, deduplication,
> auditable classification, and transparent relevance scoring.

The default implementation targets Python 3.12 and requires no API keys.

## Development

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.lock
pytest
ruff check .
mypy src
```

The GitHub Pages site is public. Generated files must never contain secrets.

## Configuration

- `config/queries.yml` separates high-precision terms, broad discovery terms,
  auditable exclusions, and source-specific query syntax. A bare `RNA` query is
  rejected.
- `config/sources.yml` holds endpoints, bounded HTTP behavior, overlap windows,
  contact settings, and attributed RSS feeds.
- `config/categories.yml` holds weighted regular expressions, field weights,
  and negative patterns for deterministic classification.

Validate all three files by loading them:

```bash
python -c "from rna_monitor.config import load_config; load_config()"
```

## Implemented sources

### PubMed

The PubMed adapter uses ESearch for discovery and EFetch XML for complete
metadata. It combines publication-date and modification-date windows, includes
the configured `tool` and contact email, preserves partial-date precision, and
supports records without abstracts or DOIs. Set `RNA_MONITOR_CONTACT_EMAIL` to
the maintainer address used for NCBI requests.

### bioRxiv and medRxiv

The preprint adapter uses the official date-interval endpoint and follows cursor
pages for both servers. Keyword scope is applied locally because this endpoint
is interval based. Different versions retain a single logical DOI-based record,
with the earliest posting date, newest metadata, revision history, and any
preprint-to-journal DOI relationship.

### ClinicalTrials.gov

The API v2 adapter searches interventional studies with a last-update window.
It captures sponsors, collaborators, conditions, intervention aliases, phases,
status, enrollment, partial-date precision, locations, outcomes, and results
availability. Tracked changes create an auditable history instead of a second
trial.

### Crossref

Crossref is enrichment-only. For DOI-bearing records it can fill missing
container, publisher, author, funder, license, date, and relationship metadata.
It records each enriched field and never replaces populated PubMed or other
higher-quality source fields merely because Crossref differs.

### RSS and Atom

Feeds are explicitly listed in `config/sources.yml` with their attribution and
terms links. The generic adapter stores only feed-provided metadata and a
bounded plain-text description; it never fetches article pages. Each feed fails
independently, and malformed feeds produce warnings without erasing other data.

## Deduplication

Exact DOI, PMID, NCT, source identifiers, and documented
preprint-to-journal DOI relationships are authoritative. Title matching is a
fallback only: it requires a long near-identical normalized title, matching
first-author identity, and compatible dates. Matching RNA vocabulary or a
surname/initial alone is never sufficient. Merge decisions retain a reason and
confidence, while all source IDs, URLs, provenance, and relationships survive.

## Classification

`config/categories.yml` defines weighted regular expressions, synonyms, field
weights, and negative patterns. Title and intervention matches outweigh
abstract or feed-description matches. Every displayed label retains confidence,
the literal matched phrases, fields, and method; source-provided sponsor and
affiliation classifications are marked separately as source metadata.

## Relevance score

The reproducible 0–100 score is the sum of exported components for direct
therapeutic relevance, modality specificity, delivery, translational stage,
human relevance, clinical changes, regulatory importance, methods, recency, and
independent-source corroboration. Excluded records remain stored but are capped
at 15. This is a prioritization score, **not a measure of scientific quality**;
press-release claims receive no evidence-quality bonus.
