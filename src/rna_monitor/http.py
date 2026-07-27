"""Bounded, identified, retrying HTTP access for public APIs."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
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
    ) -> None:
        self.settings = settings
        self._sleeper = sleeper
        self._owns_client = client is None
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

    def get(self, url: str, *, params: dict[str, Any] | None = None) -> httpx.Response:
        """GET one URL, retrying only transport and documented transient failures."""

        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_attempts + 1):
            try:
                response = self.client.get(url, params=params)
                if response.status_code not in TRANSIENT_STATUS_CODES:
                    response.raise_for_status()
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
