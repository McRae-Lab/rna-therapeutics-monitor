"""PubMed discovery and normalization through NCBI E-utilities."""

from __future__ import annotations

import hashlib
import os
import xml.etree.ElementTree as ET
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import HttpUrl

from rna_monitor.config import PubMedSettings, QueryGroup, SourceQuery, WatchedPerson
from rna_monitor.dates import ParsedDate, parse_date_parts
from rna_monitor.http import HttpClient
from rna_monitor.identifiers import canonical_id, normalize_doi
from rna_monitor.models import Author, Organization, ProvenanceEntry, Record
from rna_monitor.people import match_watched_people
from rna_monitor.sources.base import RetrievalWindow, SourceResult


def _text(element: ET.Element | None) -> str | None:
    if element is None:
        return None
    value = " ".join("".join(element.itertext()).split())
    return value or None


def _date_from_element(element: ET.Element | None) -> ParsedDate | None:
    if element is None:
        return None
    return parse_date_parts(
        _text(element.find("Year")),
        _text(element.find("Month")),
        _text(element.find("Day")),
    )


def _first_date(*values: ParsedDate | None) -> ParsedDate | None:
    present = [value for value in values if value is not None]
    return min(present, key=lambda value: value.value) if present else None


def build_pubmed_query(
    source_query: SourceQuery,
    groups: dict[str, QueryGroup],
    window: RetrievalWindow,
    people: list[WatchedPerson] | None = None,
) -> str:
    """Combine editable PubMed syntax with inclusive publication/modification windows."""

    discovery = " OR ".join(f"({query})" for query in source_query.queries)
    # Configured negative terms are applied after normalization so excluded
    # candidates remain stored with an auditable reason.
    since = window.since.strftime("%Y/%m/%d")
    until = window.until.strftime("%Y/%m/%d")
    dates = f'("{since}"[PDAT] : "{until}"[PDAT] OR "{since}"[MDAT] : "{until}"[MDAT])'
    topical = f"({discovery})"
    author_queries = " OR ".join(
        f"({person.pubmed_query})" for person in people or [] if person.active
    )
    scope = f"({topical} OR ({author_queries}))" if author_queries else topical
    return f"{scope} AND {dates}"


def _parse_authors(article: ET.Element) -> list[Author]:
    authors: list[Author] = []
    for node in article.findall("./MedlineCitation/Article/AuthorList/Author"):
        collective = _text(node.find("CollectiveName"))
        family = _text(node.find("LastName"))
        given = _text(node.find("ForeName"))
        initials = _text(node.find("Initials"))
        name = collective or " ".join(part for part in (given, family) if part)
        if not name:
            continue
        affiliations = [
            value
            for item in node.findall("./AffiliationInfo/Affiliation")
            if (value := _text(item))
        ]
        identifier = node.find("./Identifier[@Source='ORCID']")
        authors.append(
            Author(
                name=name,
                given_name=given,
                family_name=family,
                initials=initials,
                orcid=_text(identifier),
                affiliations=affiliations,
            )
        )
    return authors


def _parse_abstract(article: ET.Element) -> str | None:
    sections: list[str] = []
    for node in article.findall("./MedlineCitation/Article/Abstract/AbstractText"):
        value = _text(node)
        if not value:
            continue
        label = node.attrib.get("Label")
        sections.append(f"{label}: {value}" if label else value)
    return "\n".join(sections) or None


def _parse_article(article: ET.Element, retrieved_at: datetime) -> Record:
    citation = article.find("./MedlineCitation")
    if citation is None:
        raise ValueError("PubMedArticle is missing MedlineCitation")
    article_node = citation.find("./Article")
    if article_node is None:
        raise ValueError("MedlineCitation is missing Article")
    pmid = _text(citation.find("./PMID"))
    if not pmid:
        raise ValueError("PubMedArticle is missing PMID")
    title = _text(article_node.find("./ArticleTitle"))
    if not title:
        raise ValueError(f"PubMed record {pmid} is missing a title")

    article_ids = {
        node.attrib.get("IdType", ""): value
        for node in article.findall("./PubmedData/ArticleIdList/ArticleId")
        if (value := _text(node))
    }
    doi = normalize_doi(article_ids.get("doi"))
    authors = _parse_authors(article)
    journal_issue = article_node.find("./Journal/JournalIssue")
    print_date = _date_from_element(
        journal_issue.find("./PubDate") if journal_issue is not None else None
    )
    electronic_date = _date_from_element(article_node.find("./ArticleDate"))
    if electronic_date is None:
        electronic_date = _date_from_element(
            article.find("./PubmedData/History/PubMedPubDate[@PubStatus='epublish']")
        )
    created_date = _date_from_element(citation.find("./DateCreated"))
    revised_date = _date_from_element(citation.find("./DateRevised"))
    first = _first_date(print_date, electronic_date, created_date)
    journal = _text(article_node.find("./Journal/Title"))
    abstract = _parse_abstract(article)
    publication_types = [
        value
        for node in article_node.findall("./PublicationTypeList/PublicationType")
        if (value := _text(node))
    ]
    mesh_terms = [
        value
        for node in citation.findall("./MeshHeadingList/MeshHeading/DescriptorName")
        if (value := _text(node))
    ]
    keywords = [
        value for node in citation.findall("./KeywordList/Keyword") if (value := _text(node))
    ]
    affiliation_values = list(
        dict.fromkeys(affiliation for author in authors for affiliation in author.affiliations)
    )
    url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    raw = ET.tostring(article, encoding="utf-8")
    date_precision = {
        name: parsed.precision
        for name, parsed in (
            ("published_date", print_date),
            ("electronic_published_date", electronic_date),
            ("first_date", first),
            ("updated_date", revised_date),
        )
        if parsed is not None
    }
    return Record(
        id=canonical_id(
            doi=doi,
            pmid=pmid,
            source="pubmed",
            source_id=pmid,
            title=title,
            first_author=authors[0].name if authors else "",
            year=str(first.value.year) if first else "",
        ),
        record_type="publication",
        source_types=["pubmed"],
        source_ids={"pubmed": pmid},
        title=title,
        abstract=abstract,
        authors=authors,
        organizations=[
            Organization(name=value, organization_type="affiliation")
            for value in affiliation_values
        ],
        journal_or_source=journal,
        doi=doi,
        pmid=pmid,
        url=HttpUrl(url),
        alternate_urls=[HttpUrl(f"https://doi.org/{doi}")] if doi else [],
        first_date=first.value if first else None,
        published_date=print_date.value if print_date else None,
        electronic_published_date=electronic_date.value if electronic_date else None,
        updated_date=revised_date.value if revised_date else None,
        retrieved_at=retrieved_at,
        institutions=affiliation_values,
        keywords=keywords,
        mesh_terms=mesh_terms,
        publication_types=publication_types,
        date_precision=date_precision,
        evidence_level="peer-reviewed publication",
        provenance=[
            ProvenanceEntry(
                source="pubmed",
                source_id=pmid,
                url=HttpUrl(url),
                retrieved_at=retrieved_at,
                fields=[
                    "title",
                    "abstract",
                    "authors",
                    "journal_or_source",
                    "publication_types",
                    "mesh_terms",
                    "keywords",
                ],
                raw_sha256=hashlib.sha256(raw).hexdigest(),
            )
        ],
        field_sources={
            field: "pubmed"
            for field in (
                "title",
                "abstract",
                "authors",
                "journal_or_source",
                "doi",
                "published_date",
            )
        },
    )


def parse_pubmed_xml(xml_text: str, retrieved_at: datetime | None = None) -> list[Record]:
    """Parse an EFetch PubMed XML response into canonical records."""

    timestamp = retrieved_at or datetime.now(UTC)
    root = ET.fromstring(xml_text)
    return [_parse_article(node, timestamp) for node in root.findall("./PubmedArticle")]


class PubMedAdapter:
    """Incremental PubMed adapter using ESearch followed by EFetch."""

    name = "pubmed"

    def __init__(
        self,
        settings: PubMedSettings,
        source_query: SourceQuery,
        groups: dict[str, QueryGroup],
        http: HttpClient,
        people: list[WatchedPerson] | None = None,
    ) -> None:
        self.settings = settings
        self.source_query = source_query
        self.groups = groups
        self.http = http
        self.people = people or []

    def _common_params(self) -> dict[str, str]:
        return {
            "tool": self.settings.tool,
            "email": os.getenv(
                self.settings.contact_email_env,
                self.settings.default_contact_email,
            ),
        }

    def search_ids(self, window: RetrievalWindow, limit: int | None = None) -> list[str]:
        """Return PMIDs, splitting windows that exceed NCBI's 9,999-result ceiling."""

        ids = self._search_window_ids(window, limit)
        return list(dict.fromkeys(ids))[:limit] if limit is not None else list(dict.fromkeys(ids))

    def _search_window_ids(
        self,
        window: RetrievalWindow,
        limit: int | None,
    ) -> list[str]:
        query = build_pubmed_query(self.source_query, self.groups, window, self.people)
        ids: list[str] = []
        retstart = 0
        batch_size = min(self.settings.batch_size, limit or self.settings.batch_size)
        while limit is None or len(ids) < limit:
            params: dict[str, Any] = {
                **self._common_params(),
                "db": "pubmed",
                "retmode": "json",
                "retstart": retstart,
                "retmax": batch_size,
                "term": query,
            }
            self.http.pace("ncbi", self.settings.requests_per_second)
            payload = self.http.get(
                str(self.settings.base_url) + "esearch.fcgi", params=params
            ).json()
            result = payload.get("esearchresult", {})
            page = [str(value) for value in result.get("idlist", [])]
            total = int(result.get("count", len(ids)))
            if total > 9_999 and (limit is None or limit > 9_999):
                if window.since >= window.until:
                    raise ValueError(
                        "PubMed returned more than 9,999 matches for a single day; "
                        "narrow the configured query"
                    )
                midpoint = window.since + (window.until - window.since) // 2
                left = self._search_window_ids(
                    RetrievalWindow(window.since, midpoint),
                    limit,
                )
                remaining = None if limit is None else max(0, limit - len(left))
                right = self._search_window_ids(
                    RetrievalWindow(midpoint + timedelta(days=1), window.until),
                    remaining,
                )
                return [*left, *right]
            ids.extend(page)
            retstart += len(page)
            if not page or retstart >= total:
                break
        return ids[:limit] if limit is not None else ids

    def fetch(self, window: RetrievalWindow, limit: int | None = None) -> SourceResult:
        """Discover and fetch normalized PubMed records."""

        ids = self.search_ids(window, limit)
        records: list[Record] = []
        for batch in _batched(ids, self.settings.batch_size):
            params = {
                **self._common_params(),
                "db": "pubmed",
                "retmode": "xml",
                "id": ",".join(batch),
            }
            self.http.pace("ncbi", self.settings.requests_per_second)
            response = self.http.get(str(self.settings.base_url) + "efetch.fcgi", params=params)
            parsed = parse_pubmed_xml(response.text)
            for record in parsed:
                record.watched_people = match_watched_people(record, self.people)
            records.extend(parsed)
        return SourceResult(source=self.name, records=records, raw_count=len(ids))


def _batched(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]
