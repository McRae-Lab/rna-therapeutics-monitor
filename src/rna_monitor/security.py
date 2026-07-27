"""Fail-closed checks for credential-like material in public site artifacts."""

from __future__ import annotations

import re
from pathlib import Path

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "OpenAI-style API key": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{20,}\b"),
    "GitHub token": re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}\b"),
    "GitHub fine-grained token": re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    "AWS access key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "assigned API key": re.compile(
        r"(?im)\b(?:OPENAI_API_KEY|API_KEY|ACCESS_TOKEN|CLIENT_SECRET)\s*[:=]\s*"
        r"[\"']?(?!\s|false\b|none\b|null\b)[A-Za-z0-9_./+=-]{16,}"
    ),
}


def scan_public_site(site_dir: Path) -> dict[str, int]:
    """Inspect every reasonably sized public file and reject likely credentials."""

    findings: list[str] = []
    files_scanned = 0
    for path in sorted(item for item in site_dir.rglob("*") if item.is_file()):
        if path.stat().st_size > 20_000_000:
            raise ValueError(f"public file is unexpectedly large and was not scanned: {path}")
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        files_scanned += 1
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                findings.append(f"{path.relative_to(site_dir)}: {label}")
    if findings:
        raise ValueError(f"credential-like strings found in public site: {sorted(findings)}")
    return {"files_scanned": files_scanned, "findings": 0}
