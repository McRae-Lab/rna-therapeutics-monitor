"""Controlled vocabularies used by normalized records."""

from typing import Final

MODALITIES: Final[tuple[str, ...]] = (
    "mRNA",
    "saRNA",
    "circRNA",
    "siRNA",
    "ASO",
    "aptamer",
    "miRNA",
    "RNA editing",
    "CRISPR RNA",
    "ribozyme",
    "RNA nanostructure",
    "other",
)

DEVELOPMENT_STAGES: Final[tuple[str, ...]] = (
    "basic research",
    "platform development",
    "preclinical in vitro",
    "preclinical animal",
    "IND-enabling",
    "Phase 1",
    "Phase 1/2",
    "Phase 2",
    "Phase 2/3",
    "Phase 3",
    "approved",
    "post-marketing",
    "discontinued",
    "unknown",
)

EVIDENCE_LEVELS: Final[tuple[str, ...]] = (
    "news or announcement",
    "conference abstract",
    "preprint",
    "peer-reviewed publication",
    "patent",
    "trial registration",
    "trial results",
    "regulatory document",
)

RECORD_TYPES: Final[tuple[str, ...]] = (
    "publication",
    "preprint",
    "clinical_trial",
    "regulatory",
    "news",
    "conference",
    "society",
    "other",
)

SOURCE_TYPES: Final[tuple[str, ...]] = (
    "pubmed",
    "biorxiv",
    "medrxiv",
    "clinicaltrials.gov",
    "crossref",
    "rss",
)
