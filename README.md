# RNA Therapeutics Monitor

Production-oriented monitoring of recent RNA-therapeutics publications,
preprints, clinical trials, regulatory developments, and selected RSS sources.
The pipeline normalizes, deduplicates, classifies, scores, and exports records
for a static GitHub Pages website.

> Work in progress: checkpoints 1-17 establish the full application, including
> optional disabled-by-default structured enrichment.

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

## Run an update

```bash
python -m rna_monitor update --days 14 --no-llm
python -m rna_monitor update --source pubmed --since 2026-07-01 --dry-run
python -m rna_monitor classify
python -m rna_monitor export
python -m rna_monitor build
python -m rna_monitor validate
```

The canonical dataset is `data/records.jsonl`; successful source boundaries are
stored in `data/state.json`. Each source rechecks a seven-day overlap by
default. A failed source does not advance its state or remove old records, and
unchanged content fingerprints prevent retrieval timestamps from causing
meaningless data diffs. Logs are structured JSON and omit bodies, secrets, and
environment dumps.

The export command writes:

```text
site/data/records.min.json
site/data/latest.json
site/data/statistics.json
site/data/facets.json
site/data/last_updated.json
site/data/methodology.json
```

Exports are sorted and serialized deterministically. Public records retain
classifications, score components, source links, change history, and provenance
but omit raw-response hashes. The browser must render all source-controlled
strings with text nodes rather than HTML insertion.

## Website

`site/` is plain HTML, CSS, and modern vanilla JavaScript. It supports full-text
token search, presets, date and categorical filters, a minimum score, sorting,
progressive loading, expandable evidence, and in-browser CSV/JSON downloads.
It first loads `latest.json`, then upgrades to the complete dataset. All assets
and fetches use repository-relative paths, so the site works at a project URL
such as `https://USERNAME.github.io/rna-therapeutics-monitor/`.

Screenshot: _add a production screenshot after the first Pages deployment._

Live site: `https://USERNAME.github.io/rna-therapeutics-monitor/`

## Testing

```bash
ruff format --check .
ruff check .
mypy src
pytest
python scripts/build_fixture_site.py --output /tmp/rna-monitor-fixture-site/data
```

The push and pull-request workflow uses Python 3.12, exact versions from
`requirements.lock`, no network-dependent tests, no secrets, strict type and
style checks, configuration validation, a fixture-backed site build, and
JavaScript syntax checks.

## Scheduled updates

`.github/workflows/update.yml` runs daily at 11:17 UTC and can also be started
manually. Concurrency prevents overlapping writers. It restores only HTTP and
enrichment caches, runs the incremental pipeline with LLM use explicitly off,
runs targeted tests, builds and validates the site, and commits only changed
canonical/state/public data. The workflow has `contents: write` and no other
permission; absent optional secrets do not affect it.

## Deploy to GitHub Pages

1. Create the GitHub repository and push this `main` branch.
2. In **Settings → Pages**, set the source to **GitHub Actions**.
3. Run **Deploy GitHub Pages** manually once, or push a change under `site/`.

The deployment workflow uses the official `configure-pages`,
`upload-pages-artifact`, and `deploy-pages` actions. It deploys only `site/`,
uses the protected `github-pages` environment, and has exactly `contents: read`,
`pages: write`, and `id-token: write`. A successful daily update also triggers a
deployment; failed updates do not.

## Optional LLM enrichment

Deterministic mode is the default and calls no model:

```bash
python -m rna_monitor update --no-llm
```

Supported opt-in modes are:

1. **Deterministic:** rule labels and source abstracts only.
2. **Local enrichment:** run an OpenAI-compatible model on the maintainer's
   computer, then commit only validated generated fields:
   `python -m rna_monitor enrich --provider local --model MODEL --base-url http://127.0.0.1:8000/v1`.
3. **Self-hosted runner:** use the same local-compatible command on a private
   Actions runner.
4. **Hosted API:** set repository secret `OPENAI_API_KEY`, repository variable
   `OPENAI_MODEL`, and explicitly set `ENABLE_LLM_ENRICHMENT=true`.

Prompts receive only public metadata and abstracts. Results are JSON-schema
validated and cached under `.cache/enrichment` using the model, prompt version,
title, abstract/description, and trial fields. Malformed output leaves the
deterministic record intact. Provider, model, prompt version, timestamp, input
hash, and validation status are exported; credentials and raw responses are
never logged or published. The mere presence of a secret never enables calls.
