"""Bounded asynchronous HTML spider runner with robots and crawl provenance.

Only opt-in domain-scoped HTTPS crawling is supported. No browser automation,
login bypass, captcha evasion, proxy rotation or automatic model feature admission.
"""
from __future__ import annotations

import asyncio
import csv
import hashlib
import ipaddress
import json
import socket
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup

from .spec import SpiderPolicyError, SpiderSpec, normalize_link, safe_url

USER_AGENT = "SportsOmniResearchSpider/1.0"
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class FetchResponse:
    status: int
    body: bytes
    content_type: str = "text/html"
    retry_after_seconds: float | None = None


class PageFetcher(Protocol):
    async def fetch(self, url: str, max_bytes: int) -> FetchResponse: ...


class PublicDNSResolver:
    """Validate actual connection DNS answers; block private/reserved destinations."""

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, port, type=socket.SOCK_STREAM, family=socket.AF_UNSPEC)
        addresses = {item[4][0] for item in infos}
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise OSError("DNS resolved to a non-public destination")
        return [
            {"hostname": host, "host": a, "port": port, "family": socket.AF_INET6 if ":" in a else socket.AF_INET,
             "proto": 0, "flags": socket.AI_NUMERICHOST}
            for a in sorted(addresses)
        ]

    async def close(self) -> None:
        return None


class AiohttpFetcher:
    """Production fetcher: TLS-only, no redirects, no env proxies, bounded bodies."""

    def __init__(self, concurrency: int, timeout_seconds: float, user_agent: str = USER_AGENT):
        self.concurrency = concurrency
        self.timeout_seconds = timeout_seconds
        self.user_agent = user_agent
        self._session: Any = None

    async def __aenter__(self):
        import aiohttp

        connector = aiohttp.TCPConnector(limit=self.concurrency, resolver=PublicDNSResolver(), ttl_dns_cache=0)
        self._session = aiohttp.ClientSession(
            connector=connector, timeout=aiohttp.ClientTimeout(total=self.timeout_seconds),
            trust_env=False, headers={"User-Agent": self.user_agent, "Accept": "text/html,application/xhtml+xml"},
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self._session.close()

    async def fetch(self, url: str, max_bytes: int) -> FetchResponse:
        async with self._session.get(url, allow_redirects=False) as response:
            body = bytearray()
            async for chunk in response.content.iter_chunked(64 * 1024):
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise SpiderPolicyError("response exceeds configured max_response_bytes")
            retry_after = response.headers.get("Retry-After")
            try:
                retry_delay = max(0.0, min(float(retry_after), 30.0)) if retry_after else None
            except (ValueError, TypeError):
                retry_delay = None
            return FetchResponse(status=response.status, body=bytes(body),
                                 content_type=response.headers.get("Content-Type", "").lower(),
                                 retry_after_seconds=retry_delay)


class StreamingWriter:
    """Incrementally write JSONL, JSON array or flat CSV without buffering results."""

    META = ("spider", "source_kind", "source_url", "fetched_at", "content_sha256",
            "trusted_for_instructions", "used_in_prediction", "historical_training_eligible",
            "canonical_admission_required")

    def __init__(self, path: Path, fmt: str, fields: tuple[str, ...]):
        if fmt not in {"json", "jsonl", "csv"}:
            raise ValueError("output format must be json, jsonl or csv")
        self.path = path
        self.fmt = fmt
        self.fields = fields
        self._count = 0
        self._file: Any = None
        self._writer: Any = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = self.path.open("w", encoding="utf-8", newline="")
        if self.fmt == "csv":
            self._writer = csv.DictWriter(self._file, fieldnames=[*self.META, *self.fields], extrasaction="ignore")
            self._writer.writeheader()
        elif self.fmt == "json":
            self._file.write("[\n")
        return self

    def write(self, item: dict[str, Any]) -> None:
        if self.fmt == "csv":
            self._writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value
                                   for key, value in item.items()})
        else:
            text = json.dumps(item, sort_keys=True, ensure_ascii=False)
            self._file.write((",\n" if self._count else "") + text if self.fmt == "json" else text + "\n")
        self._count += 1

    def __exit__(self, exc_type, exc, tb):
        if self.fmt == "json":
            self._file.write("\n]\n")
        self._file.close()


@dataclass
class CrawlStats:
    spider: str
    visited: int = 0
    extracted: int = 0
    refused_by_robots: int = 0
    fetch_errors: int = 0
    http_failures: int = 0
    non_html_pages: int = 0
    queued: int = 0
    finished_at: str = ""


class SpiderRunner:
    def __init__(self, spec: SpiderSpec, *, fetcher: PageFetcher | None = None,
                 user_agent: str = USER_AGENT, sleep: Any = None):
        self.spec = spec
        self._external_fetcher = fetcher
        self._fetcher: PageFetcher | None = fetcher
        self.user_agent = user_agent
        self._sleep = sleep or asyncio.sleep
        self._queue: asyncio.Queue[tuple[str, int]] = asyncio.Queue()
        self._seen: set[str] = set()
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_lock = asyncio.Lock()
        self._host_locks: dict[str, asyncio.Lock] = {}
        self._next_request: dict[str, float] = {}
        self.stats = CrawlStats(spider=spec.name)

    async def _throttle(self, host: str, delay: float) -> None:
        lock = self._host_locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = max(0.0, self._next_request.get(host, 0.0) - time.monotonic())
            if wait:
                await self._sleep(wait)
            self._next_request[host] = time.monotonic() + delay

    async def _request(self, url: str, *, robots: bool = False) -> FetchResponse:
        host = urlsplit(url).hostname or ""
        robot_parser = self._robots.get(host)
        crawl_delay = robot_parser.crawl_delay(self.user_agent) if robot_parser else None
        delay = max(self.spec.request_delay_seconds, float(crawl_delay or 0))
        for attempt in range(self.spec.retries + 1):
            await self._throttle(host, delay)
            assert self._fetcher is not None
            try:
                response = await self._fetcher.fetch(url, self.spec.max_response_bytes)
            except (OSError, asyncio.TimeoutError):
                if attempt == self.spec.retries:
                    raise
                await self._sleep(min(2 ** attempt, 10))
                continue
            if response.status not in RETRY_STATUSES or attempt == self.spec.retries:
                return response
            await self._sleep(response.retry_after_seconds if response.retry_after_seconds is not None
                              else min(2 ** attempt, 10))
        raise AssertionError("unreachable")

    async def _robots_allowed(self, url: str) -> bool:
        host = urlsplit(url).hostname or ""
        async with self._robots_lock:
            if host not in self._robots:
                robots_url = f"https://{host}/robots.txt"
                try:
                    response = await self._request(robots_url, robots=True)
                    if response.status == 200:
                        parser = RobotFileParser()
                        parser.parse(response.body.decode("utf-8", errors="replace").splitlines())
                        self._robots[host] = parser
                    elif response.status in (404, 410):
                        self._robots[host] = None
                    else:
                        return False
                except Exception:
                    return False
            parser = self._robots.get(host)
            return parser.can_fetch(self.user_agent, url) if parser else True

    def _enqueue(self, url: str, depth: int) -> None:
        if url in self._seen or len(self._seen) >= self.spec.max_pages or depth > self.spec.max_depth:
            return
        self._seen.add(url)
        self._queue.put_nowait((url, depth))
        self.stats.queued += 1

    def parse_item(self, node: Any) -> dict[str, Any]:
        """Override in a Python spider subclass for custom per-item parsing."""
        extracted: dict[str, Any] = {}
        for name, field in self.spec.fields.items():
            matches = node.select(field.selector)
            values = []
            for element in matches if field.multiple else matches[:1]:
                value = element.get(field.attribute) if field.attribute else element.get_text(" ", strip=True)
                if isinstance(value, list):
                    value = " ".join(value)
                if value is not None and str(value).strip():
                    values.append(str(value).strip())
            extracted[name] = values if field.multiple else (values[0] if values else None)
        return extracted

    def discover_links(self, soup: BeautifulSoup, url: str) -> list[str]:
        """Override for pagination rules; URLs still pass safety and depth gates."""
        results = []
        for anchor in soup.select(self.spec.follow_selector):
            href = anchor.get("href")
            if isinstance(href, str):
                link = normalize_link(url, href, self.spec.allowed_hosts)
                if link:
                    results.append(link)
        return results

    def _extract(self, soup: BeautifulSoup, *, url: str, fetched_at: str,
                 digest: str, writer: StreamingWriter) -> None:
        for node in soup.select(self.spec.item_selector):
            if self.stats.extracted >= self.spec.max_items:
                return
            extracted = self.parse_item(node)
            if not any(extracted.values()) or any(not extracted.get(name) for name in self.spec.required_fields):
                continue
            writer.write({
                "spider": self.spec.name, "source_kind": self.spec.source_kind,
                "source_url": url, "fetched_at": fetched_at, "content_sha256": digest,
                "trusted_for_instructions": False, "used_in_prediction": False,
                "historical_training_eligible": False, "canonical_admission_required": True,
                **extracted,
            })
            self.stats.extracted += 1

    async def _work(self, writer: StreamingWriter) -> None:
        while True:
            url, depth = await self._queue.get()
            try:
                if self.stats.extracted >= self.spec.max_items:
                    continue
                if not await self._robots_allowed(url):
                    self.stats.refused_by_robots += 1
                    continue
                try:
                    response = await self._request(url)
                except Exception:
                    self.stats.fetch_errors += 1
                    continue
                self.stats.visited += 1
                if response.status != 200:
                    self.stats.http_failures += 1
                    continue
                if not any(t in response.content_type for t in ("text/html", "application/xhtml+xml")):
                    self.stats.non_html_pages += 1
                    continue
                soup = BeautifulSoup(response.body, "html.parser")
                fetched_at = datetime.now(timezone.utc).isoformat()
                digest = hashlib.sha256(response.body).hexdigest()
                self._extract(soup, url=url, fetched_at=fetched_at, digest=digest, writer=writer)
                if depth < self.spec.max_depth and self.stats.extracted < self.spec.max_items:
                    for link in self.discover_links(soup, url):
                        try:
                            self._enqueue(safe_url(link, self.spec.allowed_hosts), depth + 1)
                        except SpiderPolicyError:
                            continue
            except Exception:
                self.stats.fetch_errors += 1
            finally:
                self._queue.task_done()

    async def run(self, output: Path, fmt: str = "jsonl") -> CrawlStats:
        """Crawl with bounded concurrency and stream results to disk."""
        if self._external_fetcher is None and self.spec.request_delay_seconds < 0.2:
            raise SpiderPolicyError("network spider request delay must be at least 0.2 seconds")
        for url in self.spec.start_urls:
            self._enqueue(url, 0)
        fetcher = self._external_fetcher or AiohttpFetcher(self.spec.concurrency, self.spec.timeout_seconds,
                                                            self.user_agent)
        if self._external_fetcher is None:
            async with fetcher:
                self._fetcher = fetcher
                await self._crawl(output, fmt)
        else:
            self._fetcher = fetcher
            await self._crawl(output, fmt)
        self.stats.finished_at = datetime.now(timezone.utc).isoformat()
        return self.stats

    async def _crawl(self, output: Path, fmt: str) -> None:
        with StreamingWriter(output, fmt, tuple(self.spec.fields)) as writer:
            workers = [asyncio.create_task(self._work(writer)) for _ in range(self.spec.concurrency)]
            try:
                await self._queue.join()
            finally:
                for worker in workers:
                    worker.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
