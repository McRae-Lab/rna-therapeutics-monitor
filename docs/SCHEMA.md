# Canonical record schema

Schema implementation: `src/rna_monitor/models.py`.

The canonical store is UTF-8 JSON Lines at `data/records.jsonl`, one validated
`Record` per line. Pydantic models reject undocumented fields. Dates retain
source precision in `date_precision`; timezone-aware timestamps use UTC.

## Identity and source fields

`id` is stable and uses normalized DOI, PMID, NCT identifier, source-native
identifier, or a deterministic SHA-256 fallback in that priority order.
`record_type`, `source_types`, `source_ids`, `url`, `alternate_urls`, and
`provenance` preserve discovery and merge context. `doi`, `pmid`, and `nct_id`
are separately queryable. `watched_people` contains only SRT identities meeting
the configured strict match policy.

## Bibliographic and descriptive fields

`title`, `abstract`, `description`, `authors`, `organizations`,
`journal_or_source`, `publisher`, `funders`, `license_url`, `relations`, and
source-specific publication fields preserve metadata without fabricating
missing values. `field_sources` records fill-only enrichment attribution where
practical.

## Dates and updates

`first_date` is the earliest public date known. `published_date`,
`electronic_published_date`, and `updated_date` retain source meanings.
`retrieved_at` is the UTC observation timestamp. `version` and
`change_history` preserve substantive revisions. Trial changes include status,
enrollment, phase, dates, interventions, and outcomes.

## Classifications

Controlled arrays include `modalities`, `delivery_systems`, `disease_areas`,
`therapeutic_targets`, `development_stages`, `species`, `methods`, `topics`,
`companies`, and `institutions`. `classification_evidence` retains label,
confidence, literal matches, fields, and method. `excluded` records remain in
the canonical/public full dataset with `exclusion_reasons`; they are omitted
from the quick `latest.json` view.

## Ranking and enrichment

`relevance_score` ranges from 0 to 100 and is explained by
`score_components`. It is not scientific quality. Optional LLM results use
`summary`, `key_findings`, `numerical_results`, `uncertainty_notes`, and
`enrichment_metadata`. Deterministic fields remain authoritative fallback data.

## Source-specific extensions

`trial` contains normalized ClinicalTrials.gov sponsor, conditions,
interventions, phase, status, enrollment, dates, locations, countries,
outcomes, and result availability. `preprint` contains server, version,
category, published DOI, and publication status.

## Public projection

`site/data/records.min.json` retains the validated schema but removes internal
raw-response SHA-256 values. The other generated artifacts contain a recent
subset, aggregate statistics, facet counts, update metadata, and the scoring
method. Exports use stable key ordering and record ordering to avoid meaningless
diffs.
