"""Optional, cached, structured LLM enrichment with deterministic fallback."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import httpx
from pydantic import Field

from rna_monitor.models import (
    ClassificationEvidence,
    EnrichmentMetadata,
    NumericalResult,
    Record,
    StrictModel,
)
from rna_monitor.vocab import DEVELOPMENT_STAGES, MODALITIES

LOGGER = logging.getLogger(__name__)
PROMPT_VERSION = "rna-monitor-enrichment-v1"
SYSTEM_PROMPT = """
You extract structured facts from public RNA-therapeutics metadata.
Distinguish reported results from interpretation and preprints from peer-reviewed work.
Never infer clinical efficacy from preclinical findings.
Retain quantitative units and context.
Return unknown or an empty list instead of inventing missing information.
Do not claim novelty based solely on an abstract.
Identify uncertainty explicitly.
Return only JSON matching the supplied schema.
""".strip()


class EnrichmentPayload(StrictModel):
    """Model-generated fields before audit metadata is attached."""

    summary: str | None = None
    key_findings: list[str] = Field(default_factory=list)
    modalities: list[str] = Field(default_factory=list)
    delivery_systems: list[str] = Field(default_factory=list)
    disease_areas: list[str] = Field(default_factory=list)
    development_stages: list[str] = Field(default_factory=list)
    therapeutic_targets: list[str] = Field(default_factory=list)
    species: list[str] = Field(default_factory=list)
    numerical_results: list[NumericalResult] = Field(default_factory=list)
    uncertainty_notes: list[str] = Field(default_factory=list)


class EnrichmentResult(EnrichmentPayload):
    """Validated enrichment plus reproducibility metadata."""

    provider: str
    model: str
    prompt_version: str
    enrichment_timestamp: datetime
    input_hash: str
    validation_status: str = "valid"


class Summarizer(Protocol):
    """Common interface for disabled, hosted, and local enrichment."""

    def enrich(self, record: Record) -> EnrichmentResult:
        """Return validated structured enrichment."""


def public_llm_input(record: Record) -> dict[str, Any]:
    """Select only public metadata and abstracts allowed in an LLM request."""

    return {
        "record_type": record.record_type,
        "title": record.title,
        "abstract": record.abstract,
        "description": record.description,
        "authors": [author.name for author in record.authors],
        "journal_or_source": record.journal_or_source,
        "publication_types": record.publication_types,
        "mesh_terms": record.mesh_terms,
        "keywords": record.keywords,
        "evidence_level": record.evidence_level,
        "trial": record.trial.model_dump(mode="json") if record.trial else None,
        "preprint": record.preprint.model_dump(mode="json") if record.preprint else None,
    }


def enrichment_input_hash(record: Record, model: str, prompt_version: str) -> str:
    """Hash every input that can change a model result."""

    material = {
        "model": model,
        "prompt_version": prompt_version,
        "record": public_llm_input(record),
    }
    encoded = json.dumps(material, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


class NoOpSummarizer:
    """Explicit deterministic-mode implementation that makes no model call."""

    def enrich(self, record: Record) -> EnrichmentResult:
        """Return an empty, auditable result."""

        return EnrichmentResult(
            provider="none",
            model="none",
            prompt_version=PROMPT_VERSION,
            enrichment_timestamp=datetime.now(UTC),
            input_hash=enrichment_input_hash(record, "none", PROMPT_VERSION),
            validation_status="not-run",
        )


class OpenAICompatibleSummarizer:
    """OpenAI-compatible chat endpoint with structured validation and disk cache."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        base_url: str,
        cache_dir: Path,
        api_key: str | None = None,
        prompt_version: str = PROMPT_VERSION,
        structured_response: bool = True,
        client: httpx.Client | None = None,
        max_attempts: int = 3,
    ) -> None:
        self.provider = provider
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.cache_dir = cache_dir
        self.api_key = api_key
        self.prompt_version = prompt_version
        self.structured_response = structured_response
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(60, connect=10),
            headers={"User-Agent": "rna-therapeutics-monitor/0.1"},
        )
        self.max_attempts = max_attempts

    def _cache_path(self, input_hash: str) -> Path:
        return self.cache_dir / f"{input_hash}.json"

    def _load_cache(self, input_hash: str) -> EnrichmentResult | None:
        path = self._cache_path(input_hash)
        if not path.is_file():
            return None
        try:
            result = EnrichmentResult.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception:
            LOGGER.warning("invalid_enrichment_cache", extra={"input_hash": input_hash})
            return None
        return result if result.input_hash == input_hash else None

    def _save_cache(self, result: EnrichmentResult) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(result.input_hash)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def _request(self, body: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                response = self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=body,
                )
                response.raise_for_status()
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("LLM response root is not an object")
                return payload
            except (httpx.HTTPError, ValueError) as exc:
                error = exc
                if attempt < self.max_attempts:
                    time.sleep(min(2 ** (attempt - 1), 4))
        raise RuntimeError("LLM request failed after bounded retries") from error

    def enrich(self, record: Record) -> EnrichmentResult:
        """Return a cached result or call and validate the compatible endpoint."""

        input_hash = enrichment_input_hash(record, self.model, self.prompt_version)
        if cached := self._load_cache(input_hash):
            return cached
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        public_llm_input(record),
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                },
            ],
        }
        if self.structured_response:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "rna_therapeutics_enrichment",
                    "strict": True,
                    "schema": EnrichmentPayload.model_json_schema(),
                },
            }
        response = self._request(body)
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ValueError("LLM response has no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str):
            raise ValueError("LLM response content is not text")
        payload = EnrichmentPayload.model_validate_json(content)
        result = EnrichmentResult(
            **payload.model_dump(),
            provider=self.provider,
            model=self.model,
            prompt_version=self.prompt_version,
            enrichment_timestamp=datetime.now(UTC),
            input_hash=input_hash,
            validation_status="valid",
        )
        self._save_cache(result)
        return result


class OpenAISummarizer(OpenAICompatibleSummarizer):
    """Hosted OpenAI implementation; the key is supplied only at build time."""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        cache_dir: Path,
        client: httpx.Client | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for explicitly enabled hosted enrichment")
        super().__init__(
            provider="openai",
            model=model,
            base_url="https://api.openai.com/v1",
            cache_dir=cache_dir,
            api_key=api_key,
            structured_response=True,
            client=client,
        )


class LocalOpenAICompatibleSummarizer(OpenAICompatibleSummarizer):
    """Local OpenAI-compatible endpoint; an API key is optional."""

    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        cache_dir: Path,
        api_key: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        super().__init__(
            provider="local-openai-compatible",
            model=model,
            base_url=base_url,
            cache_dir=cache_dir,
            api_key=api_key,
            structured_response=False,
            client=client,
        )


def build_summarizer(
    *,
    enabled: bool,
    provider: str = "none",
    model: str = "",
    base_url: str = "",
    cache_dir: Path = Path(".cache/enrichment"),
) -> Summarizer:
    """Construct a summarizer only after explicit enablement."""

    if not enabled or provider == "none":
        return NoOpSummarizer()
    if not model:
        raise ValueError("an explicit model name is required for LLM enrichment")
    if provider == "openai":
        return OpenAISummarizer(
            model=model,
            api_key=os.getenv("OPENAI_API_KEY", ""),
            cache_dir=cache_dir,
        )
    if provider == "local":
        if not base_url:
            raise ValueError("a local OpenAI-compatible base URL is required")
        return LocalOpenAICompatibleSummarizer(
            model=model,
            base_url=base_url,
            cache_dir=cache_dir,
        )
    raise ValueError(f"unsupported LLM provider: {provider}")


def apply_enrichment(record: Record, result: EnrichmentResult) -> Record:
    """Apply only validated fields while retaining deterministic labels."""

    if result.provider == "none":
        return record
    categories = {
        "modalities": [value for value in result.modalities if value in MODALITIES],
        "delivery_systems": result.delivery_systems,
        "disease_areas": result.disease_areas,
        "development_stages": [
            value for value in result.development_stages if value in DEVELOPMENT_STAGES
        ],
        "therapeutic_targets": result.therapeutic_targets,
        "species": result.species,
    }
    evidence = {
        category: list(record.classification_evidence.get(category, []))
        for category in record.classification_evidence
    }
    updates: dict[str, Any] = {}
    for field, values in categories.items():
        combined = list(dict.fromkeys([*getattr(record, field), *values]))
        updates[field] = combined
        for value in values:
            if not any(item.label == value for item in evidence.get(field, [])):
                evidence.setdefault(field, []).append(
                    ClassificationEvidence(
                        label=value,
                        confidence=0.6,
                        fields=["llm_enrichment"],
                        method=f"llm:{result.provider}",
                    )
                )
    updates.update(
        {
            "summary": result.summary or record.summary,
            "key_findings": result.key_findings or record.key_findings,
            "numerical_results": result.numerical_results or record.numerical_results,
            "uncertainty_notes": result.uncertainty_notes,
            "classification_evidence": evidence,
            "classification_method": f"{record.classification_method}+llm",
            "enrichment_metadata": EnrichmentMetadata(
                provider=result.provider,
                model=result.model,
                prompt_version=result.prompt_version,
                enrichment_timestamp=result.enrichment_timestamp,
                input_hash=result.input_hash,
                validation_status=result.validation_status,
            ),
        }
    )
    return record.model_copy(update=updates)


def enrich_records(
    records: list[Record],
    summarizer: Summarizer,
) -> tuple[list[Record], list[str]]:
    """Enrich independently; malformed output leaves deterministic records intact."""

    output: list[Record] = []
    failures: list[str] = []
    for record in records:
        try:
            output.append(apply_enrichment(record, summarizer.enrich(record)))
        except Exception as exc:
            LOGGER.error(
                "llm_enrichment_failed",
                extra={"record_id": record.id, "error_type": type(exc).__name__},
            )
            failures.append(f"{record.id}: {type(exc).__name__}")
            output.append(record)
    return output, failures
