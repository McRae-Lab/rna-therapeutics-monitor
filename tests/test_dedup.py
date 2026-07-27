"""Difficult deterministic duplicate and false-positive cases."""

from datetime import UTC, date, datetime

from pydantic import HttpUrl

from rna_monitor.dedup import deduplicate, match_reason
from rna_monitor.models import Author, PreprintDetails, ProvenanceEntry, Record

NOW = datetime(2026, 7, 27, tzinfo=UTC)


def _record(
    *,
    identifier: str,
    title: str,
    author: str = "Ana Rivera",
    source: str = "rss",
    doi: str | None = None,
    pmid: str | None = None,
    first_date: date = date(2026, 7, 20),
    abstract: str | None = None,
    preprint: PreprintDetails | None = None,
) -> Record:
    return Record(
        id=identifier,
        record_type="preprint" if preprint else "publication" if source == "pubmed" else "news",
        source_types=[source],
        source_ids={source: identifier},
        title=title,
        abstract=abstract,
        authors=[Author(name=author)],
        doi=doi,
        pmid=pmid,
        url=HttpUrl(f"https://example.org/{identifier.replace(':', '-')}"),
        first_date=first_date,
        published_date=first_date,
        retrieved_at=NOW,
        evidence_level="preprint"
        if preprint
        else "peer-reviewed publication"
        if source == "pubmed"
        else "news or announcement",
        preprint=preprint,
        provenance=[
            ProvenanceEntry(
                source=source,
                source_id=identifier,
                url=HttpUrl(f"https://example.org/{identifier.replace(':', '-')}"),
                retrieved_at=NOW,
            )
        ],
    )


def test_exact_doi_deduplication_prefers_pubmed_metadata() -> None:
    news = _record(
        identifier="rss:1",
        title="Company says its mRNA platform is transformative",
        source="rss",
        doi="10.1000/example",
        abstract=None,
    )
    publication = _record(
        identifier="doi:10.1000/example",
        title="An mRNA platform for therapeutic delivery",
        source="pubmed",
        doi="10.1000/example",
        pmid="40123456",
        abstract="Peer-reviewed abstract.",
    )

    result = deduplicate([news, publication])

    assert len(result.records) == 1
    assert result.records[0].title == publication.title
    assert result.records[0].abstract == "Peer-reviewed abstract."
    assert set(result.records[0].source_types) == {"rss", "pubmed"}
    assert result.decisions[0].reason == "exact DOI"


def test_preprint_to_journal_relationship_uses_journal_doi() -> None:
    preprint = _record(
        identifier="doi:10.1101/preprint",
        title="A targeted siRNA therapeutic for liver disease",
        source="biorxiv",
        doi="10.1101/preprint",
        preprint=PreprintDetails(
            server="biorxiv",
            version=2,
            published_doi="10.1000/journal",
            publication_status="published",
        ),
    )
    journal = _record(
        identifier="doi:10.1000/journal",
        title="A targeted siRNA therapeutic for liver disease",
        source="pubmed",
        doi="10.1000/journal",
        pmid="40222222",
    )

    result = deduplicate([preprint, journal])

    assert len(result.records) == 1
    assert result.records[0].id == "doi:10.1000/journal"
    assert result.records[0].relations["has-preprint"] == ["10.1101/preprint"]
    assert result.decisions[0].reason == "documented preprint-to-journal DOI"


def test_conservative_fuzzy_match_requires_strong_author_identity() -> None:
    left = _record(
        identifier="rss:left",
        title="Selective lipid nanoparticles enable extrahepatic delivery of mRNA therapeutics",
        author="Michelle L. Hastings",
    )
    true_duplicate = _record(
        identifier="rss:right",
        title="Selective lipid nanoparticles enable extra-hepatic delivery of mRNA therapeutics",
        author="Michelle Hastings",
    )
    wrong_person = true_duplicate.model_copy(
        update={
            "id": "rss:wrong",
            "authors": [Author(name="Meredith Hastings")],
        }
    )

    assert match_reason(left, true_duplicate) is not None
    assert match_reason(left, wrong_person) is None


def test_similar_rna_terms_never_merge_unrelated_titles() -> None:
    delivery = _record(
        identifier="rss:delivery",
        title="Selective lipid nanoparticles enable extrahepatic delivery of mRNA therapeutics",
        author="Tianlun Yu",
    )
    physics = _record(
        identifier="rss:physics",
        title="Emergent 3D Fermiology and Magnetism in an Intercalated Van der Waals System",
        author="Tianlun Yu",
    )

    assert match_reason(delivery, physics) is None
    assert len(deduplicate([delivery, physics]).records) == 2
