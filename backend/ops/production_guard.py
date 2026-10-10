from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

RETRYABLE_HTTP = {429, 502, 503, 504}


def _unwrap(payload: Any) -> Any:
    """Unwrap Floot/SuperJSON transport envelopes while preserving plain JSON APIs."""
    if (
        isinstance(payload, dict)
        and "json" in payload
        and set(payload).issubset({"json", "meta"})
    ):
        return payload["json"]
    return payload


def get_json(url: str, attempts: int = 4, delay: float = 2.0) -> Any:
    last: str | None = None
    for attempt in range(attempts):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "Accept": "application/json",
                    "User-Agent": "PhilthyParleys-production-guard/1.2",
                },
            )
            with urllib.request.urlopen(req, timeout=25) as response:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}")
                payload = json.loads(response.read().decode("utf-8"))
                return _unwrap(payload)
        except urllib.error.HTTPError as exc:
            last = f"HTTPError: HTTP {exc.code}"
            exc.close()
            if exc.code not in RETRYABLE_HTTP:
                raise RuntimeError(last) from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as exc:
            last = f"{type(exc).__name__}: {exc}"
        except Exception as exc:
            last = f"{type(exc).__name__}: {exc}"
            if attempt + 1 >= attempts:
                break
        if attempt + 1 < attempts:
            time.sleep(delay * (attempt + 1))
    raise RuntimeError(last or "request failed")


def _provider_contract(providers: Any) -> tuple[bool, dict[str, Any] | None]:
    if not isinstance(providers, dict):
        return False, None
    rows = providers.get("providers")
    if not isinstance(rows, list):
        return False, None
    odds = next((row for row in rows if isinstance(row, dict) and row.get("id") == "the_odds_api"), None)
    if odds is None:
        return False, None

    # A provider may legitimately be unconfigured. What the guard forbids is an
    # internally contradictory claim that an unconfigured provider is already
    # authenticated/validated.
    configured = odds.get("configured") is True
    authenticated = odds.get("authenticated") is True
    schema_valid = odds.get("schema_valid") is True
    coherent = not authenticated or (configured and schema_valid)
    return coherent, odds


def _props_contract(props: Any) -> bool:
    if not isinstance(props, dict):
        return False
    if props.get("live_props_supported") is True:
        return bool(props.get("status"))
    return (
        props.get("live_props_supported") is False
        and props.get("status") == "UNAVAILABLE_WITHOUT_VERIFIED_PROP_FEED"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    base = args.base_url.rstrip("/")
    report: dict[str, Any] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base,
        "passed": False,
        "checks": {},
        "release_readiness_proven": False,
    }

    try:
        health = get_json(base + "/health")
        status = get_json(base + "/v1/system/status")
        props = get_json(base + "/v1/system/props")
        providers = get_json(base + "/v1/data/external-providers")
        evidence = get_json(base + "/v1/evidence/signals?limit=1")

        if not all(isinstance(item, dict) for item in (health, status, props, providers, evidence)):
            raise RuntimeError("one or more runtime endpoints returned a non-object JSON payload")

        storage = evidence.get("storage_status") or {}
        signals = evidence.get("signals") or []
        provider_ok, odds_provider = _provider_contract(providers)

        manual_review = (
            status.get("manual_review_only") is True
            or status.get("execution_mode") == "MANUAL_REVIEW_ONLY"
        )
        market_baseline = (
            status.get("market_baseline_only") is True
            or (status.get("models") or {}).get("marketBaselineFallback") is True
        )
        immutable_signal = (
            isinstance(signals, list)
            and len(signals) > 0
            and all(isinstance(row, dict) and row.get("immutable") is True for row in signals)
        )
        configured = storage.get("database_configured", storage.get("configured")) is True
        durable = evidence.get("durable_storage") is True and storage.get("durable") is True

        checks = {
            "health_ok": health.get("status") == "ok",
            "service_identity": health.get("service") == "philthysports-runtime",
            "product_identity": health.get("product") == "PhilthyParleys",
            "floot_runtime": health.get("host") == "Floot" and status.get("host") == "Floot",
            "manual_review_only": manual_review,
            "market_baseline_only": market_baseline,
            "props_contract_fail_closed": _props_contract(props),
            "provider_inventory_coherent": provider_ok,
            "evidence_database_configured": configured,
            "evidence_durable": durable,
            "evidence_floot_postgres": storage.get("mode") == "floot_postgres",
            "evidence_database_error_clear": storage.get("database_error_type") in (None, ""),
            "immutable_evidence_signal": immutable_signal,
        }

        report.update(
            runtime={
                "service": health.get("service"),
                "product": health.get("product"),
                "host": health.get("host"),
                "checked_at": health.get("checkedAt") or health.get("checked_at"),
            },
            execution={
                "manual_review_only": manual_review,
                "market_baseline_only": market_baseline,
            },
            props_status=props.get("status"),
            provider={
                "the_odds_api": odds_provider,
                "inventory_generated_at": providers.get("generated_at"),
            },
            evidence_storage={
                "durable_storage": evidence.get("durable_storage"),
                "storage_status": storage,
                "sample_signal": signals[0] if isinstance(signals, list) and signals else None,
            },
            checks=checks,
            passed=all(checks.values()),
        )
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    raise SystemExit(0 if report["passed"] else 2)


if __name__ == "__main__":
    main()
