"""HTTP retry and freshness-cache behavior."""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from rna_monitor.config import HttpSettings
from rna_monitor.http import HttpClient


def _settings() -> HttpSettings:
    return HttpSettings(
        max_attempts=3,
        backoff_min_seconds=0,
        backoff_max_seconds=1,
        cache_ttl_hours=24,
    )


def test_temporary_api_error_is_retried() -> None:
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            503 if attempts == 1 else 200,
            json={"ok": True},
            request=request,
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    http = HttpClient(_settings(), "rna-monitor-tests", client=client, sleeper=lambda _: None)

    assert http.get("https://example.test/records").json() == {"ok": True}
    assert attempts == 2


def test_fresh_cache_reused_and_stale_cache_refetched(tmp_path: Path) -> None:
    now = datetime(2026, 7, 27, 12, tzinfo=UTC)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"call": calls}, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    current = [now]
    http = HttpClient(
        _settings(),
        "rna-monitor-tests",
        client=client,
        cache_dir=tmp_path,
        clock=lambda: current[0],
    )

    assert http.get("https://example.test/records", params={"page": 1}).json() == {"call": 1}
    assert http.get("https://example.test/records", params={"page": 1}).json() == {"call": 1}
    current[0] += timedelta(hours=25)
    assert http.get("https://example.test/records", params={"page": 1}).json() == {"call": 2}
    assert calls == 2
