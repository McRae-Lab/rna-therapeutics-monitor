# Contributing

Thank you for improving the RNA Therapeutics Monitor.

## Before opening a change

Open an issue for a new source, schema change, scoring change, or broad query
expansion. Document the source's official interface, attribution, terms, rate
limits, and expected effect on false positives.

Never commit credentials, `.env` files, private API responses, patient data,
licensed full text, or realistic secret examples. GitHub Pages is public.

## Development workflow

Use Python 3.12 and the exact `requirements.lock` dependencies. Keep adapters
isolated, normalized models strict, deterministic behavior explainable, and LLM
use optional.

Every behavior change should include saved public/non-sensitive fixtures and
offline tests. Run:

```bash
ruff format --check .
ruff check .
mypy src
pytest
python scripts/build_fixture_site.py --output /tmp/rna-monitor-site/data
python -m rna_monitor --site-dir /tmp/rna-monitor-site validate
node --check site/assets/app.js
node --check site/assets/methodology.js
```

Use focused commits. Describe query, classification, scoring, or merge-rule
tradeoffs in the pull request. Do not weaken identity matching merely to raise
recall; add explicit aliases and affiliation evidence instead.

## Adding sources and feeds

Prefer a documented API or RSS/Atom feed over HTML scraping. Add source
configuration, attribution documentation, bounded retry/cache behavior,
fixtures, parser tests, temporary-failure tests, and state-preservation tests.
An unavailable source must not delete previously stored data.
