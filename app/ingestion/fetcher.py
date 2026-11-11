"""Polite, allow-listed fetcher for pre-approved Lex.uz URLs.

- Only `SourceSpec.url` values are ever requested (no arbitrary URLs).
- HTTPS only; every redirect target's host is re-checked against the allow-list.
- Timeout, bounded retries with exponential backoff, minimum interval between
  requests, response size cap.
- Conditional request headers are sent when a previous response supplied
  ETag/Last-Modified. (On 2026-11-11 Lex.uz sent neither, so change detection
  relies on the parsed-content checksum.)
"""

from __future__ import annotations

import gzip
import hashlib
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.config import Settings
from app.core.logging import get_logger

log = get_logger(__name__)

_last_request_at = 0.0
_interval_lock = threading.Lock()


class FetchError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass
class FetchResult:
    url: str
    final_url: str
    status_code: int
    body: bytes | None  # None when 304 Not Modified
    headers: dict[str, str]
    fetched_at: datetime

    @property
    def not_modified(self) -> bool:
        return self.status_code == 304


def check_url_allowed(url: str, allowed_hosts: list[str]) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise FetchError("url_not_allowed", f"non-https URL: {url}")
    if (parts.hostname or "").lower() not in {h.lower() for h in allowed_hosts}:
        raise FetchError("url_not_allowed", f"host not allow-listed: {parts.hostname}")


def _respect_interval(min_interval_s: float) -> None:
    global _last_request_at
    with _interval_lock:
        wait = _last_request_at + min_interval_s - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.monotonic()


def fetch_source(
    url: str,
    settings: Settings,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    client: httpx.Client | None = None,
    sleep=time.sleep,
) -> FetchResult:
    check_url_allowed(url, settings.fetch_allowed_hosts)
    headers = {"User-Agent": settings.fetch_user_agent, "Accept": "text/html", "Accept-Language": "uz"}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    own_client = client is None
    client = client or httpx.Client(timeout=settings.fetch_timeout_s, follow_redirects=False)
    try:
        last_exc: Exception | None = None
        for attempt in range(settings.fetch_max_retries + 1):
            if attempt:
                delay = settings.fetch_backoff_base_s * (2 ** (attempt - 1))
                log.info("fetch_retry", attempt=attempt, delay_s=delay)
                sleep(delay)
            try:
                return _fetch_once(client, url, headers, settings)
            except FetchError as exc:
                if exc.code not in ("http_5xx", "timeout", "network", "http_429"):
                    raise
                last_exc = exc
        raise last_exc or FetchError("network", "unknown")
    finally:
        if own_client:
            client.close()


def _fetch_once(client: httpx.Client, url: str, headers: dict, settings: Settings) -> FetchResult:
    current = url
    for _ in range(5):  # bounded redirect chain
        _respect_interval(settings.fetch_min_interval_s)
        try:
            with client.stream("GET", current, headers=headers) as resp:
                if resp.is_redirect:
                    nxt = urljoin(current, resp.headers.get("location", ""))
                    check_url_allowed(nxt, settings.fetch_allowed_hosts)
                    current = nxt
                    continue
                if resp.status_code == 304:
                    return FetchResult(url, current, 304, None, dict(resp.headers), datetime.now(UTC))
                if resp.status_code == 429:
                    raise FetchError("http_429", "rate limited by source")
                if resp.status_code >= 500:
                    raise FetchError("http_5xx", f"status {resp.status_code}")
                if resp.status_code != 200:
                    raise FetchError("http_status", f"status {resp.status_code}")
                body = bytearray()
                for part in resp.iter_bytes():
                    body.extend(part)
                    if len(body) > settings.fetch_max_bytes:
                        raise FetchError("too_large", f"> {settings.fetch_max_bytes} bytes")
                return FetchResult(url, current, 200, bytes(body), dict(resp.headers), datetime.now(UTC))
        except httpx.TimeoutException as exc:
            raise FetchError("timeout", str(exc)) from exc
        except httpx.TransportError as exc:
            raise FetchError("network", str(exc)) from exc
    raise FetchError("too_many_redirects", current)


def store_snapshot(snapshot_dir: Path, source_key: str, body: bytes, fetched_at: datetime) -> tuple[str, str]:
    """Write gzip'd raw bytes. Returns (relative path, sha256 of raw bytes)."""
    digest = hashlib.sha256(body).hexdigest()
    rel = Path(source_key) / f"{fetched_at.strftime('%Y%m%dT%H%M%SZ')}_{digest[:12]}.html.gz"
    target = snapshot_dir / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        with gzip.open(target, "wb") as fh:
            fh.write(body)
    return rel.as_posix(), digest
