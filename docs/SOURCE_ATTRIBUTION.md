# Source attribution and responsible use

This project uses documented public APIs and explicitly configured RSS/Atom
feeds. It does not scrape an article page when an API or feed exists. Source
metadata remains subject to the provider's current terms, rate limits, robot
rules, attribution guidance, and caching recommendations.

## PubMed / NCBI

- Interface: NCBI E-utilities ESearch and EFetch.
- Identification: every request supplies the configured `tool` and contact
  email; set `RNA_MONITOR_CONTACT_EMAIL` to a monitored address.
- Default rate: at most three requests per second without an NCBI API key.
- Attribution: records link to the authoritative PubMed page and preserve PMID.
- Guidance: <https://www.ncbi.nlm.nih.gov/books/NBK25497/>

## bioRxiv and medRxiv

- Interface: official date-interval API with cursor pagination.
- Attribution: records identify the server, DOI, version, posting date, and
  authoritative preprint URL.
- Content: only API metadata/abstracts are normalized; no manuscript PDF or
  article HTML is copied.
- API: <https://api.biorxiv.org/>

## ClinicalTrials.gov

- Interface: ClinicalTrials.gov API v2.
- Attribution: records retain and link the NCT identifier.
- Interpretation: a registration is not proof of efficacy; status and results
  availability are displayed separately.
- API: <https://clinicaltrials.gov/data-api/api>

## Crossref

- Interface: Crossref REST API, used only for DOI reconciliation and missing
  metadata.
- Identification: requests use the configured contact email for the polite
  pool.
- Attribution: Crossref is included in provenance for each field it supplies.
- Etiquette: <https://www.crossref.org/documentation/retrieve-metadata/rest-api/rest-api-metadata-retrieval/>

## RSS and Atom

Each feed entry in `config/sources.yml` must include a source name, URL,
source type, attribution, and terms URL. The adapter stores only feed-provided
metadata and a bounded short description, and links to the original item. Feed
owners may change or withdraw endpoints; maintainers should recheck terms
before expanding use.

The initial feed set includes FDA and EMA regulatory news, the Nature
Biotechnology table of contents, and Fierce Biotech headlines. These configured
feeds exercise regulatory, journal, and biotechnology-news source types; the
same adapter supports documented company, conference, and society feeds when
added under their current terms.

## Society roster

`config/people.yml` records the Society for RNA Therapeutics roster snapshot
date and source-audited identities. ORCIDs identify people but do not guarantee
that a profile exposes a complete works list, so PubMed fallbacks are retained.
The monitor labels a person only after exact ORCID or strict bibliographic
identity checks.
