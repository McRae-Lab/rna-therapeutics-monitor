"""Tests for strict repository configuration loading."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from rna_monitor.config import QueryGroup, load_config

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_repository_configuration_loads() -> None:
    config = load_config(REPOSITORY_ROOT / "config")

    assert config.sources.pubmed.requests_per_second == 3
    assert set(config.sources.preprints.servers) == {"biorxiv", "medrxiv"}
    assert "modalities_high_precision" in config.queries.groups
    assert len(config.people.people) == 36
    assert config.people.people[2].orcid == "0000-0001-9586-2508"
    assert config.categories.field_weights["title"] > config.categories.field_weights["abstract"]


def test_bare_rna_query_is_rejected() -> None:
    with pytest.raises(ValidationError, match="bare token"):
        QueryGroup(
            description="Too broad",
            precision="broad",
            terms=["RNA"],
        )


def test_unknown_query_group_is_rejected(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "config"
    for name in ("sources.yml", "categories.yml", "people.yml"):
        (tmp_path / name).write_text((source / name).read_text(encoding="utf-8"), encoding="utf-8")
    queries = yaml.safe_load((source / "queries.yml").read_text(encoding="utf-8"))
    queries["source_queries"]["rss"]["include_groups"].append("missing")
    (tmp_path / "queries.yml").write_text(yaml.safe_dump(queries), encoding="utf-8")

    with pytest.raises(ValidationError, match="unknown query groups"):
        load_config(tmp_path)


def test_invalid_regex_is_rejected(tmp_path: Path) -> None:
    source = REPOSITORY_ROOT / "config"
    for name in ("sources.yml", "queries.yml", "people.yml"):
        (tmp_path / name).write_text((source / name).read_text(encoding="utf-8"), encoding="utf-8")
    categories = yaml.safe_load((source / "categories.yml").read_text(encoding="utf-8"))
    categories["categories"]["modalities"][0]["patterns"] = ["("]
    (tmp_path / "categories.yml").write_text(yaml.safe_dump(categories), encoding="utf-8")

    with pytest.raises(ValidationError, match="invalid regular expression"):
        load_config(tmp_path)
