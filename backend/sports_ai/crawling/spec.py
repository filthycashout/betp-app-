"""Declarative definitions for reusable domain-scoped spiders."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from urllib.parse import urldefrag, urljoin, urlsplit, urlunsplit


class SpiderPolicyError(ValueError):
    """Rejected spider configuration or crawl URL."""


def safe_url(url: str, allowed_hosts: frozenset[str]) -> str:
    """Accept public HTTPS URLs to exact, explicitly approved DNS hosts only."""
    try:
        parsed = urlsplit(str(url).strip())
        hostname = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
    except ValueError as exc:
        raise SpiderPolicyError("malformed URL") from exc
    if parsed.scheme.lower() != "https" or not hostname:
        raise SpiderPolicyError("only HTTPS URLs with hostnames are allowed")
    if parsed.username or parsed.password or port not in (None, 443):
        raise SpiderPolicyError("credentials and nonstandard ports are not allowed")
    if hostname not in allowed_hosts:
        raise SpiderPolicyError(f"host not in spider allowlist: {hostname}")
    if hostname == "localhost" or hostname.endswith((".localhost", ".local", ".internal")):
        raise SpiderPolicyError("local hosts are forbidden")
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise SpiderPolicyError("literal IP hosts are forbidden")
    without_fragment, _ = urldefrag(urlunsplit(("https", hostname, parsed.path or "/", parsed.query, "")))
    return without_fragment


def normalize_link(base: str, href: str, allowed_hosts: frozenset[str]) -> str | None:
    """Reject off-domain, non-HTTPS and non-web links without crashing a crawl."""
    try:
        return safe_url(urljoin(base, href), allowed_hosts)
    except (SpiderPolicyError, ValueError):
        return None


@dataclass(frozen=True)
class FieldSpec:
    selector: str
    attribute: str | None = None
    multiple: bool = False

    @classmethod
    def from_value(cls, value: str | dict[str, Any]) -> "FieldSpec":
        if isinstance(value, str):
            return cls(selector=value)
        if not isinstance(value, dict) or not isinstance(value.get("selector"), str):
            raise SpiderPolicyError("fields must be CSS selector strings or field objects")
        attr = value.get("attribute")
        if attr is not None and (not isinstance(attr, str) or not attr.strip()):
            raise SpiderPolicyError("field attribute must be a nonempty string")
        return cls(selector=value["selector"], attribute=attr, multiple=bool(value.get("multiple", False)))


@dataclass(frozen=True)
class SpiderSpec:
    name: str
    start_urls: tuple[str, ...]
    allowed_hosts: frozenset[str]
    item_selector: str
    fields: dict[str, FieldSpec]
    follow_selector: str = "a[href]"
    required_fields: tuple[str, ...] = ()
    max_pages: int = 1000
    max_depth: int = 5
    max_items: int = 10000
    concurrency: int = 5
    request_delay_seconds: float = 0.5
    timeout_seconds: float = 15.0
    max_response_bytes: int = 1_048_576
    retries: int = 2
    source_kind: str = "general_web"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpiderSpec":
        if not isinstance(data, dict):
            raise SpiderPolicyError("spider spec must be an object")
        hosts = frozenset(str(h).rstrip(".").lower().strip() for h in data.get("allowed_hosts", []))
        if not hosts or any(not h or "/" in h or ":" in h for h in hosts):
            raise SpiderPolicyError("allowed_hosts must contain exact DNS hostnames")
        urls = tuple(safe_url(u, hosts) for u in data.get("start_urls", []))
        if not urls or len(urls) > 20:
            raise SpiderPolicyError("1 to 20 start URLs required")
        fields = {str(k): FieldSpec.from_value(v) for k, v in data.get("fields", {}).items()}
        reserved = {"spider", "source_kind", "source_url", "fetched_at", "content_sha256",
                    "trusted_for_instructions", "used_in_prediction", "historical_training_eligible",
                    "canonical_admission_required"}
        if (not fields or len(fields) > 100 or
                any(not k or k.startswith("_") or k in reserved for k in fields)):
            raise SpiderPolicyError("1 to 100 named fields required; provenance field names are reserved")
        required = tuple(data.get("required_fields", ()))
        if any(k not in fields for k in required):
            raise SpiderPolicyError("required_fields must reference defined fields")
        opts = dict(
            name=str(data.get("name", "")).strip(), start_urls=urls, allowed_hosts=hosts,
            item_selector=str(data.get("item_selector", "")).strip(),
            fields=fields, follow_selector=str(data.get("follow_selector", "a[href]")).strip(),
            required_fields=required,
            max_pages=int(data.get("max_pages", 1000)), max_depth=int(data.get("max_depth", 5)),
            max_items=int(data.get("max_items", 10000)), concurrency=int(data.get("concurrency", 5)),
            request_delay_seconds=float(data.get("request_delay_seconds", 0.5)),
            timeout_seconds=float(data.get("timeout_seconds", 15.0)),
            max_response_bytes=int(data.get("max_response_bytes", 1_048_576)),
            retries=int(data.get("retries", 2)), source_kind=str(data.get("source_kind", "general_web")),
        )
        if not opts["name"] or len(opts["name"]) > 100 or not opts["item_selector"] or not opts["follow_selector"]:
            raise SpiderPolicyError("name, item_selector and follow_selector are required")
        bounds = (("max_pages", 1, 100_000), ("max_depth", 0, 100), ("max_items", 1, 1_000_000),
                  ("concurrency", 1, 32), ("max_response_bytes", 1024, 10_485_760), ("retries", 0, 5))
        for key, low, high in bounds:
            if not low <= opts[key] <= high:
                raise SpiderPolicyError(f"{key} must be between {low} and {high}")
        if not 0 <= opts["request_delay_seconds"] <= 60 or not 1 <= opts["timeout_seconds"] <= 120:
            raise SpiderPolicyError("invalid request delay or timeout")
        if opts["source_kind"] not in {"general_web", "sports_context", "market"}:
            raise SpiderPolicyError("source_kind must be general_web, sports_context, or market")
        from bs4 import BeautifulSoup
        sample = BeautifulSoup("<html><body></body></html>", "html.parser")
        for selector in [opts["item_selector"], opts["follow_selector"], *(f.selector for f in fields.values())]:
            try:
                sample.select(selector)
            except Exception as exc:
                raise SpiderPolicyError(f"invalid CSS selector: {selector}") from exc
        return cls(**opts)
