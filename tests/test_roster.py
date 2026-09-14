"""Offline membership import tests using synthetic, non-personal workbooks."""

from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

import pytest
import yaml

from rna_monitor.config import PeopleConfig, WatchedPerson
from rna_monitor.roster import HEADERS, main, merge_members, read_members

CHECKED = date(2026, 9, 14)


def workbook(path: Path, rows: list[list[str]], shared: bool = False) -> None:
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    root = ET.Element("worksheet", xmlns=ns)
    data = ET.SubElement(root, "sheetData")
    strings = ET.Element("sst", xmlns=ns)
    index = 0
    for number, values in enumerate(rows, 1):
        row = ET.SubElement(data, "row", r=str(number))
        for column, value in enumerate(values):
            cell = ET.SubElement(
                row, "c", r=f"{chr(65 + column)}{number}", t="s" if shared else "inlineStr"
            )
            if shared:
                ET.SubElement(cell, "v").text = str(index)
                ET.SubElement(ET.SubElement(strings, "si"), "t").text = value
                index += 1
            else:
                ET.SubElement(ET.SubElement(cell, "is"), "t").text = value
    with ZipFile(path, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", ET.tostring(root))
        if shared:
            archive.writestr("xl/sharedStrings.xml", ET.tostring(strings))


def config() -> PeopleConfig:
    return PeopleConfig(
        schema_version=1,
        roster_checked_at="2026-08-18",
        people=[
            WatchedPerson(
                id="srt-0007",
                display_name="Alex M. Example",
                role="board",
                organization="Example University",
                aliases=["Alex Example", "Alex M Example"],
                orcid="0000-0001-5662-8110",
                pubmed_query="Example AM[Author]",
                affiliation_terms=["Example"],
                require_affiliation=True,
            )
        ],
    )


def member(first: str, last: str, organization: str = "Example University") -> dict[str, str]:
    return dict(zip(HEADERS, [first, last, organization], strict=True))


@pytest.mark.parametrize("shared", [False, True])
def test_xlsx_allowlists_fields_and_handles_unicode(tmp_path: Path, shared: bool) -> None:
    path = tmp_path / "members.xlsx"
    workbook(
        path,
        [
            [*HEADERS, "Email", "Country"],
            ["  Zoë  ", "Example", "Example University", "private@example.test", "US"],
        ],
        shared,
    )
    members = read_members(path)
    assert members == [member("Zoë", "Example")]
    assert "private@example.test" not in repr(members)


@pytest.mark.parametrize(
    "rows",
    [
        [["Name", "Email"]],
        [list(HEADERS), ["Alex", "", "Institution"]],
        [list(HEADERS)],
        [[*HEADERS, "First Name"]],
    ],
)
def test_invalid_workbook_fails_closed(tmp_path: Path, rows: list[list[str]]) -> None:
    path = tmp_path / "members.xlsx"
    workbook(path, rows)
    with pytest.raises(ValueError):
        read_members(path)


def test_preserves_audited_identities_and_flags_institution_change() -> None:
    original = config()
    merged, report = merge_members(original, [member("Alex", "Example", "New University")], CHECKED)
    assert merged.people == original.people
    assert report["institution_or_status_review"]
    assert report["added"] == []


def test_additive_import_is_idempotent_and_preserves_absent_members() -> None:
    original = config()
    rows = [member("Jamie", "Newperson"), member("Jamie", "Newperson")]
    merged, report = merge_members(original, rows, CHECKED)
    assert merged.people[0] == original.people[0]
    person = merged.people[1]
    assert person.id == "srt-0008"
    assert person.orcid is None and person.require_affiliation
    assert person.pubmed_query == '"newperson j"[Author] AND "example university"[Affiliation]'
    assert report["absent_retained"] == ["srt-0007"]
    assert report["duplicate_rows"] == ["Jamie Newperson"]
    again, second_report = merge_members(merged, rows, CHECKED)
    assert again == merged
    assert second_report["added"] == []


def test_conflicting_duplicate_and_similar_identity_require_review() -> None:
    with pytest.raises(ValueError, match="Conflicting institutions"):
        merge_members(
            config(),
            [member("Jamie", "Newperson"), member("Jamie", "Newperson", "Other University")],
            CHECKED,
        )
    with pytest.raises(ValueError, match="Review unmatched name"):
        merge_members(config(), [member("A", "Example")], CHECKED)


def test_unrelated_members_can_share_surname() -> None:
    merged, _ = merge_members(
        config(), [member("Jamie", "Newperson"), member("Zoe", "Newperson")], CHECKED
    )
    assert len(merged.people) == 3


def test_apply_preserves_comments_and_never_copies_contact_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "members.xlsx"
    workbook(
        path,
        [
            [*HEADERS, "Email"],
            ["Jamie", "Newperson", "Example University", "private@example.test"],
        ],
    )
    people = tmp_path / "people.yml"
    original = "# Preserve verified identities\n" + yaml.safe_dump(config().model_dump())
    people.write_text(original)
    output = tmp_path / "output"
    args = [
        "roster",
        str(path),
        "--people",
        str(people),
        "--output-dir",
        str(output),
        "--checked-at",
        CHECKED.isoformat(),
    ]
    monkeypatch.setattr("sys.argv", args)
    assert main() == 0
    assert people.read_text() == original
    monkeypatch.setattr("sys.argv", [*args, "--apply"])
    assert main() == 0
    applied = people.read_text()
    assert applied.startswith("# Preserve verified identities\n")
    assert len(PeopleConfig.model_validate(yaml.safe_load(applied)).people) == 2
    assert main() == 0
    assert people.read_text() == applied
    for file in output.iterdir():
        assert "private@example.test" not in file.read_text()
    backups = list(output.glob("people.before-*.yml"))
    assert len(backups) == 1
    assert backups[0].read_text() == original
