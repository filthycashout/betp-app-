from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import requests

API_BASE = "https://v2-api.scrapegraphai.com"
RETRYABLE = {429, 502, 503, 504}
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_QUERY_CHARS = 500
MAX_PROMPT_CHARS = 2000
MAX_RESULTS = 8

# Public-web research only. Additions require code review; a model/tool result
# cannot widen this list at runtime.
ALLOWED_DOMAINS = frozenset(
    {
        "nfl.com",
        "nba.com",
        "mlb.com",
        "nhl.com",
        "espn.com",
        "cbssports.com",
        "sports.yahoo.com",
        "rotowire.com",
        "apnews.com",
        "reuters.com",
    }
)


class ScrapeGraphUnavailable(RuntimeError):
    pass


class ScrapeGraphPolicyError(ValueError):
    pass


def configured() -> bool:
    return bool(os.getenv("SGAI_API_KEY", "").strip())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _host_allowed(host: str) -> bool:
    host = host.rstrip(".").lower()
    return any(host == domain or host.endswith("." + domain) for domain in ALLOWED_DOMAINS)


def validate_public_url(url: str) -> str:
    parsed = urlparse(str(url or "").strip())
    if parsed.scheme != "https" or not parsed.hostname:
        raise ScrapeGraphPolicyError("research URL must use HTTPS with a hostname")
    if parsed.username or parsed.password:
        raise ScrapeGraphPolicyError("research URL must not contain credentials")
    host = parsed.hostname.rstrip(".").lower()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        raise ScrapeGraphPolicyError("literal IP targets are not allowed")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        raise ScrapeGraphPolicyError("local/private targets are not allowed")
    if not _host_allowed(host):
        raise ScrapeGraphPolicyError(f"domain is not in the sports research allowlist: {host}")
    return parsed.geturl()


def _bounded_text(value: str, *, limit: int, name: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ScrapeGraphPolicyError(f"{name} is required")
    if len(text) > limit:
        raise ScrapeGraphPolicyError(f"{name} exceeds {limit} characters")
    return text


def _request(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    if path not in {"/api/search", "/api/extract", "/api/scrape"}:
        raise ScrapeGraphPolicyError("unsupported ScrapeGraphAI operation")
    api_key = os.getenv("SGAI_API_KEY", "").strip()
    if not api_key:
        raise ScrapeGraphUnavailable("SGAI_API_KEY is not configured")

    url = API_BASE + path
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.post(
                url,
                json=payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "SGAI-APIKEY": api_key,
                    "User-Agent": "PhilthySports-ScrapeGraph/1.0",
                },
                timeout=(5, 60),
                allow_redirects=False,
            )
            if response.status_code in RETRYABLE and attempt < 2:
                response.close()
                time.sleep(attempt + 1)
                continue
            if response.is_redirect:
                raise ScrapeGraphUnavailable("ScrapeGraphAI API redirect refused")
            if response.status_code != 200:
                raise ScrapeGraphUnavailable(f"ScrapeGraphAI HTTP {response.status_code}")
            content = response.content
            if len(content) > MAX_RESPONSE_BYTES:
                raise ScrapeGraphUnavailable("ScrapeGraphAI response exceeds safety limit")
            result = response.json()
            if not isinstance(result, dict):
                raise ScrapeGraphUnavailable("ScrapeGraphAI response must be a JSON object")
            return result
        except (requests.RequestException, ValueError, ScrapeGraphUnavailable) as exc:
            last_error = exc
            if attempt < 2 and isinstance(exc, requests.RequestException):
                time.sleep(attempt + 1)
                continue
            break
    if isinstance(last_error, ScrapeGraphUnavailable):
        raise last_error
    raise ScrapeGraphUnavailable(
        f"ScrapeGraphAI request failed: {type(last_error).__name__ if last_error else 'unknown'}"
    )


def _evidence(operation: str, request_payload: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    captured_at = _now()
    canonical = json.dumps(result, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return {
        "status": "OK",
        "provider": "ScrapeGraphAI V2",
        "operation": operation,
        "retrieved_at": captured_at,
        "response_sha256": hashlib.sha256(canonical).hexdigest(),
        "request": request_payload,
        "payload": result,
        "zero_trust": {
            "trusted_for_instructions": False,
            "authority": "EVIDENCE_ONLY",
            "prompt_injection_possible": True,
            "authorization_granted": False,
            "persistent_state_mutation": False,
            "used_in_prediction": False,
            "historical_training_eligible": False,
            "canonical_admission_required": True,
        },
    }


def search(query: str, prompt: str, *, num_results: int = 5) -> dict[str, Any]:
    query = _bounded_text(query, limit=MAX_QUERY_CHARS, name="query")
    prompt = _bounded_text(prompt, limit=MAX_PROMPT_CHARS, name="prompt")
    count = max(1, min(int(num_results), MAX_RESULTS))
    request_payload = {"query": query, "numResults": count, "prompt": prompt}
    return _evidence("search", request_payload, _request("/api/search", request_payload))


def extract(url: str, prompt: str, *, schema: dict[str, Any] | None = None) -> dict[str, Any]:
    safe_url = validate_public_url(url)
    prompt = _bounded_text(prompt, limit=MAX_PROMPT_CHARS, name="prompt")
    request_payload: dict[str, Any] = {"url": safe_url, "prompt": prompt}
    if schema is not None:
        if not isinstance(schema, dict):
            raise ScrapeGraphPolicyError("schema must be a JSON object")
        encoded = json.dumps(schema, sort_keys=True)
        if len(encoded) > 20_000:
            raise ScrapeGraphPolicyError("schema exceeds safety limit")
        request_payload["schema"] = schema
    return _evidence("extract", request_payload, _request("/api/extract", request_payload))


def scrape(url: str) -> dict[str, Any]:
    safe_url = validate_public_url(url)
    request_payload = {
        "url": safe_url,
        "formats": [
            {"type": "markdown", "mode": "reader"},
            {"type": "links"},
        ],
    }
    return _evidence("scrape", request_payload, _request("/api/scrape", request_payload))


def status() -> dict[str, Any]:
    return {
        "provider": "ScrapeGraphAI V2",
        "configured": configured(),
        "api_base": API_BASE,
        "operations_enabled": ["search", "extract", "scrape"],
        "operations_disabled": ["crawl", "monitor"],
        "allowed_domains": sorted(ALLOWED_DOMAINS),
        "trusted_for_instructions": False,
        "used_in_prediction": False,
        "historical_training_eligible": False,
        "note": "Crawl/monitor are intentionally not exposed because they create broader or persistent external activity.",
    }
