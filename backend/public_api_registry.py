from __future__ import annotations

"""Governed discovery registry for candidate sports APIs.

Public API directories are discovery inputs only. A listing never becomes production
evidence by itself. Candidates must pass PhilthySports provenance, freshness, schema,
event-mapping, immutable-capture, and sport-specific validation before promotion.
"""

from typing import Any

DISCOVERY_SOURCE = "publicapis.dev"
ALLOWED_STATES = (
    "DISCOVERED",
    "CANARY_PASS",
    "LIVE_VERIFIED",
    "HISTORICAL_VERIFIED",
    "PRODUCTION_ELIGIBLE",
    "REJECTED",
)

# Initial registry intentionally records capabilities, not trust. URLs here are
# documentation/discovery references and are never queried by normal request paths.
CANDIDATES: tuple[dict[str, Any], ...] = (
    {
        "id": "nba-stats-publicapis",
        "sports": ("NBA",),
        "capabilities": ("historical_stats", "player_stats", "advanced_metrics"),
        "state": "DISCOVERED",
        "production_enabled": False,
    },
    {
        "id": "mlb-stats-publicapis",
        "sports": ("MLB",),
        "capabilities": ("historical_stats", "records"),
        "state": "DISCOVERED",
        "production_enabled": False,
    },
    {
        "id": "nhl-stats-publicapis",
        "sports": ("NHL",),
        "capabilities": ("historical_stats", "records"),
        "state": "DISCOVERED",
        "production_enabled": False,
    },
    {
        "id": "isports-publicapis",
        "sports": ("NFL", "NBA", "MLB", "NHL"),
        "capabilities": ("fixtures", "scores", "player_stats", "historical_stats"),
        "state": "DISCOVERED",
        "production_enabled": False,
    },
)

REQUIRED_PROMOTION_EVIDENCE = (
    "official_provider_documentation_verified",
    "terms_and_auth_reviewed",
    "stable_event_mapping_verified",
    "schema_validated",
    "live_canary_passed",
    "provider_timestamp_verified",
    "freshness_policy_passed",
    "immutable_raw_capture_sha256",
    "result_availability_observed_independently",
)


def registry() -> dict[str, Any]:
    """Return safe discovery metadata without credentials or unverified claims."""
    return {
        "schema_version": 1,
        "discovery_source": DISCOVERY_SOURCE,
        "policy": "DISCOVERY_ONLY_FAIL_CLOSED",
        "allowed_states": list(ALLOWED_STATES),
        "required_promotion_evidence": list(REQUIRED_PROMOTION_EVIDENCE),
        "candidates": [dict(item) for item in CANDIDATES],
        "production_candidates": [
            item["id"] for item in CANDIDATES if item.get("production_enabled") is True
        ],
    }


def promotion_decision(candidate_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
    """Fail closed unless every production-evidence requirement is explicitly true."""
    candidate = next((item for item in CANDIDATES if item["id"] == candidate_id), None)
    if candidate is None:
        return {"candidate_id": candidate_id, "state": "REJECTED", "eligible": False, "missing": ["known_candidate"]}
    missing = [key for key in REQUIRED_PROMOTION_EVIDENCE if evidence.get(key) is not True]
    return {
        "candidate_id": candidate_id,
        "state": "PRODUCTION_ELIGIBLE" if not missing else "DISCOVERED",
        "eligible": not missing,
        "missing": missing,
        "note": "Eligibility does not enable a provider; explicit configuration and regression evidence are still required.",
    }
