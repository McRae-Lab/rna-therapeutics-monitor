"""Import the SRT membership-form XLSX export without copying contact fields."""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import yaml

from rna_monitor.config import PeopleConfig, WatchedPerson

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
HEADERS = ("First Name", "Last Name", "Institution or organization")


def normalize(value: str) -> str:
    """Compare complete names, allowing punctuation and accent differences."""
    value = unicodedata.normalize("NFKD", value).casefold()
    value = "".join(c for c in value if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", value).split())


def read_members(path: Path) -> list[dict[str, str]]:
    """Read the single membership sheet, supporting shared and inline strings.

    Only the three allowlisted fields are retained. This intentionally supports
    the membership form export rather than arbitrary Excel workbooks.
    """
    with ZipFile(path) as archive:
        if sum(info.file_size for info in archive.infolist()) > 20_000_000:
            raise ValueError("Workbook exceeds the 20 MB uncompressed limit")
        sheets = [
            name
            for name in archive.namelist()
            if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name)
        ]
        if len(sheets) != 1:
            raise ValueError("Expected one worksheet in the membership form export")
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root.findall("m:si", NS)]
        root = ET.fromstring(archive.read(sheets[0]))
        rows = root.findall("m:sheetData/m:row", NS)
        if not rows:
            raise ValueError("Workbook is empty")

        def cell_text(cell: ET.Element) -> str:
            if cell.find("m:f", NS) is not None:
                raise ValueError("Formula cells are not supported in member fields")
            value = cell.findtext("m:v", default="", namespaces=NS)
            if cell.get("t") == "s":
                value = shared[int(value)]
            elif cell.get("t") == "inlineStr":
                inline = cell.find("m:is", NS)
                value = "".join(inline.itertext()) if inline is not None else ""
            return " ".join(value.split())

        columns: dict[str, str] = {}
        for cell in rows[0]:
            value = cell_text(cell)
            if value in HEADERS:
                if value in columns.values():
                    raise ValueError(f"Duplicate column: {value}")
                columns[re.sub(r"\d", "", cell.get("r", ""))] = value
        if set(columns.values()) != set(HEADERS):
            raise ValueError("Expected First Name, Last Name, Institution or organization columns")
        members = []
        for row in rows[1:]:
            member = {}
            for cell in row:
                column = re.sub(r"\d", "", cell.get("r", ""))
                if column in columns:
                    member[columns[column]] = cell_text(cell)
            if not any(member.values()):
                continue
            if not all(member.get(field) for field in HEADERS):
                raise ValueError(f"Missing name or institution in worksheet row {row.get('r')}")
            members.append(member)
        if not members:
            raise ValueError("No member rows found")
        return members


def merge_members(
    config: PeopleConfig, members: list[dict[str, str]], checked_at: date
) -> tuple[PeopleConfig, dict[str, object]]:
    """Add new identities; leave audited entries and absent members unchanged."""
    people = list(config.people)
    matched, added, review, duplicates = [], [], [], []
    seen: dict[str, str] = {}
    matched_ids: set[str] = set()
    next_id = max((int(p.id[4:]) for p in people), default=0) + 1
    for member in members:
        first, last, organization = (member[field] for field in HEADERS)
        name = f"{first} {last}"
        key = normalize(name)
        if key in seen:
            if normalize(seen[key]) != normalize(organization):
                raise ValueError(f"Conflicting institutions for duplicate member: {name}")
            duplicates.append(name)
            continue
        seen[key] = organization
        matches = [
            person
            for person in people
            if key in {normalize(alias) for alias in [person.display_name, *person.aliases]}
        ]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous existing identity: {name}")
        if matches:
            person = matches[0]
            matched_ids.add(person.id)
            matched.append({"name": name, "id": person.id})
            if normalize(organization) != normalize(person.organization or ""):
                review.append(
                    {
                        "id": person.id,
                        "name": name,
                        "institution_from_form": organization,
                        "existing_institution": person.organization,
                    }
                )
            if not person.active:
                review.append({"id": person.id, "name": name, "reason": "inactive entry retained"})
            continue
        # A similar name needs review, not an automatic new identity or merge.
        similar = [
            person.display_name
            for person in people
            if any(
                normalize(alias).split()[-1:] == normalize(last).split()[-1:]
                and normalize(alias)[:1] == normalize(first)[:1]
                for alias in [person.display_name, *person.aliases]
            )
        ]
        if similar:
            raise ValueError(f"Review unmatched name {name}; existing surname matches: {similar}")
        if not normalize(first) or not normalize(last) or not normalize(organization):
            raise ValueError(f"Name and institution must contain searchable text: {name}")
        # Literal quoted fields prevent form text from becoming query operators.
        author = normalize(last) + " " + "".join(part[0] for part in normalize(first).split())
        affiliation = normalize(organization)
        person = WatchedPerson(
            id=f"srt-{next_id:04d}",
            display_name=name,
            role="member",
            organization=organization,
            aliases=[name],
            pubmed_query=f'"{author}"[Author] AND "{affiliation}"[Affiliation]',
            affiliation_terms=[organization],
            require_affiliation=True,
            note="Member form import; no verified ORCID supplied. Strict affiliation matching.",
        )
        next_id += 1
        people.append(person)
        matched_ids.add(person.id)
        added.append({"name": name, "id": person.id})
    merged = PeopleConfig.model_validate(
        {
            **config.model_dump(),
            "roster_checked_at": checked_at.isoformat(),
            "people": people,
        }
    )
    return merged, {
        "input_rows": len(members),
        "matched": matched,
        "added": added,
        "institution_or_status_review": review,
        "duplicate_rows": duplicates,
        "absent_retained": [p.id for p in config.people if p.id not in matched_ids],
        "total_people": len(people),
    }


def main() -> int:
    """Write a private candidate and report, optionally applying the additive update."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workbook", type=Path)
    parser.add_argument("--people", type=Path, default=Path("config/people.yml"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/private/roster-import"))
    parser.add_argument("--checked-at", type=date.fromisoformat, default=date.today())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    original = args.people.read_text(encoding="utf-8")
    config = PeopleConfig.model_validate(yaml.safe_load(original))
    merged, report = merge_members(config, read_members(args.workbook), args.checked_at)
    # Preserve all existing YAML comments, spelling, field choices and formatting.
    updated = re.sub(
        r"^roster_checked_at:.*$",
        f'roster_checked_at: "{merged.roster_checked_at}"',
        original,
        flags=re.M,
    )
    if merged.people[len(config.people) :]:
        additions = [
            p.model_dump(exclude_defaults=True) for p in merged.people[len(config.people) :]
        ]
        block = yaml.safe_dump(additions, allow_unicode=True, sort_keys=False)
        document = yaml.compose(updated)
        if not isinstance(document, yaml.MappingNode):
            raise ValueError("Expected a YAML mapping")
        sequence = next(value for key, value in document.value if key.value == "people")
        if not isinstance(sequence, yaml.SequenceNode) or sequence.flow_style:
            raise ValueError("Expected people as a block-style YAML list")
        indent = " " * sequence.start_mark.column
        block = "\n".join(indent + line for line in block.splitlines()) + "\n"
        position = sequence.end_mark.index
        updated = updated[:position].rstrip() + "\n\n" + block + updated[position:]
    if PeopleConfig.model_validate(yaml.safe_load(updated)) != merged:
        raise ValueError("Candidate did not preserve the expected configuration")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / "people.candidate.yml").write_text(updated, encoding="utf-8")
    (args.output_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    if args.apply and updated != original:
        # Keep a content-addressed backup before atomically replacing the config.
        import hashlib

        digest = hashlib.sha256(original.encode()).hexdigest()[:12]
        (args.output_dir / f"people.before-{digest}.yml").write_text(original, encoding="utf-8")
        temporary = args.people.with_suffix(".yml.tmp")
        temporary.write_text(updated, encoding="utf-8")
        temporary.replace(args.people)
    print(
        json.dumps(
            {
                "total_people": len(merged.people),
                "added": len(merged.people) - len(config.people),
                "applied": args.apply,
                "report": str(args.output_dir / "report.json"),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
