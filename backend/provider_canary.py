from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from typing import Any

import requests

THE_ODDS_API_SPORTS_URL = "https://api.the-odds-api.com/v4/sports"
THE_ODDS_API_HISTORICAL_EVENTS_URL = (
    "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/events"
)
# Historical probe is intentionally a single events request. It is never run by
# the normal status route and is only used when explicitly requested.
HISTORICAL_PROBE_DATE = "2024-01-15T12:00:00Z"


def _usage_headers(response: requests.Response) -> dict[str, Any]:
    def number(name: str) -> int | None:
        raw = response.headers.get(name)
        if raw is None:
            return None
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    return {
        "requests_remaining": number("x-requests-remaining"),
        "requests_used": number("x-requests-used"),
        "requests_last": number("x-requests-last"),
    }


def _safe_http_state(code: int) -> str:
    if code == 200:
        return "PASS"
    if code in (401, 403):
        return "AUTHENTICATION_REJECTED"
    if code == 429:
        return "QUOTA_OR_RATE_LIMIT"
    if 400 <= code < 500:
        return "PROVIDER_REQUEST_REJECTED"
    if code >= 500:
        return "PROVIDER_SERVER_ERROR"
    return "UNEXPECTED_HTTP_STATUS"


def _the_odds_api_canary(*, historical_probe: bool = False) -> dict[str, Any]:
    key = os.getenv("ODDS_API_KEY", "").strip()
    rotation = os.getenv("CREDENTIAL_ROTATION_CONFIRMED", "").strip().lower() == "true"
    base: dict[str, Any] = {
        "provider": "The Odds API v4",
        "credential_env": "ODDS_API_KEY",
        "credential_configured": bool(key),
        "rotation_confirmed": rotation,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "secret_exposed": False,
        "authenticated": False,
        "schema_valid": False,
        "status": "BLOCKED",
    }
    if not rotation:
        return {**base, "reason": "credential rotation is not confirmed"}
    if not key:
        return {**base, "reason": "ODDS_API_KEY is not configured"}

    try:
        response = requests.get(
            THE_ODDS_API_SPORTS_URL,
            params={"apiKey": key},
            headers={"Accept": "application/json", "User-Agent": "PhilthySports/provider-canary"},
            timeout=15,
        )
    except requests.RequestException as exc:
        return {
            **base,
            "reason": "provider request failed before an HTTP response",
            "error_type": type(exc).__name__,
        }

    result = {
        **base,
        "http_status": response.status_code,
        "http_state": _safe_http_state(response.status_code),
        "usage": _usage_headers(response),
    }
    if response.status_code != 200:
        return {**result, "reason": "provider did not authenticate the configured credential"}

    try:
        payload = response.json()
    except ValueError:
        return {**result, "reason": "provider authenticated but returned invalid JSON"}

    schema_valid = isinstance(payload, list) and all(
        isinstance(row, dict) and isinstance(row.get("key"), str)
        for row in payload[:20]
    )
    sports_seen = {
        str(row.get("key"))
        for row in payload
        if isinstance(row, dict) and isinstance(row.get("key"), str)
    }
    expected = {
        "americanfootball_nfl",
        "basketball_nba",
        "baseball_mlb",
        "icehockey_nhl",
    }
    result.update(
        {
            "authenticated": True,
            "schema_valid": schema_valid,
            "four_sport_catalog_visible": bool(expected & sports_seen),
            "catalog_count": len(payload) if isinstance(payload, list) else None,
            "status": "PASS" if schema_valid else "BLOCKED",
            "reason": (
                "configured credential authenticated against the live provider and response schema is valid"
                if schema_valid
                else "credential authenticated but provider schema validation failed"
            ),
        }
    )

    if historical_probe:
        result["historical_access_probe"] = _historical_access_probe(key)
    return result


def _historical_access_probe(key: str) -> dict[str, Any]:
    """Probe paid historical access once when explicitly requested.

    This deliberately calls only the historical *events* endpoint, not historical
    odds. The result is metadata-only and never returns provider payloads or the key.
    """
    checked = datetime.now(timezone.utc).isoformat()
    try:
        response = requests.get(
            THE_ODDS_API_HISTORICAL_EVENTS_URL,
            params={"apiKey": key, "date": HISTORICAL_PROBE_DATE},
            headers={"Accept": "application/json", "User-Agent": "PhilthySports/historical-access-canary"},
            timeout=20,
        )
    except requests.RequestException as exc:
        return {
            "checked_at": checked,
            "status": "BLOCKED",
            "reason": "historical access probe failed before an HTTP response",
            "error_type": type(exc).__name__,
        }

    out: dict[str, Any] = {
        "checked_at": checked,
        "http_status": response.status_code,
        "http_state": _safe_http_state(response.status_code),
        "usage": _usage_headers(response),
        "probe_date": HISTORICAL_PROBE_DATE,
        "status": "BLOCKED",
    }
    if response.status_code != 200:
        out["reason"] = "historical endpoint access was not accepted"
        return out
    try:
        payload = response.json()
    except ValueError:
        out["reason"] = "historical endpoint returned invalid JSON"
        return out
    data = payload.get("data") if isinstance(payload, dict) else None
    valid = isinstance(payload, dict) and isinstance(data, list)
    out.update(
        {
            "schema_valid": valid,
            "events_returned": len(data) if isinstance(data, list) else None,
            "status": "PASS" if valid else "BLOCKED",
            "reason": (
                "historical events endpoint is accessible with the configured credential"
                if valid
                else "historical endpoint response schema was not valid"
            ),
        }
    )
    return out


def _live_provider_canaries_uncached(*, historical_probe: bool = False) -> dict[str, Any]:
    odds = _the_odds_api_canary(historical_probe=historical_probe)
    sportradar_configured = bool(os.getenv("SPORTRADAR_API_KEY", "").strip())
    return {
        "schema_version": 1,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "the_odds_api": odds,
        "sportradar": {
            "credential_configured": sportradar_configured,
            "status": "NOT_PROBED",
            "reason": "no sport/feed-specific Sportradar entitlement endpoint is assumed by this generic canary",
            "secret_exposed": False,
        },
        "credentialled_live_provider_verified": (
            odds.get("authenticated") is True and odds.get("schema_valid") is True
        ),
    }


_CANARY_CACHE_LOCK = threading.Lock()
_CANARY_CACHE_VALUE: dict[str, Any] | None = None
_CANARY_CACHE_AT = 0.0
_CANARY_TTL_SECONDS = 300.0


def live_provider_canaries(*, historical_probe: bool = False) -> dict[str, Any]:
    """Return a fresh historical probe or a short-lived cached live canary."""
    global _CANARY_CACHE_VALUE, _CANARY_CACHE_AT
    if historical_probe:
        return _live_provider_canaries_uncached(historical_probe=True)
    now = time.monotonic()
    with _CANARY_CACHE_LOCK:
        if (
            _CANARY_CACHE_VALUE is not None
            and now - _CANARY_CACHE_AT < _CANARY_TTL_SECONDS
        ):
            return dict(_CANARY_CACHE_VALUE)
    value = _live_provider_canaries_uncached(historical_probe=False)
    with _CANARY_CACHE_LOCK:
        _CANARY_CACHE_VALUE = dict(value)
        _CANARY_CACHE_AT = time.monotonic()
    return dict(value)
