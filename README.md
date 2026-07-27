# RNA Therapeutics Monitor

An auditable, key-free-by-default monitor of recent RNA-therapeutics
publications, preprints, clinical trials, regulatory developments, and selected
RSS/Atom sources. Python retrieves and normalizes the data; a static HTML, CSS,
and vanilla JavaScript interface publishes it on GitHub Pages.

> **Public-site warning:** GitHub Pages and everything under `site/` are public.
> Never put credentials, private source responses, patient information, or
> confidential material in generated files. Every build recursively scans
> `site/` for credential-like strings and fails if any are found.

Screenshot: _placeholder—add a current screenshot after first deployment._

Live site: `https://mcrae-lab.github.io/rna-therapeutics-monitor/`

## What it does

- Retrieves PubMed, bioRxiv/medRxiv, ClinicalTrials.gov, and configured feeds.
- Uses Crossref only to reconcile and fill missing DOI metadata.
- Watches a separately configured Society for RNA Therapeutics author roster.
- Retains normalized, typed records and source/change provenance.
- Conservatively deduplicates identifiers, preprint relationships, and
  near-identical title/author pairs.
- Assigns auditable rule-based classifications and a reproducible 0–100
  relevance priority score.
- Exports deterministic JSON for a searchable, filterable static website.
- Updates daily and deploys through least-privilege GitHub Actions workflows.

The relevance score prioritizes likely usefulness to the monitor. It is **not**
a measure of scientific quality, validity, or endorsement.

## Architecture

```text
public APIs / RSS
        |
isolated source adapters -> canonical Pydantic records -> Crossref fill-only enrichment
        |                               |
        +-------------------------------+
                        |
         deduplicate -> classify -> score -> JSONL + source state
                                            |
                                  deterministic public JSON
                                            |
                                  static GitHub Pages site
```

Source failures are isolated. Existing records and that source's last-successful
boundary remain intact if one provider is temporarily unavailable.

## Supported sources

| Source | Role | Interface |
| --- | --- | --- |
| PubMed | Primary discovery | NCBI ESearch and EFetch |
| bioRxiv / medRxiv | Primary discovery | Official date-interval API with cursor pagination |
| ClinicalTrials.gov | Primary discovery and trial-change tracking | API v2 |
| Crossref | DOI reconciliation and fill-only metadata | REST API |
| RSS / Atom | Regulatory, society, journal, company, and news metadata | Configured feed URLs |

The generic feed adapter stores only feed-supplied metadata and a bounded short
description. It never downloads or copies full articles. See
[source attribution](docs/SOURCE_ATTRIBUTION.md) for provider-specific usage
notes.

## SRT author watchlist

`config/people.yml` contains 20 audited SRT board, member, and staff identities,
including ORCIDs where confirmed. PubMed discovery combines topical queries with
the configured author queries. This matters for profiles such as Pieter R.
Cullis (`0000-0001-9586-2508`), where a valid ORCID may expose no works.

Record attribution requires exact ORCID or conservative bibliographic identity.
Initials or surname overlap alone is insufficient; ambiguous people require
matching full given name and configured affiliation. Regression tests explicitly
reject Michelle/Meredith Hastings and Timothy/Tianlun Yu collisions.

## Local setup

Python 3.12 is required.

```bash
git clone https://github.com/McRae-Lab/rna-therapeutics-monitor.git
cd rna-therapeutics-monitor
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install --disable-pip-version-check -r requirements.lock
python -m pip install --no-deps -e .
cp .env.example .env
```

Set `RNA_MONITOR_CONTACT_EMAIL` to a real maintainer address before routine NCBI
or Crossref use. The committed `.env.example` contains no secret. The
application does not automatically load `.env`; export values in your shell or
use your preferred local environment loader.

## CLI

Global path options precede the command. Typical commands are:

```bash
python -m rna_monitor update --days 14 --no-llm
python -m rna_monitor update --source pubmed --since 2026-07-01 --dry-run
python -m rna_monitor update --source preprints --limit 20
python -m rna_monitor classify
python -m rna_monitor enrich
python -m rna_monitor export
python -m rna_monitor build
python -m rna_monitor validate
```

Use `--verbose` for structured diagnostic logs. Genuine failures return a
nonzero status. `--dry-run` performs retrieval and processing without updating
canonical records or source state. The default update path never calls an LLM.

The canonical dataset is `data/records.jsonl`; successful per-source boundaries
are in `data/state.json`. Initial updates use the requested lookback. Later
updates recheck a seven-day overlap by default to catch late indexing,
corrections, and revisions.

## Configuration

- `config/queries.yml`: high-precision, broad, and exclusion term groups plus
  source-specific syntax. The bare token `RNA` is rejected.
- `config/people.yml`: SRT identities, ORCIDs, aliases, PubMed fallback queries,
  and affiliation checks.
- `config/sources.yml`: endpoints, timeouts, bounded retries, cache lifetime,
  overlap windows, contact settings, feeds, attribution, and terms links.
- `config/categories.yml`: controlled labels, weighted regular expressions,
  field weights, and negative patterns.

Validate every configuration file:

```bash
python -m rna_monitor validate
```

### Edit discovery queries

Keep named modalities and therapeutic context in high-precision groups. Put
wider signals in `broad_discovery`; do not add the bare token `RNA`. PubMed
syntax belongs in `source_queries.pubmed.queries`; interval-based preprint
results are filtered locally with the shared groups. Exclusions set an auditable
reason instead of deleting the stored candidate.

### Add an RSS or Atom feed

Add an item beneath `rss.feeds` in `config/sources.yml`:

```yaml
- name: Example journal
  url: "https://example.org/feed.xml"
  source_type: journal
  attribution: Example publisher
  terms_url: "https://example.org/terms"
```

Confirm that the publisher documents the feed, permits the intended use, and
does not already offer a more appropriate API. Then add a saved fixture and an
offline adapter test.

### Add a source adapter

1. Implement a class in `src/rna_monitor/sources/` with `name` and
   `fetch(RetrievalWindow, limit) -> SourceResult`.
2. Normalize only documented source fields into `Record` and attach provenance.
3. Add strict configuration models and register the adapter in
   `build_default_pipeline`.
4. Add saved, non-sensitive fixtures for parsing, pagination, missing fields,
   retry/failure behavior, and source-specific updates.
5. Document attribution, rate limits, and terms; run all quality gates.

No adapter may silently fabricate records or replace higher-quality metadata.

## Canonical data and exports

The schema is documented in [docs/SCHEMA.md](docs/SCHEMA.md). Stable IDs use, in
order, normalized DOI, PMID, NCT ID, source-native ID, or a deterministic
SHA-256 fallback. DOI prefixes are stripped and values lowercased.

`python -m rna_monitor build` writes and validates:

```text
site/data/records.min.json
site/data/latest.json
site/data/statistics.json
site/data/facets.json
site/data/last_updated.json
site/data/methodology.json
```

Exports are deterministically sorted and serialized. Public records retain
classifications, score components, source links, change history, and provenance
while omitting raw hashes. Large raw responses and private caches are ignored by
Git. Source text is rendered with DOM text nodes, and outbound URLs are limited
to HTTP(S), preventing source-controlled HTML injection.

## Deduplication, classification, and scoring

Exact DOI, PMID, NCT, source identifiers, and documented preprint-to-journal
relationships are authoritative. Fuzzy title matching is only a fallback and
requires a long near-identical normalized title, strong first-author identity,
and compatible dates. All merge reasons are retained.

Classification searches titles, abstracts/descriptions, interventions, MeSH
terms, keywords, and source metadata. Title and intervention hits weigh more
than abstract hits. Each assigned label retains confidence, matched phrases,
fields, and method. Negative rules reduce common nontherapeutic false positives.

The exported score breakdown covers therapeutic directness, modality,
delivery, translation, human evidence, clinical changes, regulation, methods,
recency, and independent-source corroboration. Press-release rhetoric adds no
evidence-quality bonus.

## Static website

`site/` contains only plain HTML, CSS, JavaScript, and JSON. It provides
normalized token search, date/facet/score filters, preset views, deterministic
sorting, progressive loading, expandable provenance and rationale, and
browser-only CSV/JSON downloads. All links and fetches are relative, so the site
works at `/rna-therapeutics-monitor/` rather than requiring a domain root.

For a local preview:

```bash
python -m http.server 8000 --directory site
```

Then open `http://localhost:8000/`.

## Automated updates and deployment

- `tests.yml` runs formatting, linting, strict typing, offline tests,
  configuration validation, a fixture site build, and JavaScript syntax checks
  on pushes and pull requests. It receives no secrets.
- `update.yml` runs daily at 11:17 UTC and by manual dispatch. Concurrency
  prevents simultaneous writers. It restores caches, runs an incremental
  no-key update, validates, and commits only changed data/site artifacts using
  `contents: write`.
- `pages.yml` deploys only `site/` with the official GitHub Pages actions and
  `contents: read`, `pages: write`, and `id-token: write`.

If there are no data changes, the updater creates no commit.

### Deploy to GitHub Pages

1. Create `McRae-Lab/rna-therapeutics-monitor` and push `main`.
2. In **Settings → Pages**, choose **GitHub Actions** as the source.
3. Run **Deploy GitHub Pages** once, or push a `site/` change.
4. Set repository variable `RNA_MONITOR_CONTACT_EMAIL` to a monitored address.

The resulting project URL is
`https://mcrae-lab.github.io/rna-therapeutics-monitor/`.

## Optional LLM enrichment

Deterministic mode is the default and requires no API credentials.

Supported opt-in modes:

1. **Deterministic:** rule classification and source abstracts only.
2. **Local:** use an OpenAI-compatible endpoint on the maintainer's computer,
   then commit only validated generated fields.
3. **Self-hosted runner:** use a private runner and local-compatible endpoint;
   the public site receives static output only.
4. **Hosted API:** set repository secret `OPENAI_API_KEY`, repository variable
   `OPENAI_MODEL`, and explicitly set `ENABLE_LLM_ENRICHMENT=true`.

Examples:

```bash
python -m rna_monitor enrich --provider none
python -m rna_monitor enrich \
  --provider local \
  --model YOUR_LOCAL_MODEL \
  --base-url http://127.0.0.1:8000/v1
```

The structured prompt receives only public source metadata and abstracts. The
result is Pydantic-validated and cached from model, prompt version, normalized
title, abstract/description, and relevant trial fields. Malformed output is
logged without the response body and leaves deterministic data intact.
Credentials, environment dumps, and full API responses are never logged.

The scheduled workflow does not enable enrichment merely because a secret
exists. Credentialed steps are not present in the pull-request workflow.

## Testing

All tests are offline and use saved fixtures:

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

Coverage includes date/DOI normalization, primary-source parsing and pagination,
missing abstracts, revisions and journal relationships, exact and conservative
deduplication, false-positive author identities, metadata conflicts,
classification negatives, reproducible scores, malformed feeds, transient HTTP
failures, stale caches, deterministic exports, HTML safety, credential scans,
and disabled/malformed/cached LLM behavior.

## Troubleshooting

- **All requested sources failed:** rerun one source with `--verbose`; existing
  records are preserved. Check endpoint availability and your network before
  changing source state.
- **NCBI contact warning:** export a real `RNA_MONITOR_CONTACT_EMAIL`.
- **No PubMed results:** inspect the exact query groups and date range; the SRT
  watchlist uses bibliographic fallbacks even when ORCID exposes no works.
- **Feed warning:** malformed or unavailable feeds are isolated. Confirm the
  documented feed URL and terms before editing it.
- **Build rejects a secret:** inspect only the reported public file, remove the
  credential, rotate it if genuine, and rebuild. Do not weaken the scanner to
  publish a key.
- **Pages loads HTML but no results:** confirm all `site/data/*.json` files were
  deployed and that URLs remain repository-relative.
- **Hosted enrichment fails:** it is opt-in; verify the explicit variable,
  secret, model name, and structured-output support. Deterministic publication
  remains available.

## Limitations and attribution

Indexing and feeds can lag. Rule sets can miss new product aliases and can still
misclassify records. Automated matching does not establish author identity with
the certainty of an identity authority. Feed claims are not independently
verified. Inclusion does not represent endorsement by the maintainers or the
Society for RNA Therapeutics.

Use of upstream metadata remains subject to each source's current policies,
terms, attribution requirements, and rate guidance. Maintainers must review
those requirements when adding or changing a source.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Contributions should include offline
fixtures, tests, documentation, and a focused commit. Never contribute
credentials, private responses, copyrighted full-text articles, or generated
site files containing sensitive data.

Licensed under the [MIT License](LICENSE).
