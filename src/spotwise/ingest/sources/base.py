"""Shared types for price sources, plus an HTTP GET with retry and backoff."""

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)

# Status codes worth retrying: rate limiting and temporary server problems.
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass(frozen=True)
class PriceSlot:
    """One normalised price: UTC start, slot length in minutes, €/MWh excluding VAT."""

    ts_start: datetime
    resolution_minutes: int
    price_eur_mwh: Decimal


class SourceError(Exception):
    """A source failed after retries, or returned data we can't use."""


class Source(Protocol):
    """A place we can fetch day-ahead prices from."""

    name: str

    def fetch(self, start: datetime, end: datetime) -> list[PriceSlot]:
        """Return all price slots that start in [start, end) (both UTC)."""
        ...


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    source_name: str,
    params: Mapping[str, str] | None = None,
    max_retries: int = 3,
    base_delay_s: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
) -> httpx.Response:
    """GET with exponential backoff (1 s, 2 s, 4 s) on network errors, 429 and 5xx.

    Other responses (including 4xx) are returned for the caller to handle. Log and error
    messages never include the URL, because it may contain an API token.
    """
    problem = ""
    for attempt in range(max_retries + 1):
        try:
            response = client.get(url, params=params)
        except httpx.TransportError as exc:
            problem = f"network error ({type(exc).__name__})"
        else:
            if response.status_code not in RETRYABLE_STATUS:
                return response
            problem = f"HTTP {response.status_code}"

        if attempt < max_retries:
            delay = base_delay_s * 2**attempt
            logger.warning(
                "%s request failed: %s; retry %d/%d in %.0f s",
                source_name,
                problem,
                attempt + 1,
                max_retries,
                delay,
            )
            sleep(delay)

    logger.error("%s request failed after %d retries: %s", source_name, max_retries, problem)
    raise SourceError(f"{source_name}: request failed after {max_retries} retries: {problem}")
