# RNA Therapeutics Monitor

Production-oriented monitoring of recent RNA-therapeutics publications,
preprints, clinical trials, regulatory developments, and selected RSS sources.
The pipeline normalizes, deduplicates, classifies, scores, and exports records
for a static GitHub Pages website.

> Work in progress: checkpoints 1-2 establish the typed canonical schema,
> project quality gates, and strictly validated editable configuration.

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
