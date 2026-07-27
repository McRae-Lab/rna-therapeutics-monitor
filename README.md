# RNA Therapeutics Monitor

Production-oriented monitoring of recent RNA-therapeutics publications,
preprints, clinical trials, regulatory developments, and selected RSS sources.
The pipeline normalizes, deduplicates, classifies, scores, and exports records
for a static GitHub Pages website.

> Work in progress: checkpoint 1 establishes the typed canonical schema and
> project quality gates.

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

