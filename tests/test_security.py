"""Public-artifact credential scanning."""

from pathlib import Path

import pytest

from rna_monitor.security import scan_public_site


def test_public_site_secret_scan_accepts_variable_names(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        "<p>Set OPENAI_API_KEY only in a repository secret.</p>",
        encoding="utf-8",
    )

    assert scan_public_site(tmp_path) == {"files_scanned": 1, "findings": 0}


def test_public_site_secret_scan_rejects_likely_key(tmp_path: Path) -> None:
    fake_key = "sk-" + "proj-" + "abcdefghijklmnopqrstuvwxyz123456"
    (tmp_path / "data.json").write_text(
        f'{{"OPENAI_API_KEY":"{fake_key}"}}',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="credential-like"):
        scan_public_site(tmp_path)
