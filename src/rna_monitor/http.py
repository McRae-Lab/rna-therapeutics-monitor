"""Bounded, identified, retrying HTTP access for public APIs."""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from rna_monitor.config import HttpSettings

LOGGER = logging.getLogger(__name__)
TRANSIENT_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


class HttpRequestError(RuntimeError):
    """A bounded HTTP request failed."""


class HttpClient:
    """Small synchronous HTTP wrapper with bounded exponential backoff and jitter."""

    def __init__(
        self,
        settings: HttpSettings,
        user_agent: str,
        *,
        client: httpx.Client | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        cache_dir: Path | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.settings = settings
        self._sleeper = sleeper
        self._owns_client = client is None
        self.cache_dir = cache_dir
        self._clock = clock
        self._monotonic = monotonic
        self._last_request: dict[str, float] = {}
        timeout = httpx.Timeout(
            connect=settings.connect_timeout_seconds,
            read=settings.read_timeout_seconds,
            write=settings.read_timeout_seconds,
            pool=settings.connect_timeout_seconds,
        )
        self.client = client or httpx.Client(
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept": "application/json, application/xml"},
            follow_redirects=True,
        )

    def pace(self, service: str, requests_per_second: float) -> None:
        """Enforce a conservative per-process interval for a named service."""

        minimum_interval = 1.0 / requests_per_second
        now = self._monotonic()
        last = self._last_request.get(service)
        if last is not None and now - last < minimum_interval:
            self._sleeper(minimum_interval - (now - last))
        self._last_request[service] = self._monotonic()

    def _cache_path(self, url: str, params: dict[str, Any] | None) -> Path | None:
        if self.cache_dir is None or self.settings.cache_ttl_hours <= 0:
            return None
        key = json.dumps(
            {"url": url, "params": sorted((params or {}).items())},
            ensure_ascii=True,
            separators=(",", ":"),
            default=str,
        )
        return self.cache_dir / f"{hashlib.sha256(key.encode()).hexdigest()}.json"

    def _read_cache(
        self,
        path: Path | None,
        url: str,
        params: dict[str, Any] | None,
    ) -> httpx.Response | None:
        if path is None or not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            stored_at = datetime.fromisoformat(payload["stored_at"])
            if stored_at.tzinfo is None:
                return None
            age = self._clock() - stored_at
            if age < timedelta(0) or age > timedelta(hours=self.settings.cache_ttl_hours):
                return None
            request = httpx.Request("GET", url, params=params)
            return httpx.Response(
                int(payload["status_code"]),
                content=bytes.fromhex(payload["content_hex"]),
                headers=payload.get("headers", {}),
                request=request,
                extensions={"rna_monitor_cache": True},
            )
        except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
            LOGGER.warning("http_cache_entry_ignored", extra={"cache_file": path.name})
            return None

    def _write_cache(self, path: Path | None, response: httpx.Response) -> None:
        if path is None or response.status_code != 200 or len(response.content) > 10_000_000:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        headers = {
            name: value
            for name in ("content-type", "etag", "last-modified")
            if (value := response.headers.get(name))
        }
        payload = {
            "stored_at": self._clock().isoformat(),
            "status_code": response.status_code,
            "headers": headers,
            "content_hex": response.content.hex(),
        }
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
        temporary.replace(path)

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        """GET one URL, retrying only transport and documented transient failures."""

        cache_path = self._cache_path(url, params)
        cached = self._read_cache(cache_path, url, params)
        if cached is not None:
            return cached
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_attempts + 1):
            try:
                response = self.client.get(url, params=params)
                if response.status_code not in TRANSIENT_STATUS_CODES:
                    response.raise_for_status()
                    self._write_cache(cache_path, response)
                    return response
                last_error = HttpRequestError(
                    f"transient HTTP {response.status_code} from {response.request.url}"
                )
                retry_after = response.headers.get("Retry-After")
            except httpx.TransportError as exc:
                last_error = exc
                retry_after = None
            if attempt < self.settings.max_attempts:
                delay = min(
                    self.settings.backoff_max_seconds,
                    self.settings.backoff_min_seconds * (2 ** (attempt - 1)),
                )
                if retry_after and retry_after.isdigit():
                    delay = min(self.settings.backoff_max_seconds, float(retry_after))
                delay += random.uniform(0, max(0.1, delay * 0.25))
                LOGGER.warning(
                    "transient_http_retry",
                    extra={"attempt": attempt, "delay_seconds": round(delay, 2), "url": url},
                )
                self._sleeper(delay)
        raise HttpRequestError(f"request failed after bounded retries: {url}") from last_error

    def close(self) -> None:
        """Close the underlying client when this wrapper created it."""

        if self._owns_client:
            self.client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
